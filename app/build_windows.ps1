$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") {
    throw "请在 Windows 电脑上运行此打包脚本。"
}

Push-Location $PSScriptRoot
try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        py -3 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "无法创建 Python 开发环境。" }
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
