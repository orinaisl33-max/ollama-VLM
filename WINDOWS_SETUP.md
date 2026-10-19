# Windows 移機與安裝指南

核對日期：2026-10-15。適用 Windows x64 原生 Python／Ollama；不以 WSL、Windows ARM 或打包 EXE 為本指南的驗證範圍。

## 先了解移機範圍

本專案是「人工智慧系統實驗室 · 展示工具」，包含文字對話、圖片理解、人工標註、AI 建議框、PNG／JSON 匯出及 macOS 朗讀。

**目前沒有 Windows 實機驗證紀錄。語音輸入僅驗證 Mac，Windows 麥克風按鈕停用；Windows TTS 尚未實作。** 已核對所有六個鎖定 Qt 套件均有 Windows x64 wheel；這只代表安裝套件具備平台支援，不代表所有功能已通過 Windows 測試。Windows 朗讀尚未實作，應停用；聊天及影像功能仍須依下方清單驗收。UI 的 macOS 字型在 Windows 會發生字型替代，須檢查中文顯示及標籤尺寸。

## 1. 搬哪些檔案

複製專案的原始碼、`labchat/`、`assets/`、`scripts/`、`tests/`、`logo.png`、所有 requirements 檔、`pyproject.toml`、啟動檔與 Markdown 文件。可使用隨附的 `scripts/package_handoff.py` 產生移機 ZIP。

不要搬用 `.venv/`、`.venv-*/`、`.logs/`、快取或 macOS Python 執行檔。虛擬環境不可跨作業系統共用。Ollama 模型與專案 `models/` 的 Whisper 模型均不在來源包裡，新電腦須另外下載；不建議直接複製 Mac 的模型快取。

如需舊標註，先在舊程式匯出 PNG 與 JSON，再個別搬移。新版會將成功完成的文字問答存於系統使用者資料目錄，並不在原始碼資料夾內；新版草稿也可保存，圖片／標註需明確啟用保存；語音設定仍只存於記憶體。最新行為見FEATURES.md。移機包不附帶私人對話資料庫。ZIP 預設不含個人測試圖片與 `artifacts/`，請依需要自行複製。

建議解壓至自己可寫入的本機路徑，例如 `C:\AI-Lab\labchat`。勿直接從 ZIP 內執行，也勿放在 Program Files。專案會寫入 `.logs/`。

## 2. 安裝必要軟體

