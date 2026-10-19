# 2026-10-19 輕量模型擴充與相容性驗證

依使用者授權，在 Mac mini M4、16GB 統一記憶體上擴充模型選單並下載實測。這是目前工作目錄的來源修改，沒有重新建立舊交接 ZIP；原始 HANDOFF_MANIFEST 屬修改前的歷史基線。

## 如何使用

正常關閉舊版聊天視窗，再於 Finder 雙擊此專案的 `run.command`。從主畫面的「模型」下拉選單切換；切換會建立新對話，原有資料切換保護仍適用。下載／能力說明在「設定 → 模型下載與說明」。原有五個模型保留，預設仍是 Qwen3.5 2B。

看圖請選標示「圖文」的模型，按「附加圖片」選擇 PNG、JPEG 或 WebP。DeepSeek 與 NVIDIA 本次選用的輕量版本為純文字，會停用附圖與 AI 建議框；已有圖片仍可手動標註／匯出。麥克風及本機朗讀透過 Whisper 與 macOS TTS 工作，可以搭配文字或圖文模型；不代表這些模型原生接受音訊。此介面尚未接入影片或音訊檔直接多模態推論。

## 選型與限制

- DeepSeek R1 1.5B 是蒸餾推理模型，純文字；實測能回答，但偶爾使用簡體中文，繁體中文提示並非保證。
- Qwen3-VL 明確採用 `2b-instruct`。實測發現 `2b` 別名對應 Thinking 版：指定定位 JSON 時結果被放進 `thinking`，`content` 空白；不將內部推理當作正式答案或送去朗讀。舊別名已下載作診斷，但不列入介面；保留檔案，沒有自行刪除模型。
- NVIDIA 選用 `nemotron-3-nano:4b-q4_K_M`，避免無大小標籤下載 30B 預設模型。這款是 NVIDIA 發布的文字模型，並非圖文模型。NVIDIA Nano Omni `nemotron3:33b` 的公開下載量約 28GB，超過本機 16GB 記憶體，因此未安裝；參數中「活躍 3B」不等於僅需儲存／載入 3B 權重。
- 圖文模型可提出 AI 建議框，但這是模型估計，並非可靠物件偵測器；實際物件、OCR、中文與幾何位置仍需核對。合成雙色圖片測試不代表一般圖片準確率。

## 程式修改

`labchat/config.py` 為固定模型白名單新增能力資料；訊息建構與 `ChatClient` 在發出請求前拒絕將圖片送給純文字模型。主視窗同步調整附圖、重用圖片、提示、示範與傳送檢查；框選視窗保留人工操作並依模型能力限制 AI。

模型設定會顯示文字／圖片能力及正確官方頁；下載仍以參數清單啟動 Ollama，不使用 shell。圖片提示改為先回答當次問題，僅在詢問數量時使用計數表格，避免詢問左右顏色卻只收到數量表。

`smoke_local.py --model` 支援依所選模型走正式 Qt 串流流程，純文字模型略過圖片。`smoke_models.py` 同樣區分能力，圖片／定位跳過項目標記 `skipped`，不當作成功圖片測試；定位測試使用與正式介面一致的 2048 token 上限。

## 官方資料（2026-10-19 查核）

