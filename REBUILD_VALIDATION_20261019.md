# 2026-10-19 新電腦復刻流程驗證

目標：讓新使用者只需取得可信原始碼及教學，從官方來源取得外部依賴，在本機建立自己的環境，並有明確的完成／失敗檢查。這不是把原機 venv、私人資料或數十 GB 模型放到 GitHub。

## 本輪增加的重建材料

- `Brewfile`：Python 3.11、Ollama、whisper.cpp 系統工具清單；使用者依 Homebrew 支援與確認流程安裝。
- `environment.lock.json`：本機驗證的引擎版本、九模型 digest／大小、Whisper URL／大小／SHA256 與 basic／full 方案。
- `requirements-macos-hashed.lock.txt`：六個固定版本 macOS wheel 的官方 PyPI SHA256；安裝器強制 `--require-hashes --only-binary=:all:`。
- `restore.command`／`scripts/restore_environment.py`：引導選方案及確認下載、呼叫 venv 安裝、連接或啟動 loopback 服務、下載並核對模型與 Whisper、執行最終環境檢查。
- [完整復刻教學](docs/REBUILD_MAC.md)：系統工具、兩種方案、例外處理、日常啟動及實際操作驗收。

## 可重現的範圍

Python 套件版本與 macOS wheel 檔案雜湊固定；模型內容 digest 與 Whisper 權重 SHA256 固定。既有模型若不符，停止而不覆蓋；新的 Whisper 使用獨立暫存檔，校驗通過後才建立正式檔案，拒絕降至 HTTP 下載。

Homebrew 取得的系統工具可能較基準新，腳本不自動降版；Python 使用 3.11 分支，不強制所有電腦的修訂版完全相同。macOS、硬體、聲音與麥克風權限並非複製原機。本輪仍以 Apple Silicon M4、macOS 26.4、16GB 實測，不能推論所有系統都 100% 成功。

## 已完成的驗證

- 從官方 PyPI 取得六個 macOS wheel 的 SHA256，與版本清單一致；在沒有舊套件的乾淨環境強制雜湊安裝成功。
- 原有及新增回歸 **234 項通過**。涵蓋模型 digest 變更不得默默接受、只讀模式不可安裝或啟動服務、未確認不得下載、損毀 Whisper 保留原檔、錯誤下載不可啟用、失敗暫存清理與拒絕 HTTPS 降級。
- 本機九款模型與原 Whisper 的 `full --verify-only` 基準檢查通過；只查詢，不重新下載或啟動既有服務。
- 在另一份乾淨來源實際執行 `full --yes`：雜湊套件安裝、九模型 digest、重新下載 Whisper 與容量／SHA256 校驗、最後環境檢查均通過；之後文字／圖片可見回答與合成語音辨識通過，沒有錄音或播放喇叭。
- 封裝規則已包含 Brewfile、重建基準、hashed requirements、復刻入口及圖文教學；原交接 ZIP 未被覆蓋。

本輪完整方案的乾淨執行結果與驗證證據見本機 `.logs/rebuild-*.log`。模型下載使用本機既有 Ollama 服務；匹配基準的模型略過下載，不能因此稱為在另一台沒有模型的電腦重新下載了全部九款。

## 同日再次檢查（上傳前）

- 再跑全部回歸：234 項通過（14.477 秒）；Ruff 檢查、格式檢查及三個 `.command` 的 zsh 語法檢查通過。第一次受沙箱限制的測試無法建立 loopback 測試伺服器，解除該執行限制後完整重跑通過，未以跳過測試代替。
- 再實際執行 `restore.command --profile full --yes`：套件、九款既有模型 digest、Whisper SHA256 與環境檢查通過；Qwen3.5 2B 文字／圖片顯示及正常退出通過（4.5 秒），合成中文音訊辨識成功（0.58 秒），暫存錄音清理完成。本輪沒有重新下載既有權重。
- 修正語音驗收腳本寫死 `/opt/homebrew/bin/whisper-cli` 的問題，改為透過 PATH 尋找安裝位置；補上 ZIP 解壓後啟動檔缺執行權限的處理教學。這不代表已驗證 Intel Mac。
- 檢查當時 114 個上傳候選檔案及 80 個本機文件連結：沒有缺檔連結、符號連結、大型檔案或常見憑證格式；環境、日誌、權重、私人資料、音訊與資料庫範例均被忽略。格式掃描不能取代人工內容審查，也不保證辨識任意形式的秘密。
- 證據保存在本機 `.logs/final-recheck-*.log` 及 `.logs/final-recheck-publication.json`；未加入暫存區、未提交、未上傳。

## GitHub 下載副本依教學實際安裝

首次發布後，使用從 GitHub clone 的 `a2071ee` 副本再次驗證；開始時該副本沒有 `.venv` 或 Whisper 模型。

- 依教學執行 `restore.command --profile full --yes`，新建 venv、安裝六個固定版本 wheel 並校驗 SHA256、`pip check` 與 Qt 匯入全部通過。套件使用官方來源先前留下的 pip 快取，不是本輪重新傳輸全部 wheel。
- 從官方來源重新下載 487601967 bytes Whisper small，容量與 SHA256 通過；九款聊天模型仍沿用本機 Ollama 既有權重並核對 digest，沒有重下載九款。
- 副本內的圖文聊天正常（3.6 秒，正確回答左藍右紅）、合成中文語音辨識正常（0.74 秒）、暫存清理成功，精靈以狀態碼 0 完成。
- 額外執行副本的 `run.command --check` 與 `restore.command --profile full --verify-only`，兩者通過。
- 系統工具為原機既有安裝，沒有重新安裝 Homebrew 或三項系統工具。`brew bundle check` 提示需安裝或更新，不能記為通過；另以 `brew list --versions` 與命令列直接確認三工具均已安裝且可用，未為測試強制升級。
- `whisper-cli --version` 證實引擎為 1.9.1，修正先前文件與基準的 1.9.5 誤記；相關 12 項重建回歸再次通過。證據見本機 `.logs/github-fresh-install.log`、`.logs/github-run-check.log`、`.logs/github-verify-only.log`。

這證明下載來源可在本機現有系統工具下重建應用環境並運行；仍不是另一台全新 Mac 的全流程驗收，也沒有實測麥克風收音。

## 仍需使用者操作

新機先安裝受支援的系統工具，下載套件／模型需要網路與磁碟。完整方案的麥克風授權、實際收音及音色聽感仍需使用者確認，不會在背景錄音或代為變更系統安全性。

上游若移除舊 wheel 或改變同名模型內容，校驗流程會停止；由維護者重新驗證並更新基準，而不是讓使用者自行取消校驗。若要完全離線、逐位元相同的長期保存，需另外準備符合授權的外部工具與權重離線備份，本來源包沒有包含這些大型依賴。