1. 安裝仍受安全更新支援的 Windows 11 x64，並更新顯示卡驅動。Ollama 官方列出的最低系統為 Windows 10 22H2；本指南建議 Windows 11。
2. 從 [Python 官方網站](https://www.python.org/downloads/windows/) 安裝 **64 位元 CPython 3.11 或 3.12**。確認 `py -3.11 --version` 或 `py -3.12 --version` 可執行。以下命令以 3.11 為例；若裝 3.12，僅將建立環境的 `-3.11` 改為 `-3.12`。不用安裝 Anaconda。
3. 從 [Ollama Windows 官方下載頁](https://ollama.com/download/windows) 安裝 Ollama，完成後重新開啟 PowerShell，執行 `ollama --version`。原生安裝不需要 Docker 或 WSL。
4. Codex 是開發工具；啟動此應用程式不需要 Codex 或 OpenAI API 金鑰。另一台 Codex 的安裝、登入及權限由該電腦處理。

Qt 已包含在 PySide6 wheel，不必另外安裝 Qt SDK。先以 2B 模型驗收；Windows 的 RAM、GPU／VRAM 與 M2 統一記憶體不能直接等量比較。8GB 電腦需特別觀察記憶體，效能不足再評估 0.8B；勿直接預設 4B 能順暢執行。請預留 Ollama 本體、Qt 套件、模型與快取的磁碟空間。

## 3. 建立 Windows 虛擬環境

在專案目錄開啟 **PowerShell**，逐行執行，任何一行失敗先停止處理錯誤：

```powershell
Set-Location 'C:\AI-Lab\labchat'
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "from PySide6 import QtCore, QtWidgets, QtNetwork; print(QtCore.__version__)"
```

如已有從 Mac 搬來的 `.venv`，先將它移出專案或改名備份，再建立新的 `.venv`。不要在舊環境上覆蓋安裝。不需啟用 Activate.ps1，因此不用調整 PowerShell 執行原則。pip 若表示找不到版本，先確認 x64、Python 版本、網路／套件索引及 requirements 是否完整；不要自行取消鎖版。

## 4. 設定 Ollama 為本機服務

先從系統匣完整退出正在執行的 Ollama，再於 Windows「編輯您帳戶的環境變數」加入：

| 變數 | 值 | 用途 |
| --- | --- | --- |
| `OLLAMA_HOST` | `127.0.0.1:11434` | 僅監聽本機 |
| `OLLAMA_NO_CLOUD` | `1` | 停用 Ollama 雲端功能 |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | 限制同時載入模型數 |
| `OLLAMA_NUM_PARALLEL` | `1` | 限制推論並行 |

儲存後重新啟動 Ollama 與 PowerShell。不要設定 `0.0.0.0` 或開放路由器／防火牆埠。環境變數不會回溯套用到已啟動的服務。

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 5
ollama pull qwen3.5:2b
ollama list
Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5
```

模型下載需要網路。模型標籤可能更新，跨平台下載結果未必與 Mac 的模型雜湊相同；記錄 `ollama --version`、`ollama list`、`ollama show qwen3.5:2b`，並重新驗收。原 Mac 已下載 Qwen3.5 2B、Ministral 3 3B 與 Gemma 3 4B；新 Windows 不會繼承模型。選單列出 4B／0.8B 不表示已下載。

選用模型，確有需求時再下載：

```powershell
ollama pull qwen3.5:0.8b
ollama pull qwen3.5:4b
ollama pull ministral-3:3b
ollama pull gemma3:4b
```

若服務未啟動，可在另一個 PowerShell 視窗執行 `ollama serve` 並保持開啟；系統匣服務已在運作時不要重複啟動。新服務必須繼承上述設定。

## 5. 啟動

雙擊 `run_windows.cmd`，或在 PowerShell 執行：

```powershell
.\.venv\Scripts\python.exe main.py
```

Windows 啟動檔會檢查環境與 Qt，然後開啟介面；**不會安裝套件、下載模型或自動啟動 Ollama**。請先完成上一節。Mac 的 `run.command` 不能用在 Windows。

## 6. 必做驗收

- 首頁 Logo、中文、下拉選單、標註視窗及 100%／125%／150% 顯示縮放無裁切。
- 按「檢查服務」，服務與 2B 模型顯示就緒；文字提問可回覆，處理中顯示動畫，停止後保留草稿。
- 附加已知內容圖片，驗證顏色、可見物件與數量；重新問圖前要重新附加圖片。
- 開啟框選視窗，人工新增、改名、刪除，測試 AI 建議框及停止，匯出 PNG／JSON 後實際開檔檢視。匯出使用縮圖座標與尺寸，最長邊最多 1024，不是原始高解析度。
- AI 框會漏框、重複與偏移；計數與類別也可能錯誤，必須人工核對。沒有偵測準確率或信心分數保證。
- Windows 目前找不到 `/usr/bin/say` 是已知限制；不啟用自動朗讀，文字／圖片流程應仍能使用。需要 Windows TTS 時依 `CODEX_HANDOFF.md` 實作並驗收。
- 測試關閉視窗、生成途中取消、Ollama 未啟動、模型未下載、無效／過大圖片等情況。

開發檢查（同樣逐行確認成功）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff check main.py labchat tests scripts
.\.venv\Scripts\python.exe -m ruff format --check main.py labchat tests scripts
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe -X faulthandler -m unittest discover -s tests -v
Remove-Item Env:QT_QPA_PLATFORM
.\.venv\Scripts\python.exe -m pip check
```

`offscreen` 只供測試，日常啟動前須移除，否則視窗不會出現。測試會建立本機 HTTP 模擬伺服器，需允許本機 loopback。通過單元測試後仍須進行真實 GUI／模型驗收。選用 `scripts/smoke_local.py` 會呼叫已安裝的真實模型，耗用記憶體與時間。

## 7. 常見問題與診斷

| 問題 | 處理 |
| --- | --- |
| 找不到 py／ollama | 重開終端機，檢查官方安裝與 PATH；勿下載來路不明的修復檔 |
| 找不到 `.venv\Scripts\python.exe` | 重新建立 Windows 環境；Mac 的 `.venv/bin` 不可用 |
| 連線失敗 | 確認 Ollama 正在運作、11434 只綁定 loopback，及服務實際繼承的環境變數 |
| 模型未安裝 | `ollama list` 後下載完全相同標籤，再按檢查服務 |
| 回覆慢或記憶體不足 | 關閉其他重型程式，以 `ollama ps` 查看載入情況，先縮短內容與圖片；依硬體評估小模型 |
| 字體／版面不同 | 檢查 Windows 中文字型與 DPI；由 Codex 修正平台字型 fallback，勿只靠縮小全域字級 |
| 無聲音 | 目前只有 macOS TTS，安裝 Windows 聲音不會自動讓現有後端可用 |
| Qt DLL 無法載入 | 核對 Python 位元架構與 wheel；必要時依官方錯誤指示安裝 Microsoft 官方 VC++ x64 runtime，勿到第三方網站下載單顆 DLL |

應用程式日誌在 `.logs/application.log`；Ollama 日誌通常在 `%LOCALAPPDATA%\Ollama`。分享前檢視是否包含私人路徑或資訊。套件與模型安裝會聯網，程式的本機推論路徑不等於整台電腦或 Codex 都離線。

## 官方參考

- [Ollama Windows 安裝與系統需求](https://docs.ollama.com/windows)
- [Ollama 環境變數、雲端停用與 GPU 使用檢查](https://docs.ollama.com/faq)
- [Qt for Python：虛擬環境與 wheel 安裝](https://doc.qt.io/qtforpython-6/gettingstarted.html)
- [Python Windows 下載](https://www.python.org/downloads/windows/)

本文件依官方資料與原始碼核對；實際 Windows 相容性須由目標電腦的驗收結果確認。

## 移機包完整性

下載後先依 START_HERE.md 比對 ZIP 的 `.sha256`，再在新的空目錄解壓並執行 `scripts/verify_handoff.py`。Codex 所需交接文件已隨包收錄；HANDOFF_MANIFEST.json 提供來源檔案清單與逐檔雜湊。上傳前複查範圍見 PACKAGE_REVIEW.md。
