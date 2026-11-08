@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" desktop.py
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    python desktop.py
  ) else (
    py -3 desktop.py
  )
)
if errorlevel 1 (
  echo 启动失败，请确认已安装 Python 3。
  pause
)
