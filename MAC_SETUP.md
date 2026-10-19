# Mac 移機與安裝指南

> **GitHub 新使用者請先閱讀 [目前 Mac 安裝圖解](docs/INSTALL_MAC.md)。本文件保留較早的來源包／移機流程；舊 ZIP 與 HANDOFF_MANIFEST 的校驗不是目前 GitHub 安裝步驟。首次安裝用 install.command，日常啟動用 run.command。**

> **2026-10-16 Mac mini M4 最新交付入口：請先讀 [MAC_MINI_M4_START.md](MAC_MINI_M4_START.md)。本次已授權更新 Mac 來源 ZIP，較早的「尚未打包」敘述是歷史紀錄。Windows ZIP 本次未重建。**

核對日期：2026-10-15。適用 macOS 14 Sonoma 或更新版本；本專案目前鎖定的六個 Qt 套件皆提供 `macosx_14_0_universal2` wheel，包含 arm64 與 x86_64。更舊 macOS 不適用此鎖版，不建議直接取消鎖版強行安裝。

## 1. 確認新 Mac

在「關於這台 Mac」確認系統、晶片與記憶體，也可於終端機執行：

```sh
sw_vers -productVersion
uname -m
```

- Apple Silicon（M 系列）：使用原生 arm64 Python 與 Ollama，避免混用 Rosetta x86_64 環境。若終端機設定以 Rosetta 開啟，先關閉該設定。
- Intel Mac：使用 x86_64 Python。Ollama 官方說明 Intel Mac 僅 CPU 推論，速度可能顯著慢於 M 系列；目前未在 Intel 實機驗證。
- 以 2B 模型為起點；8GB 記憶體須觀察實際壓力，勿假設更大模型一定可用。新 Mac 的速度與記憶體容量需要重新驗收。

## 2. 檔案與校驗

一起搬移 `labchat-mac-handoff.zip` 與 `.zip.sha256`。在兩個檔案所在目錄執行：

```sh
shasum -a 256 -c labchat-mac-handoff.zip.sha256
```

應顯示 `OK`。另外保留原機校驗碼比對；雜湊不是數位簽章。解壓到新的、自己可寫入的資料夾，例如 `~/Projects/labchat`；下方假設程式就在此目錄。不要覆蓋正在使用且有未匯出標註的專案。

ZIP 包含完整原始碼、Logo、測試、安裝與 Codex 交接文件、Mac 啟動檔及逐檔清單。不包含舊 `.venv`、模型、日誌、私人圖片或歷史標註。即使兩台都是 Mac，也應重新建立虛擬環境。舊程式的標註需先另行匯出 PNG／JSON；尚未儲存的聊天、草稿與框不會自動搬過來。

## 3. 安裝 Python 與 Ollama

