# 程式導覽與後續修改基準

> **2026-10-19 游標防護與診斷：215 項回歸通過；原警告尚未重現，改善與限制見 [CURSOR_DIAGNOSTICS_20261019.md](CURSOR_DIAGNOSTICS_20261019.md)。**

> **2026-10-19 最新模型擴充：九個介面選項均已安裝，212 項回歸通過；模型能力與品質限制見 [MODEL_EXPANSION_20261019.md](MODEL_EXPANSION_20261019.md)。**

> **最新操作改善：搜尋合併、歷史批次排版、直接複製回答與快捷鍵已完成，詳見 [SMOOTHNESS_UPDATE.md](SMOOTHNESS_UPDATE.md)。**

> **更新：第一批修正已完成，見 FIRST_BATCH_UPDATE.md。新增 preferences.py 與 test_first_batch.py；下方草稿與模型切換問題已修正，現在共 51 個 Python 檔、192 項測試。**

整理日期：2026-10-16（Asia/Taipei）。依本機實際原始碼逐模組核對，供後續共同修改使用。環境結果見 `M4_VALIDATION.md`，逐檔 SHA256、匯入與測試索引見 `.logs/m4-code-inventory.json`。

## 查核範圍

第一方 Python 程式共 49 個檔案、9,142 行：入口 1、`labchat` 25、`scripts` 8、`tests` 15。測試定義共 175 項。這裡的理解範圍是專案原始碼，不包含 Python、Qt、Ollama、Whisper 等第三方依賴的全部內部實作。

全部 `labchat` 模組在本機 `.venv` 可成功匯入；原始交接 manifest 的 75 個來源檔案符合，沒有修改既有功能程式。新建文件與測試紀錄不屬於原 manifest。

## 主流程

1. Finder／終端啟動 `run.command`：檢查 `.venv` 與 Qt；Ollama 未啟動時，以僅本機、停用雲端、單模型／單並行環境啟動服務。
2. `scripts/mac_python.py`：依本機 Python 建立 `.runtime/LabChat.app`，寫入麥克風用途宣告並簽章；啟動時指定本專案套件路徑。
3. `main.py`：建立輪替日誌、QApplication、圖片配置限制與主視窗，結束前呼叫 shutdown。
4. `Window.submit()`：檢查操作狀態、模型與文字長度，保存草稿，建立 pending 問題，組裝受限上下文並開始非同步請求。
5. `ChatClient` → Ollama `/api/chat` → `StreamDecoder`：串流驗證後發出 chunk；主視窗以 40ms timer 合併更新，朗讀管線可同步接收完整句子。
6. `_on_completed()`：成功才加入模型上下文與 SQLite；完成後將純文字轉為安全 Markdown。取消／失敗／逾時保留輸入與附件，不保存未完成問答。
7. `shutdown()`：停止顯示／草稿／狀態 timer、標註請求、下載、錄音、朗讀、服務探測、聊天請求，最後關閉 SQLite。

## 各模組責任

