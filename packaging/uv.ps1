# [INPUT]: 本机 uv 或官方固定版本安装脚本。
# [OUTPUT]: UTF-8 stdout 返回 uv.exe 的绝对路径；不改系统 PATH。
# [POS]: Windows 的 Python 引导，和 Unix 使用同版工具链。
# [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
# 本脚本也会由 Python 单独启动；须在缓存命中等提前返回之前设置编码。
$LoreLabUtf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $LoreLabUtf8
[Console]::OutputEncoding = $LoreLabUtf8
$OutputEncoding = $LoreLabUtf8
$UvExecutable = Join-Path $Destination 'uv.exe'
if (Test-Path -LiteralPath $UvExecutable) { Write-Output $UvExecutable; exit 0 }
$FoundUv = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
if ($FoundUv) { Write-Output $FoundUv.Source; exit 0 }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
New-Item -ItemType Directory -Force -Path $Destination | Out-Null
$InstallerFile = Join-Path $Destination 'install-uv.ps1'
Invoke-WebRequest -UseBasicParsing 'https://astral.sh/uv/0.9.26/install.ps1' -OutFile $InstallerFile
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerFile).Hash.ToLowerInvariant() -ne 'cd53e230e7062ddb90263480f244adda051f329fa694c14b78d659e1e901b76f') {
    throw 'uv bootstrap checksum mismatch'
}
$env:UV_UNMANAGED_INSTALL = $Destination
$env:UV_NO_MODIFY_PATH = '1'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $InstallerFile | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'uv bootstrap failed' }
if (-not (Test-Path -LiteralPath $UvExecutable)) { throw 'uv.exe missing after bootstrap' }
Write-Output $UvExecutable
