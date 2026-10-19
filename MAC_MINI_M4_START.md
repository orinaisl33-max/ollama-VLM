# Mac mini M4 移機教學：給使用者與接手 Codex

> **GitHub 新使用者請先閱讀 [目前 Mac 安裝圖解](docs/INSTALL_MAC.md)。本文件保留較早的來源包／移機流程；舊 ZIP 與 HANDOFF_MANIFEST 的校驗不是目前 GitHub 安裝步驟。首次安裝用 install.command，日常啟動用 run.command。**

> 2026-10-19 本機來源已有輕量模型擴充，請先讀 [MODEL_EXPANSION_20261019.md](MODEL_EXPANSION_20261019.md)。下方 2026-10-16 ZIP 與安裝驗收屬歷史交接基線，現行來源修改沒有重新打包進該 ZIP。

版本：2026-10-16 最新來源交接包。適用 Apple Silicon Mac mini M4，使用原生 arm64 環境。本文件是本次 Mac 安裝的優先入口；其他文件中的「尚未打包」與舊測試數字屬歷史紀錄。

## 你需要帶走什麼

一起搬移以下兩個檔案，並保留本教學：

- `labchat-mac-handoff.zip`：最新程式、Logo、測試、鎖定套件清單及交接文件。
- `labchat-mac-handoff.zip.sha256`：ZIP 校驗碼。

這是可重建環境的**原始碼包**，不是雙擊即用的獨立 App，也不是完整離線安裝包。首次需網路下載 Python／Qt 套件、Ollama 模型、Whisper 引擎與模型，以及可能缺少的中文聲音。建置完成後，本程式的模型推論、語音辨識與朗讀可在本機執行；這不表示接手用的 Codex 也能離線運作。

不搬移舊 `.venv`、`.runtime`、模型、私人對話資料庫、圖片、錄音與日誌。**必要的安裝步驟有提供，但大型外部依賴沒有塞入 ZIP。** 原機對話記錄不會自動出現在新機；需要時另依下方資料搬移說明處理。

## 最簡單的使用流程

1. 將 ZIP、校驗碼與教學放到新 Mac，例如「下載項目」。
2. 在終端機進入兩個檔案所在資料夾，先驗證 ZIP：

   ```sh
   cd ~/Downloads
   shasum -a 256 -c labchat-mac-handoff.zip.sha256
   ```

   必須顯示 `OK`；不符合就停止並重新取得檔案。也應比對原機提供的校驗碼。雜湊驗證完整性，不是數位簽章。
3. 用 Finder 解壓到新的空資料夾。ZIP 內的專案根目錄叫 `labchat`，其中應看得到 `main.py`、`run.command` 與本文件。
4. 在新 Mac 的 Codex 開啟／選擇**解壓後的專案資料夾**，將下方完整文字貼入對話。若 Codex 尚未安裝或登入，先完成它自己的安裝與登入。
5. 讓 Codex 按階段完成安裝與驗收；macOS 管理者密碼、麥克風權限與音色試聽由你在新機操作。不要把密碼貼進對話。

## 直接複製貼給新電腦 Codex 的指令

