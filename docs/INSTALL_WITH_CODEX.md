# 使用 Codex 協助安裝與驗收

[回首頁](../README.md) · [手動分步安裝](INSTALL_MAC.md) · [完整復刻](REBUILD_MAC.md)

Codex 可協助讀取專案、執行本機安裝指令並查錯；本專案仍使用 Python、Qt 與本機 Ollama，不以 Codex 作為聊天或框選引擎。Codex 是選用的安裝助手，平常使用本程式不必保持它開啟。

## 1. 準備 Codex 與本機專案

依 [OpenAI 官方快速入門](https://learn.chatgpt.com/docs/quickstart) 與 [桌面程式說明](https://learn.chatgpt.com/docs/app) 安裝及登入。官方頁面目前將桌面體驗列為 ChatGPT desktop app，介面名稱可能因版本不同；在可用的 Codex 編碼工作流程中開啟本機資料夾。帳號可用功能以官方說明與您的帳號為準。

先從 GitHub **Code → Download ZIP** 解壓，或執行：

```sh
git clone https://github.com/orinaisl33-max/ollama-VLM.git
cd ollama-VLM
```

在桌面程式選擇解壓／clone 後的專案根目錄，確認其中有 `main.py`、`Brewfile`、`restore.command`。使用能存取這台 Mac 檔案與終端機的本機工作流程；只有貼 GitHub 網址、沒有本機執行權限的對話，不能替這台 Mac 建立環境。雲端執行結果也不能算作本機麥克風與 Metal 驗收。

## 2. 貼上這段安裝要求

以下預設只裝一個圖文模型。整段貼到已開啟本專案的 Codex：

```text
請協助在目前這台 Mac 安裝並驗收這個 ollama-VLM 專案。
先讀 README.md、docs/INSTALL_MAC.md、docs/REBUILD_MAC.md 和 environment.lock.json。

我授權您在本專案建立 .venv、從官方來源安裝鎖定套件，
並下載基本方案 qwen3.5:2b 模型；請先回報磁碟與環境檢查結果，再繼續已授權工作。

請依序進行：
1. 確認專案根目錄、macOS、晶片、Python 3.11、Ollama、網路與可用磁碟。
2. 若缺少系統工具，依安裝指南處理；需要管理者密碼、系統操作或額外權限時，
   清楚說明並由我操作。不要自行關閉 Gatekeeper 或其他安全機制。
3. 系統工具可用後，依指南執行 restore.command 的 basic 方案。
   自動化可用 ./restore.command --profile basic --yes；不要額外下載完整九模型。
4. 強制保留 SHA256／模型 digest 校驗。既有 .venv 或模型不符時保留並報告，
   不刪除私人資料、不強制降版、不用 sudo pip，不取消校驗來掩蓋錯誤。
5. 執行 .venv/bin/python scripts/check_install.py --require-model，
   確認自動文字／圖片測試通過，再協助我用 run.command 開啟。
6. 告訴我如何使用「測試圖」資料夾驗收圖片與框選：
   指定人物或其他明確目標，確認逐框預覽、人工調整與匯出；未實測就列為待測。
7. 最後列出實際安裝版本、已下載與沿用的項目、通過與未通過的檢查、
   尚待人工驗收項目及日常啟動方法。不能只憑檔案存在就宣稱運行成功。

這次只做本機安裝與必要修復，不提交或上傳 GitHub。
若修復會改動依賴基準或模型內容，先說明具體差異供我確認。
```

Codex 的網路、檔案與執行權限由您的環境管理；遇到權限要求請核對實際動作。安裝授權不會取代 macOS 的密碼或麥克風權限操作。

## 3. 想安裝完整模型與語音

基本方案成功後，再貼上：

```text
我現在授權安裝 docs/REBUILD_MAC.md 的 full 方案：九款模型及 Whisper small。
先確認至少 30GB 可用磁碟、Python 3.11、Ollama、whisper-cli 與中文系統聲音，
再執行 ./restore.command --profile full --yes。
核對全部 digest／SHA256，執行圖文與合成語音驗收；既有符合基準的模型可略過下載。
不要背景錄音，真實麥克風權限與收音請由我操作；未測試項目請明確列出。
不要上傳私人資料，也不要提交或推送 GitHub。
```

## 4. 如何判斷真的完成

應有建立在本專案的 `.venv`、套件校驗與 `pip check` 成功、至少一款模型可用、實際文字／圖片回答與正常退出的證據。最後再由使用者確認 `run.command` 開啟的視窗、框選與匯出；完整方案另確認合成語音及真實麥克風。

若安裝失敗，可貼上：

```text
請根據實際錯誤找出安裝卡在哪一步，保留現有檔案與私人資料。
先提供最小修復並重新跑失敗的檢查；不要反覆重裝所有套件、取消鎖版或刪除模型。
請區分工具權限、網路／上游供應、版本不符與程式錯誤，並列出尚未完成的驗收。
```

此方法提供可執行的安裝任務與驗收標準，不保證所有硬體、網路或上游版本都成功。Codex 工作可能使用其帳號所選服務；不要把不適合分享的圖片、金鑰或個資貼入對話，這與本程式的本機 Ollama 推論不同。