| 模組 | 職責與修改連動 |
| --- | --- |
| `labchat/__init__.py` | 套件識別，沒有啟動副作用 |
| `window.py` | 主畫面、輸入、模型切換、上下文、草稿與對話切換、附圖狀態、Markdown 插入及操作互斥；修改需同時檢查儲存、語音與關閉流程 |
| `config.py` | 五個模型、提示詞、容量與逾時；build_messages／retain_turn 保持完整問答組，附新圖時不送舊視覺結論 |
| `client.py` | ChatResult、單一非同步聊天請求、取消／逾時／唯一終態；ServiceProbe 只讀取 `/api/tags` |
| `protocol.py` | 有界 NDJSON 解析，處理跨封包 UTF-8、結尾無換行、錯誤欄位、Unicode 與容量 |
| `security.py` | loopback HTTP 位址、Unicode 與顯示名稱清理；不把模型文字變成可執行指令 |
| `conversations.py` | SQLite schema 5、交易、容量、問答／草稿／偏好／釘選／選用圖片與標註；保存失敗須維持可復原 |
| `conversation_io.py` | 對話 JSON v2 匯出、v1/v2 匯入、嚴格欄位與大小限制、Markdown 匯出、QSaveFile 原子寫入 |
| `conversation_widgets.py` | 對話管理與側欄、全文搜尋、釘選、更名、匯入匯出與刪除確認 |
| `timestamps.py` | 合法 epoch 秒數與本機 HH:MM；未知舊時間不補造，時間不送模型 |
| `images.py` | 檔案格式、大小、像素、方向與最長 1024 邊縮圖，輸出 base64 PNG |
| `attachments.py` | 小型 PNG 與標註資料驗證；限制單圖與圖片總保存量 |
| `grounding.py` | Box、定位 JSON schema、提示詞與解析；座標為 0–1000 的 xyxy，不產生假信心分數 |
| `annotation.py` | 畫布座標映射、人工新增／拖移／縮放／改名／刪除、50 步復原重做、AI 定位與相容重試、PNG／專案 JSON 匯入匯出 |
| `labelme_export.py` | 轉換正規化座標為前處理圖片的像素矩形，內嵌未畫框 PNG；不輸出原始私人圖片絕對路徑 |
| `dictation.py` | 麥克風權限與 30 秒錄音、PCM 轉換／靜音檢查、Whisper 子程序與暫存清理；辨識文字只填入草稿 |
| `speech.py` | 本機中文音色、朗讀文字前處理、say 子程序、stdin 傳文字、停止與逾時 |
| `speech_stream.py` | 增量句子切分，略過程式碼／表格，避免在數字、連結或未閉合標記中間切開 |
| `speech_widgets.py` | 關閉／分段／完成後三模式、音色與語速、有限句子佇列與試聽；停止須清除待播內容 |
| `reader.py` | 回答排版、原文與複製；LocalDocument 拒絕所有外部資源，Markdown 不解析 HTML |
| `model_settings.py` | 固定白名單下載、進度、取消／逾時、重新檢查；以 QProcess 參數陣列呼叫 Ollama |
| `service_widgets.py` | 非阻塞服務檢查結果視窗；只反映最近探測，不代表持續健康監控 |
| `assistant_activity.py` | AI 標題旁等待／生成狀態、單調計時與 viewport 錨定；不修改回答內容 |
| `indicators.py` | 共用向量轉圈與 timer |
| `theme.py` | 共用深淺 palette／CSS、局部樣式、唯讀文件重新上色；不改寫輸入框以保留草稿與復原 |

## 資料與狀態

- `history`：只供模型使用的近期完整問答，最多三輪／8,000 字；不等於資料庫全部歷史。
- `pending`：本次問題、附圖標記、送出／完成時間，以及選用的待保存圖片與框；只有成功結果才提交。
- `image`：下一次請求實際附帶的圖片；`last_image`：供檢視／標註的最近圖片。兩者不能混用，否則可能不小心重送圖片。
- `_annotation_sequence`：目前標註對應的已存問答序號，防止將框更新到其他圖片。
- `_draft_key`／`_draft_model`：對話專屬草稿或 `new:<model>` 草稿。變更模型時必須先處理原草稿，再更新索引。
- SQLite 表：`conversations`、`turns`、`drafts`、`settings`、`attachments`；刪除採 foreign key cascade，容量檢查與新增問答使用交易。
- 持久化：文字與草稿預設保存，圖片／框預設關閉；外觀、語音模式與音色只保留本次執行。
- 私人資料庫在系統使用者資料目錄，不在專案或移機來源 ZIP；未加密。

## 必須保留的行為

1. 非同步 Qt 網路與 QProcess，不在 UI 執行緒等待模型／下載。
2. 關閉與取消的回呼必須可靠清理；關閉後不能重新啟動請求，也不能寫入半份問答。
3. 錄音時停用切換對話／模型並停止朗讀；辨識完成後仍由使用者核對與傳送。
4. 不接回原生 `QAudioSource.stateChanged → _audio_state`，保留目前 100ms 裝置錯誤輪詢，避免已知 QAudio::State 轉換問題。
5. 時間插入先清除 QTextCursor 選取；Markdown 替換保留回答起點錨定，避免覆寫回答。
6. AI 定位最多相容重試一次，累計時間不中斷；保留人工框，失敗不覆寫現有標註。
7. 模型文字不執行，TTS 文字走 stdin；不跟隨重新導向，不經系統 proxy；連線僅限 loopback。
8. 不把 1024 邊縮圖座標當成原始高解析圖座標；Labelme 與專案 JSON 是不同格式。

## 腳本