```text
請在目前開啟的 labchat 專案中完成 Mac mini M4 環境重建與驗收。

先讀 MAC_MINI_M4_START.md、MAC_CODEX_HANDOFF.md、README.md、FEATURES.md、VOICE_INPUT.md、SECURITY_REVIEW.md 頂部最新複查、QUALITY.md 及本機適用的 AGENTS.md。Mac 指示優先於 Windows 範例；舊日期的「尚未打包」是歷史紀錄。

這是從 MacBook Air M2 8GB 移來的 Python/PySide6/Ollama 本機 AI 展示工具。請確認 macOS >=14、原生 arm64、RAM、可用磁碟、Python、Homebrew、Ollama 和 whisper-cli，記錄實際版本。先驗證外部 ZIP 校驗碼（若可取得），再使用標準 Python 執行 scripts/verify_handoff.py 驗證逐檔 manifest；驗證前不要修改來源。

請依教學逐步安裝或重用已存在且相容的工具，建立全新的 .venv，安裝 requirements.lock.txt 與 requirements-dev.txt。若 .venv 已存在，先檢查，不要刪除或覆蓋；需要重建時保留備份。使用 Python 3.11 原生 arm64，勿修改系統 Python、勿使用 Rosetta 或 sudo pip，不要靜默取消鎖定版本。

請檢查 Ollama，保持 127.0.0.1:11434 本機連線、OLLAMA_NO_CLOUD=1、單模型與單並行。既有服務不要直接殺掉；如需更改請先說明並由我正常退出。以 qwen3.5:2b 起步，為重建原機三個已安裝選項，再下載 ministral-3:3b、gemma3:4b；逐個下載與驗證。先確認磁碟空間，記錄模型大小/ID/能力。qwen3.5:4b、qwen3.5:0.8b 目前不是必要下載。不要因模型不可用而暗中改成雲端推論或替換模型。

請依 VOICE_INPUT.md 安裝 whisper.cpp 與 small 多語言 ggml-small.bin，必須驗證教學中的 SHA256 才能啟用；檢查 whisper-cli 可用。檢查 /usr/bin/say 中文聲音，缺少時指引我從 macOS 系統設定下載。使用 run.command 重建 .runtime/LabChat.app 與本機簽章；不要帶入原機 .runtime，不要關閉 Gatekeeper 或替我變更隱私權設定。

先跑完整測試、Ruff、pip check、compileall 及 zsh 語法檢查，使用暫存資料庫與本機假服務。再做真實模型文字/圖片/取消、手動畫框與 AI 建議框、PNG/JSON/Labelme 匯出、歷史/草稿/時間標記、深淺色與螢幕排版驗收。語音輸入、權限及 TTS 實際聽感由我操作；不要在未告知情況下錄音或播放。檢查錄音不再出現 _audio_state(QAudio::State) TypeError，定位與回答計時可停止，相容重試不中斷計時。

保留繁體中文、MIRDC Logo、精簡輸入區與設定入口、非同步串流、安全 Markdown 與原有功能；不要自行增加新功能或升級整套套件。不外傳私人對話、圖片或錄音。遇到安裝失敗、校驗不符、模型/鎖版不相容就先停止該步並說明，不能跳過後宣稱完成。

最後參考 M4_VALIDATION_TEMPLATE.md 產生 M4_VALIDATION.md，記錄新機硬體、版本、命令、測試數量、模型及功能的通過/失敗/未測。原機最後175項測試通過不是新機通過證據。安裝依目前授權協助，系統必要確認由我處理；先不要重新打包或上傳。
```

## 手動指令參考：Codex 也應逐步核對

下方命令在**解壓後的 labchat 根目錄**執行；若目錄不同，先 `cd` 到實際路徑。每個步驟失敗時停止，不要整頁一次貼入。

### 1. 確認架構與工具

```sh
pwd
sw_vers -productVersion
uname -m
sysctl -n hw.memsize
df -h .
command -v brew
command -v python3.11
command -v ollama
command -v whisper-cli
```

M4 的 `uname -m` 與 Python 架構應為 `arm64`。本專案鎖版要求 macOS 14 以上。缺少工具時 `command -v` 沒有輸出是待安裝，不是全部步驟失敗。

