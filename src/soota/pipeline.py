from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from soota.config import SootaSettings, ensure_dirs
from soota.errors import AuthBudgetError, InputError, SourceError
from soota.models import (
    AnalysisManifest,
    AnalysisStatus,
    CommandResult,
    ContentBundleManifest,
    ProcessingManifest,
    TranscriptDocument,
    TranscriptManifest,
    TranscriptMode,
    TranscriptStatus,
)
from soota.providers.tikhub.capability import capabilities_for
from soota.providers.tikhub.client import TikHubProvider
from soota.render.analysis import load_analysis
from soota.render.bundle import write_bundle
from soota.routing import recognize
from soota.secrets import api_key_present, load_tikhub_api_key
from soota.storage.cache import CacheStore
from soota.storage.jobs import JobStore
from soota.storage.ledger import CostLedger
from soota.transcripts.asr import AsrEngine, resolve_engine
from soota.transcripts.resolver import TranscriptResolver

INGESTABLE_KINDS = {"video", "shortlink"}


def _provider(
    settings: SootaSettings,
    cache: CacheStore,
    requester: Callable[..., Any] | None = None,
) -> TikHubProvider:
    return TikHubProvider(
        cache=cache,
        api_key=load_tikhub_api_key(),
        base_url=settings.tikhub.base_url,
        timeout=settings.tikhub.timeout_seconds,
        requester=requester,
        preferred_language=settings.default_language,
    )


def doctor(settings: SootaSettings) -> CommandResult:
    ensure_dirs(settings)
    from soota import TIKHUB_SDK_VERSION, __version__

    tikhub_ok = False
    tikhub_ver = None
    try:
        import tikhub

        tikhub_ok = True
        tikhub_ver = getattr(tikhub, "__version__", None) or TIKHUB_SDK_VERSION
    except ImportError:
        tikhub_ok = False
    asr_engine = resolve_engine(settings.asr)
    data = {
        "soota_version": __version__,
        "tikhub_sdk_required": TIKHUB_SDK_VERSION,
        "tikhub_sdk_installed": tikhub_ver,
        "tikhub_import_ok": tikhub_ok,
        "api_key_present": api_key_present(),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "whisper_cli": bool(shutil.which(settings.asr.whisper_bin)),
        "asr_engine": asr_engine.name,
        "asr_model": settings.asr.model,
        "config_path": str(settings.config_path),
        "cache_dir": str(settings.cache_dir),
        "data_dir": str(settings.data_dir),
        "output_dir": str(settings.output_dir),
    }
    warnings: list[str] = []
    if not data["api_key_present"]:
        warnings.append("未检测到 TikHub API Key；inspect 仍可识别 URL，ingest 需要密钥。")
    if not data["ffmpeg"]:
        warnings.append("未找到 ffmpeg，无字幕音频抽取可能失败。")
    if not data["whisper_cli"] and asr_engine.name == "whisper-cli":
        warnings.append("未找到 whisper CLI；无字幕路径在运行 ASR 前会失败。")
    return CommandResult(
        ok=True,
        status="success",
        code="ok",
        exit_code=0,
        message="doctor 完成。",
        data=data,
        warnings=warnings,
    )


def inspect(
    settings: SootaSettings, url: str, *, fetch: bool = True, requester: Callable[..., Any] | None = None
) -> CommandResult:
    source = recognize(url)
    caps = capabilities_for(source)
    data: dict[str, Any] = {
        "source": source.model_dump(),
        "capabilities": caps.model_dump(),
        "metadata": None,
    }
    warnings: list[str] = []
    if source.kind not in INGESTABLE_KINDS:
        warnings.append("目录来源请使用 catalog；先加 --dry-run 预估。" if caps.catalog else "该来源暂不支持采集。")
    if not fetch or not caps.inspect:
        return CommandResult(
            ok=True,
            status="success",
            code="ok",
            exit_code=0,
            message="已识别来源。",
            data=data,
            warnings=warnings,
        )
    if not api_key_present() and requester is None:
        warnings.append("没有 API Key，只返回 URL 识别结果。")
        return CommandResult(
            ok=True,
            status="success",
            code="ok",
            exit_code=0,
            message="已识别来源。",
            data=data,
            warnings=warnings,
        )
    cache = CacheStore(settings.cache_dir)
    provider = _provider(settings, cache, requester=requester)
    item = provider.inspect(source)
    data["source"] = item.source.model_dump()
    data["metadata"] = {
        "title": item.title,
        "creator": item.creator,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "duration_seconds": item.duration_seconds,
        "extras": item.extras,
    }
    data["requests"] = [r.model_dump() for r in provider.records]
    return CommandResult(
        ok=True,
        status="success",
        code="ok",
        exit_code=0,
        message="inspect 完成。",
        data=data,
        warnings=warnings,
    )


