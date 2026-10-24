# [INPUT]: Agent 克隆的源码仓库和安装器参数。
# [OUTPUT]: UTF-8 命令链路及用户目录中的四个 CLI / Skill，保留已有配置与任务。
# [POS]: Windows 原生源码安装入口，不依赖 WSL 或预构建发行包。
# [PROTOCOL]: 变更时更新此头部，然后检查 AGENTS.md
$ErrorActionPreference = 'Stop'
# 原生命令的捕获和 PowerShell 的输出都使用 UTF-8，不依赖当前代码页。
$LoreLabUtf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $LoreLabUtf8
[Console]::OutputEncoding = $LoreLabUtf8
$OutputEncoding = $LoreLabUtf8
$RepositoryRoot = $PSScriptRoot
$InstallPrefix = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local\share\lorelab'
$InstallerArgs = @($args)
for ($Index = 0; $Index -lt $InstallerArgs.Count; $Index++) {
    if ($InstallerArgs[$Index] -eq '--prefix') {
        $Index++
        if ($Index -ge $InstallerArgs.Count) { throw '--prefix requires a directory' }
        $InstallPrefix = $InstallerArgs[$Index]
    } elseif ($InstallerArgs[$Index].StartsWith('--prefix=')) {
        $InstallPrefix = $InstallerArgs[$Index].Substring(9)
    } elseif ($InstallerArgs[$Index] -in @('-h','--help')) {
        Write-Output 'install.ps1 [--prefix DIR] [--skills-dir DIR | --no-skills] [--bin-dir DIR | --no-bin] [--force]'
        exit 0
    }
}
$InstallPrefix = [IO.Path]::GetFullPath($InstallPrefix)
$PythonExecutable = Join-Path $InstallPrefix 'current\venv\Scripts\python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
if (-not (Test-Path -LiteralPath $PythonExecutable)) {
    $UvExecutable = & (Join-Path $RepositoryRoot 'packaging\uv.ps1') (Join-Path $InstallPrefix 'toolchain\uv')
    foreach ($VariableName in @('UV_PYTHON_PREFERENCE','UV_PYTHON','UV_MANAGED_PYTHON','UV_NO_MANAGED_PYTHON','UV_PYTHON_DOWNLOADS')) {
        [Environment]::SetEnvironmentVariable($VariableName, $null, 'Process')
    }
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $InstallPrefix 'toolchain\python'
    $env:UV_CACHE_DIR = Join-Path $InstallPrefix 'toolchain\cache'
    $env:UV_PYTHON_INSTALL_BIN = 'false'
    & $UvExecutable --no-config python install --no-bin 3.12.12
    if ($LASTEXITCODE -ne 0) { throw 'Python bootstrap failed' }
    $PythonExecutable = & $UvExecutable --no-config python find --managed-python 3.12.12
    if ($LASTEXITCODE -ne 0) { throw 'Python lookup failed' }
    $env:LORELAB_INSTALL_UV = $UvExecutable
    $env:LOREHUB_INSTALL_UV = $UvExecutable
}
& $PythonExecutable -X utf8 -I -B (Join-Path $RepositoryRoot 'packaging\install.py') @InstallerArgs
exit $LASTEXITCODE