若沒有 Homebrew，從 [Homebrew 官方網站](https://brew.sh/) 依指示安裝，依安裝器顯示的步驟設定 PATH；它可能需要 Apple Command Line Tools。這不是要求安裝完整 Xcode。M 系列一般使用 `/opt/homebrew`，不要混用 Intel 的 Homebrew。

已有 Homebrew 後：

```sh
brew install python@3.11 whisper.cpp
python3.11 --version
python3.11 -c 'import platform; print(platform.machine())'
whisper-cli --help
```

安裝器取得的 Python 3.11 修補版可能比原機3.11.15新，請記錄實際版本，無需強行找舊版。Homebrew 在查核時使用公式名稱 `whisper.cpp`，舊名為 `whisper-cpp`。

### 2. 校驗來源，建立全新虛擬環境

```sh
python3.11 scripts/verify_handoff.py
```

必須顯示 `Verified ... source files`。若 `.venv` 已存在，先由 Codex 檢查與保留備份；以下只適用尚無 `.venv` 的新目錄：

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock.txt
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip check
.venv/bin/python -c 'import platform; from PySide6 import QtCore, QtWidgets, QtMultimedia, QtNetwork; print(platform.machine(), QtCore.__version__)'
```

`requirements-dev.txt` 會引用同一 runtime 鎖版並安裝 Ruff。執行時不需要啟用 venv，以上用完整 `.venv/bin/python` 路徑避免混用。不要把套件裝進系統 Python。

### 3. 安裝、啟動 Ollama

從 [Ollama 官方 macOS 下載](https://ollama.com/download/mac) 安裝到 Applications 並依首次啟動提示提供 CLI。若已安裝，先檢查版本，不需重複安裝。若 Ollama App 已在執行，請使用者從選單列正常退出，再執行：

```sh
launchctl setenv OLLAMA_HOST '127.0.0.1:11434'
launchctl setenv OLLAMA_NO_CLOUD '1'
launchctl setenv OLLAMA_MAX_LOADED_MODELS '1'
launchctl setenv OLLAMA_NUM_PARALLEL '1'
open -a Ollama
```

等 App 就緒，再確認：

```sh
ollama --version
curl --noproxy '*' -fsS --max-time 5 http://127.0.0.1:11434/api/version
```

這些 `launchctl` 設定不是跨重新開機的永久設定。`run.command` 在服務未啟動時可用同樣環境啟動 `ollama serve`；對已啟動服務不會重新配置。不要同時啟動第二個服務，不要開放 `0.0.0.0`。程式預設API走本機，不使用雲端模型。

### 4. 分別下載原機的三個模型

以下只在缺少時執行；下載需網路與足夠磁碟。先以預設2B完成基本驗收，再補另外兩個；下載完成不代表同時載入。

```sh
OLLAMA_HOST=127.0.0.1:11434 ollama pull qwen3.5:2b
OLLAMA_HOST=127.0.0.1:11434 ollama pull ministral-3:3b
OLLAMA_HOST=127.0.0.1:11434 ollama pull gemma3:4b
OLLAMA_HOST=127.0.0.1:11434 ollama list
OLLAMA_HOST=127.0.0.1:11434 ollama show qwen3.5:2b
OLLAMA_HOST=127.0.0.1:11434 ollama show ministral-3:3b
OLLAMA_HOST=127.0.0.1:11434 ollama show gemma3:4b
```

模型標籤不是不可變版本。請記錄新下載的 ID／大小／能力；同名模型日後可能不同，無法保證與原機位元組完全一致。其他選項 `qwen3.5:4b`、`qwen3.5:0.8b` 是選用，不需為了跑程式全部下載。記憶體容量未確認前不增加模型大小／並行。

### 5. 下載並校驗中文語音輸入模型

在專案根目錄執行；若 `models/ggml-small.bin` 已存在，先驗證其雜湊，不要覆寫：

```sh
mkdir -p models
curl -fL --retry 2 -o models/ggml-small.bin.part 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin'
.venv/bin/python - <<'PY'
import hashlib
from pathlib import Path
source = Path('models/ggml-small.bin.part')
target = Path('models/ggml-small.bin')
expected = '1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b'
with source.open('rb') as stream:
    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
if actual != expected:
    raise SystemExit('模型校驗失敗：保留 .part 供檢查，不啟用模型。')
if target.exists():
    raise SystemExit('目標模型已存在，未覆寫；請先核對既有模型。')
source.rename(target)
print('Whisper small 模型校驗通過，已啟用。')
PY
```

模型約488 MB，使用多語言 `small`，不是 `.en` 英文限定版。若模型已存在，可使用 `shasum -a 256 models/ggml-small.bin` 比對同一校驗值。校驗失敗不得直接改名使用。不要使用 `sudo` 執行模型下載或啟動程式。

### 6. 測試與啟動

```sh
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m compileall -q labchat scripts tests main.py
.venv/bin/python -m pip check
zsh -n run.command
QT_QPA_PLATFORM=offscreen .venv/bin/python -X faulthandler -m unittest discover -s tests -q
chmod u+x run.command
./run.command
```

離屏測試只測本機假服務與暫存資料，不會實際錄音；需允許 loopback 網路，不需模型或網際網路。原機此版175項測試通過，新機必須重新跑。不要全域設定 `QT_QPA_PLATFORM=offscreen`，正常啟動需要顯示視窗。

`run.command` 自動建立本機 `.runtime/LabChat.app`，宣告麥克風用途並做 ad-hoc 簽章。若簽章工具不可用，先查 Apple Command Line Tools；不要關閉 Gatekeeper、全域移除 quarantine 或修改系統 Python。直接 `python main.py` 可能缺少麥克風用途宣告，請用啟動檔。

## 新機驗收清單

- 「設定 → 檢查本機服務」有進度、結果、模型狀態及重試；不只看右上綠燈。
- 文字與圖片問答、AI標題旁轉圈與秒數、停止生成、提問與完成時間標記。
- 左側搜尋／歷史／新對話、使用者藍色區塊、草稿、深淺色、小螢幕或外接螢幕排版。
- 附圖、手動畫框／調整／復原／重做、AI建議框與定位計時、停止定位、PNG／專案JSON／Labelme JSON匯出並重新開檔。AI框須人工校對。
- 「設定 → 語音與朗讀」列出中文音色；實際試聽、停止、關閉／分段／完成後朗讀三模式。
- 「使用麥克風語音輸入」首次權限、30秒倒數、提早停止、取消、辨識文字核對再傳送。正常操作後不應出現 `_audio_state(QAudio::State)` TypeError。
- 生成／錄音／朗讀／定位中關閉程式，無卡住、殘留程序或錯誤寫入歷史。
- 安裝與模型下載完成後斷網，另測本程式的本機文字／圖片／錄音／朗讀；勿把 Codex 是否連線當作本程式是否離線的判斷。

中文聲音使用新 Mac 自己的 `/usr/bin/say`。可用 `/usr/bin/say -v '?'` 列清單；缺中文音色時由使用者在 macOS「系統設定」搜尋語音朗讀相關設定並下載，再回程式重新整理。原機音色不在ZIP，播放品質與新機聲音資源有關。Mac mini 須有可用的麥克風輸入裝置，請先確認 USB／耳麥／其他輸入來源；不假設桌機自帶可用麥克風。

若 Codex 需要繼續開發，完整舊聊天不會跟ZIP自動搬移；接續背景已整理於交接MD。也不會繼承原機的帳號、權限與授權狀態。

## 私人對話與圖片資料

來源包預設不帶私人資料。只想驗證程式，使用新機全新紀錄即可。若需要舊文字對話，先在原機「管理／匯入匯出」匯出對話JSON，再另行安全搬移；文字交換不包含圖片／標註。圖片標註請另匯出專案JSON／PNG或Labelme JSON，並保留對應圖片。

完整資料庫另存系統使用者資料目錄（實際路徑見程式的對話管理），**不在專案ZIP內**。要搬整庫應先完全關閉兩邊程式、另做備份，再由Codex核對版本與檔案，不可覆寫新機既有紀錄。資料未加密，搬移與雲端保存需自行選擇適當方式。

## 常見問題與官方依據

- 未下載模型：到設定的模型下載與說明，或執行對應 `ollama pull`；不要以選單存在當作已下載。
- 套件無相容wheel：先核對 macOS、arm64、Python及套件來源，停止並記錄錯誤，不靜默升級整組Qt。
- 麥克風權限拒絕：到「系統設定 → 隱私權與安全性 → 麥克風」核對實際顯示的程式，再重新啟動。
- TSM／IMK訊息是macOS輸入法訊息，FFmpeg版本行是音訊後端資訊；有實際打字／錄音異常時再記錄排查，不隱藏錯誤。
- 本指南核對日期2026-10-16；安裝來源可能更新。以新機實際測試為準，不承諾M4效能、音色或辨識率與原機相同。

參考：[Python venv](https://docs.python.org/3/library/venv.html)、[Homebrew Python 3.11](https://formulae.brew.sh/formula/python@3.11)、[Homebrew whisper.cpp](https://formulae.brew.sh/formula/whisper.cpp)、[Ollama macOS](https://docs.ollama.com/macos)、[Ollama FAQ](https://docs.ollama.com/faq)、[Whisper small檔案與SHA256](https://huggingface.co/ggerganov/whisper.cpp/blob/main/ggml-small.bin)。
