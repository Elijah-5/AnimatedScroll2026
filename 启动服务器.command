#!/bin/zsh
cd -- "${0:A:h}" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
PYTHON=".venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
"$PYTHON" scripts/server_control.py start
RESULT=$?
printf '\n按回车关闭此窗口（后台服务会继续运行）…'
read -r
exit "$RESULT"
