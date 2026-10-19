#!/bin/zsh
# Local LabChat launcher, recreated on this Mac.
set -eu
cd -- "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

fail() {
  print -r -- "$1"
  if [[ -t 0 ]]; then
    read '?按 Enter 關閉'
  fi
  exit 1
}

[[ -x .venv/bin/python ]] || fail '找不到虛擬環境，請先雙擊 install.command；詳見 docs/INSTALL_MAC.md。'
[[ -f scripts/mac_python.py && -f main.py ]] || fail '專案檔案不完整，請保留整個專案資料夾。'
.venv/bin/python -c 'import sys; assert sys.version_info >= (3, 11); from PySide6 import QtWidgets, QtNetwork' \
  || fail 'Python 或 Qt 環境不完整，請依 README 重新安裝套件。'

if [[ "${1:-}" == --check ]]; then
  exec .venv/bin/python scripts/check_install.py
fi

service_ready() {
  curl --noproxy '*' -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1
}

if ! service_ready; then
  command -v ollama >/dev/null || fail '找不到 Ollama，請先安裝。'
  mkdir -p .logs
  if [[ -f .logs/ollama.log ]]; then
    mv -f .logs/ollama.log .logs/ollama.previous.log
  fi
  OLLAMA_HOST=127.0.0.1:11434 OLLAMA_NO_CLOUD=1 OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_NUM_PARALLEL=1 nohup ollama serve >.logs/ollama.log 2>&1 </dev/null &
  for attempt in {1..30}; do
    service_ready && break
    sleep 1
  done
  service_ready || fail 'Ollama 啟動失敗，請查看 .logs/ollama.log。'
fi

if .venv/bin/python scripts/mac_python.py; then
  exit 0
else
  fail '程式未正常結束，請保留上方錯誤，並執行 .venv/bin/python scripts/check_install.py 檢查。'
fi
