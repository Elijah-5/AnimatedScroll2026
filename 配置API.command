#!/bin/zsh
cd -- "${0:A:h}" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
PYTHON=".venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
"$PYTHON" scripts/configure_api.py
RESULT=$?
printf '\n按回车关闭此窗口…'
read -r
exit "$RESULT"