def estimate(
    settings: SootaSettings,
    url: str,
    *,
    mode: str = "ingest",
    transcript: TranscriptMode = TranscriptMode.AUTO,
    max_items: int = 100,
    max_pages: int = 10,
    requester: Callable[..., Any] | None = None,
) -> CommandResult:
    if mode == "catalog":
        from soota.catalog import estimate_catalog

        return estimate_catalog(settings, url, max_items=max_items, max_pages=max_pages)
    if mode != "ingest":
        raise InputError("--mode 只支持 ingest 或 catalog。")
    source = recognize(url)
    cache = CacheStore(settings.cache_dir)
    provider = _provider(settings, cache, requester=requester)
    need_captions = transcript in {TranscriptMode.AUTO, TranscriptMode.CAPTIONS_ONLY}
    need_audio = transcript in {TranscriptMode.AUTO, TranscriptMode.ASR}
    if cache.has(source, "transcript"):
        endpoints: list[str] = []
    else:
        endpoints = provider.estimate_requests(source, need_captions=need_captions, need_audio=need_audio)
        if cache.has(source, "inspect"):
            endpoints = [
                e
                for e in endpoints
                if e
                not in {
                    "/api/v1/youtube/web_v2/get_video_info_v2",
                    "/api/v1/bilibili/web/fetch_one_video",
                    "/api/v1/bilibili/web/fetch_one_video_v3",
                }
            ]
        if cache.has(source, "captions"):
            endpoints = [e for e in endpoints if "caption" not in e and "subtitle" not in e]
        if cache.has(source, "audio") or cache.audio_path(source).is_file():
            endpoints = [e for e in endpoints if "stream" not in e and "playurl" not in e]
    cost, basis = provider.estimate_cost(endpoints)
    warnings: list[str] = []
    wallet_view: dict[str, Any] | None = None
    try:
        wallet = provider.get_wallet()
    except Exception:
        warnings.append("无法读取 TikHub 余额，估价未与钱包核对。")
        wallet = None
    if wallet is not None:
        wallet_view = provider.assess_wallet(endpoints, wallet)
        if wallet_view.get("sufficient") is False:
            paid_need = wallet_view.get("paid_required_usd")
            warnings.append(
                f"TikHub 余额不足：预计需要付费余额 {paid_need} USD，"
                f"当前付费余额 {wallet_view.get('balance')}、免费额度 {wallet_view.get('free_credit')}。"
                "免费额度不能用于不接受它的接口。"
            )
    short = bool(wallet_view and wallet_view.get("sufficient") is False)
    return CommandResult(
        ok=True,
        status="success",
        code="ok",
        exit_code=0,
        message="估价完成。",
        hint="到 https://user.tikhub.io/dashboard/add-credit 充值后再 ingest。" if short else None,
        data={
            "mode": mode,
            "source": source.model_dump(),
            "endpoints": endpoints,
            "request_count": len(endpoints),
            "estimated_cost_usd": cost,
            "price_basis": basis,
            "cache_hit": not endpoints,
            "wallet": wallet_view,
        },
        warnings=warnings,
    )


