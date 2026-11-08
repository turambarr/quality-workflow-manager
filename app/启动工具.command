#!/bin/zsh
set -eu
cd "$(dirname "$0")"
if [[ -x ".venv/bin/python" ]]; then
  exec .venv/bin/python desktop.py
elif command -v python3 >/dev/null 2>&1; then
  exec python3 desktop.py
else
  print "此电脑尚未安装 Python 3，请先安装后再打开工具。"
  read "?按回车键关闭窗口。"
fi
