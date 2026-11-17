$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") {
    throw "请在 Windows 电脑上运行此脚本。"
}

Push-Location $PSScriptRoot
try {
    if (-not (Test-Path "dist\质量节点\质量节点.exe")) {
        Write-Host "没有找到已生成的程序，先运行 build_windows.ps1。"
        & "$PSScriptRoot\build_windows.ps1"
        if ($LASTEXITCODE -ne 0) { throw "生成程序失败。" }
    }
    if (-not (Test-Path ".venv\Scripts\python.exe")) { throw "没有找到打包环境，请先运行 build_windows.ps1。" }

    & ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name "升级程序" upgrade.py
    if ($LASTEXITCODE -ne 0) { throw "生成升级程序失败。" }

    $pkg = "dist\升级包"
    if (Test-Path $pkg) { Remove-Item -Recurse -Force $pkg }
    New-Item -ItemType Directory -Path "$pkg\新版本" | Out-Null
    Copy-Item "dist\升级程序.exe" $pkg
    Copy-Item "升级说明.txt" $pkg
    Copy-Item "dist\质量节点" -Destination "$pkg\新版本" -Recurse

    $version = Get-Date -Format "yyyy-MM-dd"
    $manifest = @{ version = $version; folder = "质量节点"; exe = "质量节点.exe" } | ConvertTo-Json
    [System.IO.File]::WriteAllText("$pkg\upgrade.json", $manifest, (New-Object System.Text.UTF8Encoding($false)))

    $zip = "dist\质量节点-升级包-$version.zip"
    if (Test-Path $zip) { Remove-Item -Force $zip }
    Compress-Archive -Path "$pkg\*" -DestinationPath $zip

    Write-Host "升级包已生成：$zip"
    Write-Host "发给老师后，解压并双击“升级程序.exe”即可。"
} finally {
    Pop-Location
}