| 腳本 | 用途 |
| --- | --- |
| `mac_python.py` | 本機 macOS 啟動器與用途宣告 |
| `verify_handoff.py` | 只用標準函式庫逐檔比對來源 manifest；不驗證額外檔案或來源身分 |
| `package_handoff.py` | 白名單來源封裝、逐檔 manifest 與 ZIP 校驗碼；不帶環境／模型／私人資料；本次未執行 |
| `smoke_local.py` | 正式 Qt 主視窗流程的文字與合成圖片問答，使用暫存資料庫 |
| `smoke_models.py` | 各模型文字、合成圖片與定位 JSON；程序成功不等於辨識與框位置正確 |
| `smoke_dictation.py` | 合成中文 WAV → Whisper → 清理，不使用麥克風 |
| `smoke_stream_speech.py` | 合成分段文字 → 暫存 WAV，不播放喇叭 |
| `smoke_stream_pipeline.py` | 真實本機模型串流與分段 TTS 並行，音訊寫暫存 WAV |

`run_windows.cmd` 是 Windows 入口，不取代本機 `run.command`。Windows 語音與實機操作仍不能由 Mac 測試推定。

## 測試分布與修改對照

| 測試檔 | 項數 | 修改時關注 |
| --- | --- | --- |
| `test_network_ui.py` | 45 | 網路終態、主視窗互斥、服務檢查、歷史／草稿、版面、關閉 |
| `test_speech.py` | 20 | stdin、聲音清單、取消、逾時、程序回收、完成朗讀 |
| `test_annotation.py` | 19 | 人工框／AI 框、座標、復原、匯入匯出、計時與相容重試 |
| `test_conversations.py` | 17 | 交易、容量、schema、草稿、搜尋、釘選與刪除 |
| `test_dictation.py` | 14 | PCM、倒數、錯誤輪詢、取消、辨識結果與暫存 |
| `test_core.py` | 12 | 串流協定、上下文、圖片限制 |
| `test_speech_stream.py` | 12 | 句子切分、佇列上限、停止與三模式 |
| `test_model_settings.py` | 8 | 下載白名單、程序、取消、逾時與服務重新檢查 |
| `test_conversation_io.py` | 7 | JSON／Markdown、容量與原子匯出 |
| `test_attachments.py` | 5 | PNG／框保存與交易，跨對話隔離 |
| `test_security.py` | 5 | loopback、Unicode、標籤與關閉後禁止請求 |
| `test_timestamps.py` | 4 | 時間合法性、schema 升級、JSON 相容及不覆寫回答 |
| `test_labelme.py` | 3 | 像素座標、內嵌圖片與匯出失敗保護 |
| `test_theme.py` | 3 | palette、次視窗、主題切換與指定配色對比 |
| `test_reader.py` | 1 | Markdown、程式碼複製與外部資源拒絕 |

## 本次查核發現：後續優先處理

### 草稿保存失敗後，新對話仍會重設輸入

已使用暫存 SQLite 重現兩種情況：草稿超過 16,000 字，以及模擬磁碟保存失敗。`Window._save_draft()` 正確回傳 False，但 `reset()` 忽略結果，接著 `_set_draft_context()` 將輸入替換為先前保存的草稿，新的未保存文字因此消失。

位置：`window.py` 的 `_save_draft`（457 行）、`reset`（842 行）、`request_new_conversation`（865 行）。`_model_changed`、`load_conversation` 也使用 reset，修正時應一併檢查切換路徑。關閉視窗已有失敗保護，但不能因此推定所有切換路徑都安全。

重現證據：`.logs/m4-review-draft-reproduction.json`。兩種情況均為保存失敗後，畫面從新文字回復到先前六字草稿。未操作使用者私人資料，未改動功能，尚未新增正式回歸測試。

建議修正方向：將保存失敗作為切換前的阻擋條件，保留輸入／模型／對話狀態；為新對話、模型切換與開啟歷史加入針對性回歸測試，再驗證正常切換及關閉。

### 已知品質與文件差異

- 0.8B 圖片語義測試有明顯誤判；其他模型也有定位偏移／漏框，屬已記錄品質限制，不能用 JSON 結構通過取代內容驗證。
- 部分舊 MD 仍寫 schema 4、尚未打包或沒有語音輸入；目前程式為 schema 5、有 Mac 語音輸入，封裝歷史以最新交接入口為準。
- 既有 175 項測試通過，但沒有覆蓋上述新確認的草稿切換失敗情境。

後續共同修改時，先依功能定位模組與資料狀態，再做必要變更及對應驗證；本文件作為起點，修改後應同步更新。
