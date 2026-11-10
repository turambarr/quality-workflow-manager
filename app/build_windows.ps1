$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") {
    throw "请在 Windows 电脑上运行此打包脚本。"
}

Push-Location $PSScriptRoot
try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        $created = $false
        foreach ($exe in @("py", "python")) {
            if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
            $pyargs = if ($exe -eq "py") { @("-3") } else { @() }
            & $exe @pyargs -m venv .venv
            if ($LASTEXITCODE -eq 0) { $created = $true; break }
            Write-Host "用 $exe 创建环境失败，换另一个 Python 试试。"
            if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }
        }
        if (-not $created) {
            throw "没有找到可用的 Python。请安装 Python 3.9 以上版本（勾选 Add python.exe to PATH），或在 Anaconda Prompt 里运行本脚本。"
        }
    }
    & ".venv\Scripts\python.exe" -m pip install -r requirements-desktop.txt
    if ($LASTEXITCODE -ne 0) { throw "安装打包组件失败。" }
    & ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onedir --windowed --name "质量节点" --add-data "web;web" --add-data "presets.json;." desktop.py
    if ($LASTEXITCODE -ne 0) { throw "生成程序失败。" }
    Write-Host "程序已生成，请在 dist\质量节点 中打开质量节点.exe。"
    Write-Host "分发时请复制整个质量节点文件夹。"
} finally {
    Pop-Location
}
