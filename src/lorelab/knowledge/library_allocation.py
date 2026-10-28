"""[INPUT]: 共享库身份、类别分配计划与目的地写锁。
[OUTPUT]: 不随分类回滚倒退的编号分配记录，防止旧任务误认复用的 ID。
[POS]: 自适应分类的单调分配边界；调用方必须持有 writer 锁。
[PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
"""

from itertools import pairwise
from pathlib import Path

from .workflow_state import inside, read_json, require, write_json

FILE = "分类编号.json"


def load(root: Path, taxonomy: dict) -> dict:
    path = inside(root, FILE)
    if not path.exists():
        return {"schema_version": 1, "library_id": taxonomy["id"],
                "next_code": taxonomy.get("next_code", 1), "reservations": {}}
    data = read_json(path)
    require(isinstance(data, dict) and data.get("schema_version") == 1
            and data.get("library_id") == taxonomy["id"]
            and type(data.get("next_code")) is int and data["next_code"] > 0
            and isinstance(data.get("reservations"), dict), "分类编号记录无效或属于其他知识库。")
    ranges = []
    for key, value in data["reservations"].items():
        require(isinstance(key, str) and isinstance(value, list) and len(value) == 2
                and all(type(n) is int for n in value) and 0 < value[0] < value[1] <= data["next_code"],
                "分类编号预留范围无效。")
        ranges.append(value)
    ranges.sort()
    require(all(a[1] <= b[0] for a, b in pairwise(ranges)), "分类编号预留范围重叠。")
    return data


def start(root: Path, taxonomy: dict) -> int:
    return max(load(root, taxonomy)["next_code"], taxonomy.get("next_code", 1))


def reserve(root: Path, taxonomy: dict, job: Path, allocation: list[int]):
    first, end = allocation
    if first == end:
        return
    data = load(root, taxonomy)
    token = job.name
    if token in data["reservations"]:
        require(data["reservations"][token] == allocation, "任务的分类编号预留已改变。")
        return
    require(max(data["next_code"], taxonomy.get("next_code", 1)) <= first,
            "分类编号已被其他任务使用，请重新准备分类审阅。")
    data["reservations"][token] = allocation
    data["next_code"] = end
    write_json(inside(root, FILE), data)