- [DeepSeek R1 1.5B](https://ollama.com/library/deepseek-r1:1.5b)
- [Qwen3-VL 版本與 Instruct／Thinking 標籤](https://ollama.com/library/qwen3-vl/tags)
- [NVIDIA Nemotron 3 Nano 量化標籤及輸入能力](https://ollama.com/library/nemotron-3-nano/tags)
- [NVIDIA Nano Omni](https://ollama.com/library/nemotron3:33b)
- [LiquidAI 官方 450M 圖文 GGUF](https://huggingface.co/LiquidAI/LFM2.5-VL-450M-GGUF)

官方標籤可能更新，以下交付紀錄以本機實際 digest／能力與測試為準。

## 功能回歸紀錄

- 212 項回歸測試通過（`.logs/model-expansion-unit-tests.log`），包含圖片誤送防護、能力切換、偏好白名單與 `thinking` 不進入顯示／朗讀串流的測試。
- Ruff 檢查、格式、Python 編譯、`pip check`、`run.command` 語法檢查通過。
- DeepSeek 正式 Qt 串流回答及正常退出通過（`.logs/expansion-deepseek-ui.log`）；取消時只產生一次終止結果，計時器已停止（`.logs/expansion-deepseek-cancel.log`）。
- 本機 Whisper 對合成中文語音辨識成功，暫存清理完成（`.logs/expansion-voice-input.log`）。本機分段 TTS 產生兩段有效音訊，無錯誤（`.logs/expansion-voice-output.log`）。這些測試沒有錄音或透過喇叭播放，真實麥克風與聽感仍由使用者實測。
- 小視窗 720×680 的模型選單與純文字提示已檢視，附圖按鈕會正確停用。
- NVIDIA Nemotron 4B 的正式 Qt 文字串流、正常退出與取消均通過；算術測試回答 `2`。證據為 `.logs/expansion-nvidia-ui.log`、`.logs/expansion-nvidia-smoke.log`、`.logs/expansion-nvidia-cancel.log`。`/api/show` 確認為 `nemotron_h`、Q4_K_M、純文字能力。


## 本機下載與模型實測結果

新增四個模型均已下載，九個介面選項皆經 `/api/tags` 及 `/api/show` 確認。大小為十進位 GB 的檔案大小，不是執行 RAM 用量；應用程式仍使用 4096 context 與單模型並行。

| 新增選項 | 下載大小 GB | 本機 digest 前 12 碼 | 文字 | 圖片 | AI 框選 |
| --- | ---: | --- | --- | --- | --- |
| DeepSeek R1 1.5B | 1.117 | `e0979632db5a` | 通過 | 不支援 | 不支援 |
| Qwen3-VL 2B Instruct | 1.931 | `afc393e3572c` | 通過 | 左藍右紅正確 | 兩區塊座標正確 |
| NVIDIA Nemotron 3 Nano 4B Q4_K_M | 2.838 | `6cc467f05439` | 通過 | 不支援 | 不支援 |
| LiquidAI LFM2.5-VL 450M Q4_K_M | 0.332 | `01d5ec51c8e9` | 傳輸通過，表達品質有限 | 傳輸通過，顏色辨識不穩定 | 幾何失敗，介面停用 |

Qwen Instruct 的文字、圖片與定位 JSON 三項成功，雙色圖定位為 `[0,0,500,1000]` 與 `[500,0,1000,1000]`，與合成圖片幾何一致。正式 Qt 圖文聊天亦完成並正常退出。證據：`.logs/expansion-vision-smoke.log`、`.logs/expansion-qwen-instruct-ui.log`。

LiquidAI 的第一輪能說出左藍右紅，正式 Qt 第二輪將左側藍色說為青色；它也未能正確回答關於本機／雲端的說明問題。定位只輸出 `[0,0,1,1]`，雖符合 JSON 結構但幾何錯誤，因此 `grounding=False`，停用這款的 AI 建議框，保留圖片聊天、人工標註與匯出。它僅適合低資源試驗，不建議取代預設 2B。證據：`.logs/expansion-liquid-ui.log` 與同一視覺測試紀錄。對定位的停用另有回歸測試。

這些測試不應合併稱為全部回答正確；`smoke_models.py` 的 success 只代表請求完成及回覆／JSON 可解析。最終腳本會將純文字的圖片項目、LiquidAI 的定位項目標記 skipped。完整模型大小、能力與 digest 見 `.logs/model-expansion-inventory.json`。


## 最終完整性與交付

- 四個新增模型合計 20 個不重複權重／設定 blob 的大小與 SHA256 全部吻合，manifest digest 與本機模型清單相符；紀錄為 `.logs/model-expansion-integrity.json`。
- 最後對預設 Qwen3.5 2B 與四個新選項執行 15 個階段，其中 10 個完成請求／結構檢查，5 個依能力略過，沒有傳輸錯誤。略過為 DeepSeek／NVIDIA 各兩個影像項目，以及 LiquidAI 的定位；不是 15 項全部成功。結果見 `.logs/model-expansion-final-smoke.json`。預設 Qwen3.5 的定位框高度仍有偏差，需人工修正；未將此項宣稱為幾何通過。
- 正式 Qwen Instruct 框選視窗回傳兩個正確合成圖框，完成後計時器停止，紀錄為 `.logs/expansion-qwen-annotation.json`。
- 最終深色設定畫面及模型下拉清單已檢視，9 款均顯示已安裝；截圖為 `.logs/model-expanded-dropdown.png`、`.logs/model-expanded-settings.png`。
- 修改前來源備份為 `.logs/before-model-expansion-20261019-090820.zip`，不含私人對話與模型。沒有刪除原有模型、重建私人資料庫或修改隱私權設定；舊視窗需正常關閉，再透過 `run.command` 載入新程式。