def ingest(
    settings: SootaSettings,
    url: str,
    *,
    transcript: TranscriptMode = TranscriptMode.AUTO,
    output: Path | None = None,
    max_cost: float | None = None,
    dry_run: bool = False,
    force: bool = False,
    requester: Callable[..., Any] | None = None,
    asr: AsrEngine | None = None,
) -> CommandResult:
    ensure_dirs(settings)
    source = recognize(url)
    if source.kind not in INGESTABLE_KINDS:
        raise SourceError("ingest 只摄取单条视频。", hint="频道目录请使用 catalog URL --dry-run。")
    caps = capabilities_for(source)
    if not caps.inspect:
        raise SourceError("该来源不支持摄取。")
    guessed = estimate(settings, url, mode="ingest", transcript=transcript, requester=requester)
    estimated = guessed.data.get("estimated_cost_usd")
    if max_cost is not None:
        over = estimated is None or float(estimated) > max_cost
        if over:
            raise AuthBudgetError(
                f"预计费用 {estimated} USD 超过 --max-cost {max_cost}，或价格未知。",
                hint="提高上限、先 estimate，或等缓存命中后再跑。未知单价时硬限制拒绝执行。",
            )
    wallet_view = guessed.data.get("wallet") if isinstance(guessed.data, dict) else None
    if isinstance(wallet_view, dict) and wallet_view.get("sufficient") is False and not dry_run:
        raise AuthBudgetError(
            (
                f"TikHub 付费余额不足：预计需要付费余额 {wallet_view.get('paid_required_usd')} USD，"
                f"当前 {wallet_view.get('balance')}（免费额度 {wallet_view.get('free_credit')} "
                "不能用于这些接口）。"
            ),
            hint="到 https://user.tikhub.io/dashboard/add-credit 充值后再 ingest。不要重试会 402 的计费接口。",
            details={"wallet": wallet_view, "estimated_cost_usd": estimated},
        )
    if dry_run:
        return guessed.model_copy(update={"message": "dry-run：未发起付费请求。"})

    output_root = (output or settings.output_dir).expanduser()
    cache = CacheStore(settings.cache_dir)
    provider = _provider(settings, cache, requester=requester)
    resolver = TranscriptResolver(provider, cache, settings, asr=asr)
    try:
        item = provider.inspect(source)
        document = resolver.resolve(item, transcript)
    except Exception:
        if provider.records:
            CostLedger(settings.ledger_path).append(source.id, provider.records)
        raise
    billed = [r for r in provider.records if r.billed and not r.cache_hit]
    cost = sum(r.estimated_cost_usd or 0.0 for r in billed)
    manifest = ContentBundleManifest(
        source=item.source,
        transcript=TranscriptManifest(
            status=document.status,
            source=document.source,
            language=document.language,
            segments=len(document.segments),
        ),
        analysis=AnalysisManifest(status=AnalysisStatus.PENDING, path="content.md"),
        processing=ProcessingManifest(
            provider="tikhub",
            cache_hit=all(r.cache_hit or not r.billed for r in provider.records) and bool(provider.records),
            estimated_cost_usd=cost,
            actual_cost_usd=cost,
            request_count=len(billed),
            price_basis=f"snapshot:{provider.snapshot.get('as_of')}",
            requests=provider.records,
        ),
    )
    manifest.metadata_from_item(item)
    folder = write_bundle(output_root, item, document, manifest, None, force=force)
    CostLedger(settings.ledger_path).append(item.source.id, provider.records)
    JobStore(settings.jobs_dir).create(
        {
            "status": "completed" if document.status is TranscriptStatus.READY else "partial",
            "source": item.source.model_dump(),
            "output": str(folder),
            "transcript_status": document.status,
        }
    )
    status: Literal["success", "partial"] = "success" if document.status is TranscriptStatus.READY else "partial"
    code = "ok" if status == "success" else "transcript_missing"
    return CommandResult(
        ok=status == "success",
        status=status,
        code=code,
        exit_code=0 if status == "success" else 2,
        message="摄取完成。" if status == "success" else "已保存元数据，字幕仍缺失。",
        data={
            "output": str(folder),
            "manifest": str(folder / "manifest.json"),
            "transcript": str(folder / "transcript.md"),
            "content": str(folder / "content.md"),
            "source": item.source.model_dump(),
            "transcript_status": document.status,
            "transcript_source": document.source,
            "cache_hit": manifest.processing.cache_hit,
            "request_count": manifest.processing.request_count,
            "estimated_cost_usd": manifest.processing.estimated_cost_usd,
            "requests": [r.model_dump() for r in provider.records],
        },
    )


