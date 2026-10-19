# 從一台新 Mac 完整重建

[回首頁](../README.md) · [安裝圖解](INSTALL_MAC.md) · [一般發布前驗證](../RELEASE_AUDIT_20261019.md)

目標是「取得原始碼後，依教學取得外部工具、重建 venv、下載並校驗套件及模型，再確認能執行」。排除大型／私人檔案，不代表缺少重建步驟。

## 先分清楚兩種重建

| 方案 | 內容 | 模型標示下載約量 |
| --- | --- | ---: |
| 基本圖文 `basic` | 鎖定 Python 套件＋Qwen3.5 2B；可文字及圖片聊天 | 2.68GB |
| 完整 `full` | 同一套 Python 套件＋九款模型＋已校驗 Whisper small | 約 20GB，另加約 488MB 語音權重 |

另外預留 Python／Qt、安裝快取與模型執行空間。完整方案建議至少 30GB 可用磁碟；8GB 記憶體不代表適合使用所有模型。模型不會全部同時載入；相同模型已安裝且 digest 符合時略過下載。

「復刻」是依版本與內容基準重建應用程式環境。macOS、硬體、系統聲音與 Homebrew 工具版本不是複製舊機；實測基準記錄在 [environment.lock.json](../environment.lock.json)。目前驗證為 Apple Silicon M4、16GB、Python 3.11、macOS 26.4。其他系統組合需自行驗收。

## 第一步：取得整個專案

從 GitHub **Code → Download ZIP** 解壓，或 `git clone`。不要只下載單一啟動檔。您應看到：

```text
ollama-VLM/
  Brewfile                         系統工具清單
  environment.lock.json            引擎基準、模型 digest、Whisper 校驗碼
  requirements.lock.txt            跨平台套件版本清單
  requirements-macos-hashed.lock.txt  Mac 套件檔案 SHA256
  restore.command                  引導式完整重建
  install.command                  只建立／檢查 Python 環境
  run.command                      日常啟動
  scripts/                         安裝、下載、檢查工具
  docs/                            教學與圖片
```

`.venv/`、`.runtime/`、`models/` 等資料夾會在新電腦重新建立，GitHub 不會提供原機的私人資料或登入憑證。

## 第二步：先安裝系統工具

腳本不會以管理者權限自動下載及執行遠端安裝程式。

### 已使用受支援 Homebrew 的 Mac

