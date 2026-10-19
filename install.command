#!/bin/zsh
# First-time package setup only; no models, system packages or permissions changed.
set -eu
cd -- "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
fail() {
  print -r -- "$1"
  if [[ -t 0 ]]; then read '?按 Enter 關閉'; fi
  exit 1
}
[[ "$(uname -s)" == Darwin ]] || fail '此安裝入口僅支援 Mac，其他系統請參閱對應文件。'
python_program="$(command -v python3.11 || true)"
if [[ -z "$python_program" && -x /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11 ]]; then
  python_program=/Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11
fi
[[ -n "$python_program" ]] || fail '請先安裝 Python 3.11，再重新開啟 install.command。詳細步驟：docs/INSTALL_MAC.md'
if ! "$python_program" scripts/setup_mac.py; then
  fail '安裝未完成，請查看上方錯誤。可保留此畫面並依 docs/INSTALL_MAC.md 排除。'
fi
print -r -- '以後請使用 run.command 開啟程式。'
if [[ -t 0 ]]; then read '?按 Enter 關閉'; fi