def render(
    settings: SootaSettings,
    *,
    bundle: Path,
    analysis: Path,
    force: bool = False,
) -> CommandResult:
    manifest_path = bundle if bundle.name == "manifest.json" else bundle / "manifest.json"
    if not manifest_path.is_file():
        raise InputError("找不到 manifest.json。", hint="先 ingest 再 render。")
    folder = manifest_path.parent
    existing_content = folder / "content.md"
    previous = existing_content.read_bytes() if existing_content.is_file() else None
    try:
        parsed = load_analysis(analysis)
    except Exception:
        if previous is not None:
            existing_content.write_bytes(previous)
        raise
    manifest = ContentBundleManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    from soota.models import MediaItem
    from soota.render.bundle import write_bundle_to

    meta = manifest.metadata or {}
    published = meta.get("published_at")
    published_at = None
    if isinstance(published, str) and published:
        from datetime import datetime

        published_at = datetime.fromisoformat(published)
    item = MediaItem(
        source=manifest.source,
        title=meta.get("title"),
        creator=meta.get("creator"),
        published_at=published_at,
        duration_seconds=meta.get("duration_seconds"),
        language=meta.get("language"),
    )
    document = _document_from_transcript_md(folder / "transcript.md", manifest)
    write_bundle_to(folder, item, document, manifest, parsed, force=True)
    return CommandResult(
        ok=True,
        status="success",
        code="ok",
        exit_code=0,
        message="已渲染 content.md。",
        data={"content": str(folder / "content.md"), "manifest": str(manifest_path)},
    )


def _document_from_transcript_md(path: Path, manifest: ContentBundleManifest) -> TranscriptDocument:
    from soota.models import TranscriptDocument, TranscriptSegment, TranscriptSource

    segments: list[TranscriptSegment] = []
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        current_id = None
        current_time = "00:00:00-00:00:00"
        buf: list[str] = []
        for line in text.splitlines():
            if line.startswith("## seg-"):
                if current_id:
                    start, end = _parse_heading_time(current_time)
                    segments.append(
                        TranscriptSegment(
                            segment_id=current_id,
                            start_ms=start,
                            end_ms=end,
                            text=" ".join(buf).strip(),
                            language=manifest.transcript.language,
                            source=manifest.transcript.source or TranscriptSource.OFFICIAL,
                        )
                    )
                header = line[3:].strip()
                current_id = header.split("·")[0].strip()
                current_time = header.split("·", 1)[1].strip() if "·" in header else "00:00:00-00:00:00"
                buf = []
            elif line.startswith("<a id="):
                continue
            elif current_id:
                buf.append(line)
        if current_id:
            start, end = _parse_heading_time(current_time)
            segments.append(
                TranscriptSegment(
                    segment_id=current_id,
                    start_ms=start,
                    end_ms=end,
                    text=" ".join(buf).strip(),
                    language=manifest.transcript.language,
                    source=manifest.transcript.source or TranscriptSource.OFFICIAL,
                )
            )
    return TranscriptDocument(
        status=manifest.transcript.status,
        source=manifest.transcript.source,
        language=manifest.transcript.language,
        segments=segments,
    )


def _parse_heading_time(value: str) -> tuple[int, int]:
    from soota.transcripts.captions import clock_to_ms

    left, right = (value.split("-", 1) + ["00:00:00"])[:2]
    try:
        return clock_to_ms(left.strip() + ".000"), clock_to_ms(right.strip() + ".000")
    except Exception:
        return 0, 0


def list_jobs(settings: SootaSettings) -> CommandResult:
    jobs = JobStore(settings.jobs_dir).list_jobs()
    jobs = [
        {
            **{
                key: job[key]
                for key in ("id", "kind", "status", "source", "created_at", "updated_at", "stop_reason")
                if key in job
            },
            "item_count": len(job.get("items", [])),
            "pages_fetched": job.get("pages_fetched", 0),
        }
        if job.get("kind") == "catalog"
        else job
        for job in jobs
    ]
    return CommandResult(
        ok=True,
        status="success",
        code="ok",
        exit_code=0,
        message=f"{len(jobs)} 个任务。",
        data={"jobs": jobs},
    )