先依 [Homebrew 官網](https://brew.sh/) 安裝及設定 PATH，再在專案根目錄執行：

```sh
brew bundle --file Brewfile
```

這會依清單安裝 Python 3.11、Ollama 與 whisper.cpp；Homebrew 可能要求安裝命令列工具、系統確認或密碼，請由電腦擁有者操作。完整方案需要 `whisper-cli`，基本方案只需 Python 與 Ollama。

Brewfile 會安裝當時可用的工具版本，**不是強制降版到舊機版本**。本機已驗證版本為 Ollama 0.32.1、whisper.cpp 1.9.1（以 `whisper-cli --version` 重新核實，修正先前的 1.9.5 誤記）；若新機不同，仍須跑最終驗收，不能直接視為完全相同的引擎行為。

### 不使用 Homebrew

依 [Mac 安裝圖解](INSTALL_MAC.md#1-準備-python-與-ollama) 從官方來源安裝 Python 3.11 與 Ollama。完整方案另依 [VOICE_INPUT.md](../VOICE_INPUT.md) 安裝 whisper.cpp。不要把其他電腦的 `.venv` 複製過來。

確認：

```sh
python3.11 --version
ollama --version
```

完整方案再檢查：

```sh
whisper-cli --help
```

## 第三步：執行復刻精靈

Finder 雙擊 **`restore.command`**。選擇：

- `1`：基本圖文。
- `2`：完整模型與 Whisper。

精靈會顯示下載範圍。確認後輸入 `YES` 才開始安裝與下載。若 macOS 阻擋下載檔案，確認來源後依 [Apple 單一檔案允許流程](https://support.apple.com/zh-tw/102445) 操作，不需關閉整體安全性。

也可以在專案根目錄執行：

```sh
chmod u+x restore.command install.command run.command
./restore.command --profile basic
```

若雙擊沒有執行，或終端機顯示 `permission denied`，先在解壓後的專案根目錄執行上方 `chmod`，再重試。這只為這三個入口加入目前使用者的執行權限，不會移除 macOS 的下載檔案安全檢查。

有意明確同意完整下載、自動化執行時才使用：

```sh
./restore.command --profile full --yes
```

重建過程會：

1. 檢查系統、Python 3.11、Ollama 與來源檔案。
2. 建立專案 `.venv`，或確認既有環境仍屬本專案。
3. 從官方 PyPI 取得鎖定的 macOS wheel，強制檢查 SHA256，拒絕來源碼套件安裝；執行 pip 與 Qt 匯入檢查。
4. 在本機服務不存在時啟動 loopback Ollama；沿用既有服務時不修改它的設定。
5. 下載方案中的模型，核對 `environment.lock.json` 的 digest。
6. 完整方案另下載 Whisper，核對容量與 SHA256，通過後才啟用正式模型檔。
7. 使用專案 Python 執行環境／本機模型檢查，並以暫存對話與合成圖驗證實際聊天、顯示和退出；完整方案另用已安裝的中文系統聲音產生合成 WAV 驗證 Whisper，過程不錄音、不播放喇叭，通過後才顯示完成。

中斷、磁碟不足、校驗不符或上游模型版本改變都可能使流程停止；不會暗中改用別的模型或雲端推論。請保留錯誤，再依下方處理。

## 第四步：開啟與功能驗收

雙擊 **`run.command`**，選擇已安裝模型並逐項確認：

- 文字：問一個簡單問題，確認實際畫面出現完整回答。
- 圖片：選圖文模型，附加不含個資的圖片，核對辨識是否合理。
- 停止與紀錄：中止長回答、再次發問、保存並開啟歷史對話。
- 完整方案：選中文聲音試聽；接上麥克風、由使用者允許權限，短錄音後確認辨識文字。

只檢查已重建的內容、不下載也不啟動服務：

```sh
./restore.command --profile full --verify-only
```

基本方案把 `full` 改為 `basic`。本機服務尚未啟動時，請先用 `run.command` 開啟，再執行檢查。

進一步測試可執行 `.venv/bin/python scripts/smoke_local.py`；它使用暫存資料庫與合成圖，不會讀取您的私人對話。完整錄音仍不能用合成音訊測試取代。

## 失敗時怎麼做

| 情況 | 處理 |
| --- | --- |
| 找不到 Python／Ollama／whisper-cli | 先完成系統工具安裝、重開終端機並確認 PATH，再執行精靈 |
| `.venv` 不完整或來自其他電腦 | 先備份該資料夾；確認沒有個人檔案後移出原位置，再重建；腳本不自行刪除 |
| 套件 SHA256 不符 | 停止，不要移除雜湊參數強行安裝；重新取得可信來源或請維護者檢查 |
| Ollama 模型 digest 不符 | 可能是同名標籤已更新；維護者需重新實測並更新基準。不要自行改成其他模型或宣稱已精確復刻 |
| Whisper 舊檔校驗失敗 | 原檔保留；備份檢查後再重試，下載中暫存檔不當成有效模型使用 |
| 沒有中文聲音或麥克風 | 完整方案的合成驗收需要至少一款已安裝中文系統聲音，缺少時會停止並指引安裝；麥克風是系統硬體／權限步驟，依語音指南由使用者完成；文字與圖片不依賴麥克風 |
| 網路、代理或磁碟不足 | 修正後重跑；已校驗通過的模型可略過。檔案有校驗不代表供應網站未來一定永遠可下載 |

## 安全與重現性的界線

套件版本及 macOS wheel SHA256 固定，模型 digest 及 Whisper SHA256 固定；完整基準隨原始碼提交。固定校驗碼不是程式碼簽章，取得原始碼本身仍須確認可信來源。

外部工具、系統聲音、作業系統及官方模型供應可能更新。若要求逐位元相同且完全離線重建，還需要另行保存對應工具／wheel／模型的合法離線副本；本 GitHub 原始碼包沒有包含那些大型外部依賴。
