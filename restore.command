#!/bin/zsh
# Rebuild local packages/models after the user selects a profile and confirms downloads.
set -eu
cd -- "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
python_program="$(command -v python3.11 || true)"
if [[ -z "$python_program" && -x /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 ]]; then
  python_program=/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
fi
if [[ -z "$python_program" ]]; then
  print -r -- '尚未安裝 Python 3.11。請依 docs/REBUILD_MAC.md 安裝系統工具，再重開此檔案。'
  print -r -- '已安裝且支援 Homebrew 者，可在專案執行：brew bundle --file Brewfile'
  if [[ -t 0 ]]; then read '?按 Enter 關閉'; fi
  exit 1
fi
if "$python_program" scripts/restore_environment.py "$@"; then
  if [[ -t 0 ]]; then read '?按 Enter 關閉'; fi
else
  print -r -- '復刻尚未完成。請保留上方錯誤，依 docs/REBUILD_MAC.md 處理後重試。'
  if [[ -t 0 ]]; then read '?按 Enter 關閉'; fi
  exit 1
fi