1. 從 [Python 官方 macOS 下載頁](https://www.python.org/downloads/macos/) 選擇提供安裝程式的 CPython 3.11 或 3.12。下方以 `python3.11` 為例；若安裝3.12，改用 `python3.12`。不要改動系統 Python。
2. 若原本已使用 Homebrew，也可安裝 `python@3.11`；Apple Silicon 通常在 `/opt/homebrew/bin/python3.11`，Intel 通常在 `/usr/local/bin/python3.11`。兩種安裝來源擇一，不需兩種都裝。
3. 從 [Ollama 官方 Mac 下載頁](https://ollama.com/download/mac) 安裝應用程式並首次開啟，依提示建立 CLI，再確認 `ollama --version`。不用 Docker 或 Xcode 作為一般執行環境。

核對版本與 Python 執行架構：

```sh
python3.11 --version
python3.11 -c 'import platform; print(platform.machine())'
ollama --version
```

若找不到命令，先確認安裝及 PATH，重新開啟終端機；不要將舊 Mac 的 Python 執行檔複製過來。

## 4. 驗證來源並建立環境

逐行執行；出錯就先處理，不要繼續下一行：

```sh
cd ~/Projects/labchat
python3.11 scripts/verify_handoff.py
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip check
.venv/bin/python -c 'from PySide6 import QtCore, QtWidgets, QtNetwork; print(QtCore.__version__)'
chmod u+x run.command
```

若已有舊環境，先改名備份或移出，勿覆蓋使用。驗證器只需標準 Python，不需安裝 Qt；若內容不符，先重新取得正確來源包。

## 5. Ollama 本機與模型設定

若 Ollama App 已啟動，先從選單列正常退出，再設定 App 啟動時繼承的環境變數：

```sh
launchctl setenv OLLAMA_HOST '127.0.0.1:11434'
launchctl setenv OLLAMA_NO_CLOUD '1'
launchctl setenv OLLAMA_MAX_LOADED_MODELS '1'
launchctl setenv OLLAMA_NUM_PARALLEL '1'
open -a Ollama
```

這些 launchctl 設定不是跨重新開機的永久設定；重開機後若使用 Ollama App，需重新套用並重新開啟 App。`run.command` 在服務尚未啟動時會以同樣參數啟動 `ollama serve`；若服務已存在，則不修改其設定。不要同時啟動兩個服務，也不要監聽 `0.0.0.0`。

確認本機 API，下載預設模型：

```sh
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:11434/api/version
ollama pull qwen3.5:2b
ollama list
```

原 Mac 的模型沒有放在 ZIP，選單列出某個模型不代表新電腦已下載。模型與套件安裝需要網路，之後使用已安裝的本機模型不需要雲端推論。4B／0.8B 僅在有需要時另行 `ollama pull`，不自動下載。

## 6. 啟動、語音與驗收

若要使用麥克風輸入，先依 [VOICE_INPUT.md](VOICE_INPUT.md) 安裝 `whisper.cpp` 與 small 多語言模型。來源包不含模型或 `.runtime`；`run.command` 會在新機建立含麥克風用途宣告的本機啟動環境。只需文字／圖片功能時，可先不安裝 Whisper，缺少依賴不影響打字。


```sh
./run.command
```

也可以在 Finder 雙擊 `run.command`。若 Finder 對網路下載檔案提出安全提示，先完成來源校驗，依 macOS 官方允許開啟流程處理；不要關閉整體 Gatekeeper 或全域移除安全保護。終端機可用 `zsh run.command` 明確執行已核對的腳本。

在介面按「設定 → 檢查本機服務」，測試文字、圖片、處理中動畫、停止／取消，以及框選、改名、刪除與 PNG／JSON 匯出。AI 框與計數需要人工核對；圖片僅隨當次問題傳送，追問圖片請重新附加。匯出圖使用最長1024像素的預處理圖片。

Mac 已有 `/usr/bin/say` 語音後端，可先在終端機列出聲音（不會播放）：

```sh
/usr/bin/say -v '?'
```

在程式「設定 → 語音與朗讀」重新整理並試聽；聲音與品質依新 Mac 已安裝的語音資源而定，無法隨 ZIP 搬移。若沒有中文聲音，依 [Apple 語音設定說明](https://support.apple.com/guide/mac-help/change-the-voice-your-mac-uses-to-speak-text-mchlp2290/mac) 下載後重新整理。本工具會優先選擇 Meijia，但新機未必已安裝；不要假設一定有相同音色。

開發與回歸檢查：

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m ruff check main.py labchat tests scripts
.venv/bin/python -m ruff format --check main.py labchat tests scripts
QT_QPA_PLATFORM=offscreen .venv/bin/python -X faulthandler -m unittest discover -s tests -q
zsh -n run.command
```

離屏測試只套用到該命令，不影響正常視窗。測試需本機 loopback 權限，不需下載模型；真實模型可選擇執行 `.venv/bin/python scripts/smoke_local.py`。舊機測試通過不代表所有新 Mac 已驗證，仍需檢查顯示縮放、中文輸入法、真實模型及聲音。

日誌在專案 `.logs/`；Ollama App 日誌通常在 `~/.ollama/logs`。分享診斷前先檢視私人資訊。此包不是離線套件安裝包，也不含完整 Codex 舊對話；請讓新電腦 Codex 閱讀 MAC_CODEX_HANDOFF.md。

## 官方依據

- [Ollama macOS 需求：macOS14以上，M系列CPU/GPU、Intel CPU](https://docs.ollama.com/macos)
- [Ollama 環境變數與本機設定](https://docs.ollama.com/faq)
- [Qt for Python 安裝與虛擬環境](https://doc.qt.io/qtforpython-6/gettingstarted.html)
- [Python macOS 安裝檔](https://www.python.org/downloads/macos/)

六個鎖定 Qt 套件的 macOS14 universal2 wheel 已於本次查詢 PyPI 官方資料核對。目標機仍須實際安裝與驗收。

## 新版對話紀錄注意事項

新版成功文字問答另存於系統使用者資料目錄，不在原始碼ZIP內。Mac常見路徑為~/Library/Application Support/AI-System-Lab/conversations.sqlite3，實際位置請看程式對話紀錄視窗。私人紀錄不會自動跟著移機，若另行備份請先完全關閉程式。最新來源包已納入對話紀錄、Labelme 匯出、語音輸入、共用主題、Markdown 排版與提問配色。
