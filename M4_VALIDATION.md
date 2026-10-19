# Mac mini M4 安裝與驗收紀錄

> **2026-10-19 游標防護與診斷：215 項回歸通過；原警告尚未重現，改善與限制見 [CURSOR_DIAGNOSTICS_20261019.md](CURSOR_DIAGNOSTICS_20261019.md)。**

> **2026-10-19 最新模型擴充：九個介面選項均已安裝，212 項回歸通過；模型能力與品質限制見 [MODEL_EXPANSION_20261019.md](MODEL_EXPANSION_20261019.md)。**

> **最新操作改善：搜尋合併、歷史批次排版、直接複製回答與快捷鍵已完成，詳見 [SMOOTHNESS_UPDATE.md](SMOOTHNESS_UPDATE.md)。**

> **最新修改版：見 FIRST_BATCH_UPDATE.md。第一批資料保護、麥克風診斷與偏好保存已完成，完整回歸 192 項通過。下方舊缺陷與設定限制保留作歷史紀錄。**

日期：2026-10-16（Asia/Taipei）。本文件記錄本次新機實際執行結果；不是沿用原機測試數字。

## 環境

- Mac mini／Apple M4／10 核心／16GB RAM。
- macOS 26.4（25E246），原生 arm64；安裝前可用空間約 396GiB。
- Python 3.11.15；專案新建 `.venv`；pip 26.1.2。
- PySide6 6.12.0，依 `requirements.lock.txt` 原樣安裝全部六個 runtime 套件；Ruff 0.17.0。
- Homebrew Ollama 0.32.1；Whisper `whisper-cpp` 1.9.1。本機 Homebrew 不提供文件中的 `whisper.cpp` 公式名，依其回報使用 `whisper-cpp`，實際 `whisper-cli` 可執行。
- 已有中文聲音 Meijia（zh_TW）、Sinji（zh_HK）、Tingting（zh_CN）。未播放聲音。
- Ollama 啟動環境：`OLLAMA_HOST=127.0.0.1:11434`、`OLLAMA_NO_CLOUD=1`、`OLLAMA_MAX_LOADED_MODELS=1`、`OLLAMA_NUM_PARALLEL=1`。lsof 確認只監聽 127.0.0.1:11434。

## 來源與模型完整性

- `python3.11 scripts/verify_handoff.py`：75 個來源檔案符合 manifest，安裝後再次核對通過；原始碼與既有 MD 未修改。
- 外部 ZIP CRC 通過，SHA256：`7a246773e14616eb26ed213c512262d747caea3ca6de1c5ffe8a66ba816be5d5`。未提供獨立 `.sha256`，因此此值僅記錄，未驗證 ZIP 來源身分。
- Whisper small 多語言模型 SHA256 通過：`1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b`，驗證後才從 `.part` 改名啟用。
五個選單模型均已完成下載及 Ollama SHA256 校驗；最終 `/api/tags` 與 `/api/show` 核對通過。完整 digest 與能力見 `.logs/m4-model-inventory.json`。

| 模型 | ID（前12碼） | 大小（十進位 GB） |
| --- | --- | --- |
| `qwen3.5:2b` | `0689d44085e0` | 2.683 |
| `qwen3.5:4b` | `d8b0f5e9760c` | 3.324 |
| `qwen3.5:0.8b` | `de63045f2975` | 1.322 |
| `ministral-3:3b` | `f04aa1c738f6` | 2.954 |
| `gemma3:4b` | `68ceab7e468a` | 3.350 |

模型邏輯大小合計約 13.63 GB；實際磁碟用量受共享權重影響。

0.8B 首次下載遇來源 HTTP 503，重試利用快取後成功。`.logs/model-download-results.json` 保留首次失敗歷程，最終以本機模型清單及重試紀錄為準。

Qwen 2B、4B、0.8B 與 Ministral 的文字／圖片傳輸、非空回覆與定位 JSON 解析均成功。2B、4B 與 Ministral 的合成圖左右顏色回答正確；0.8B 的圖片語義測試失敗（數量、位置及形狀誤判），已安裝可用但不代表回答可靠。各模型定位框均有偏差，JSON 可解析不代表幾何或辨識正確。預設模型保持 2B。Gemma 文字與圖片左右顏色回答正確，定位 JSON 可解析，但漏掉紅色區塊且藍框高度不足。全部五個模型共 15 項傳輸／結構測試成功；語義與框選品質須分別評估，不能稱為 15 項準確率測試。完整結果見 `.logs/m4-model-smoke-results.json`。

最終狀態：環境安裝完成、五個模型下載完成、175 項回歸通過、正式程式已啟動。真實麥克風、音色聽感與使用者操作留待實測。

## 已執行檢查

| 項目 | 結果 | 證據與範圍 |
| --- | --- | --- |
| 新建 .venv、鎖定套件與架構 | 通過 | arm64、Qt 6.12.0；pip check 無相依問題 |
| 完整回歸測試 | 通過 | 175 項／49.135 秒；`.logs/m4-unittest.log`；暫存資料庫與本機假服務 |
| Ruff 靜態與格式 | 通過 | `ruff check main.py labchat tests scripts`；format --check 49 個 Python 檔案 |
| 編譯與啟動腳本語法 | 通過 | compileall main.py/labchat/scripts/tests；zsh -n run.command |
| 預設模型正式聊天流程 | 通過 | `scripts/smoke_local.py`；文字與左藍右紅合成圖回答正確；約 4.9 秒，非效能基準 |
| 真實模型取消 | 通過 | 第一段輸出後取消，終態 cancelled，請求與 timer 清理；`.logs/m4-real-cancel.json` |
| 語音辨識引擎 | 通過 | `scripts/smoke_dictation.py`；合成語音辨識約 7.39 秒，輸出「您好,请帮我整理今天的工作重点。」；暫存清理正常 |
| 串流分段朗讀管線 | 通過 | `scripts/smoke_stream_pipeline.py`；模型生成未結束前開始 TTS，三段 WAV 有效、無錯誤；音訊僅暫存檔，無喇叭播放 |
| 深淺色與小視窗 | 通過（離屏） | 已檢視 1200×900 淺色、720×680 深色截圖；`.logs/m4-ui-light.png` 與 `m4-ui-dark.png` |
| 本機啟動器 | 通過 | 建立 `.runtime/LabChat.app`，麥克風用途宣告與 codesign --verify --deep --strict 通過 |
| 正式啟動 | 通過（程序） | `./run.command` 啟動 `.runtime/LabChat.app`，最終 pgrep 確認程序存活，`.logs/m4-gui.log` 無錯誤輸出；原生視窗操作待使用者確認 |
| 對話、草稿、時間、標註、匯出 | 通過（自動化） | 完整回歸涵蓋 SQLite 升級、保存、JSON 往返、PNG、Labelme、框選調整與復原重做；未操作私人資料庫 |

## 尚未實測

| 項目 | 狀態與原因 |
| --- | --- |
| 真實麥克風、首次權限、停止與取消 | 未測；保留給使用者主動操作，沒有錄音或變更隱私設定 |
| QAudio::State 實機收音問題 | 錯誤輪詢回歸通過；真實裝置尚未測，不宣稱完全排除 |
| 中文 TTS 音色聽感、喇叭與三模式操作 | 未測；僅測試合成音訊檔與程序管線 |
| 原生桌面完整操作與外接螢幕 | 未測；Computer Use 工具回報未授予電腦控制權限；離屏排版已檢視 |
| 真正斷網後運作 | 未測；測試推論走 loopback，但沒有關閉系統網路 |
| 長時間運作與記憶體壓力 | 未測；不以短測推估長時間穩定性 |
| Labelme 外部程式開檔 | 未測；只驗證輸出結構、內嵌圖片與座標，不另安裝 Labelme |

## 使用方式

在 Finder 雙擊本專案的 `run.command`。模型選單可切換已下載模型；切換將建立新對話。若主視窗早於其他模型下載前啟動，請用「設定 → 檢查本機服務」更新安裝狀態。

麥克風與中文音色請由使用者實測。Mac mini 需要可用的外接／其他輸入裝置；未假設有內建麥克風。資料庫依原設定保存於使用者資料目錄且未加密；本次測試使用暫存資料，不混入私人歷史。

本次未重新打包或上傳，未變更系統 Python、Gatekeeper 或隱私權設定。模型名稱為可更新標籤，實際 ID 以本次本機清單為準。

## 安裝後完整性複查與程式理解

2026-10-16 依使用者要求再查核：五個模型 manifest 與本機服務 digest 一致，全部 25 個不重複權重／設定 blob 的大小與 SHA256 正確；七個鎖定 runtime／開發套件版本正確，Whisper 模型雜湊、本機啟動器簽章及用途宣告通過。證據：`.logs/m4-install-integrity-recheck.json`。

已逐模組檢閱本專案第一方程式、啟動／封裝／實機腳本與 15 個測試檔；49 個 Python 檔共 9,142 行，175 個測試方法。25 個 labchat 模組均可在本機匯入。模組責任、資料流、修改連動及測試對照見 `PROJECT_MAP.md`；逐檔索引與 SHA256 見 `.logs/m4-code-inventory.json`。本次未修改功能原始碼，既有 175 項測試結果仍指上一輪完整測試。

查核另外確認一個既有缺陷：草稿保存失敗後建立新對話，`reset()` 忽略 `_save_draft()` 的 False，可能將未保存文字替換為舊草稿。已以超長草稿與模擬保存失敗兩種情境、暫存 SQLite 重現；證據見 `.logs/m4-review-draft-reproduction.json`，細節與修正方向見 `PROJECT_MAP.md`。尚未修正，不能把環境完整或既有測試通過解讀為程式沒有缺陷。

## 2026-10-16 再次模型與語音測試

依使用者最新要求重測，證據保存在 `.logs/retest-20261016/`。這一輪確實播放了一句短測試語音，前面安裝紀錄的「未播放」只描述先前階段。

- 本機 `/api/tags` 確認五個模型均已安裝，digest 與原安裝紀錄相同，因此未重複下載或更新權重。
- 完整回歸：175 項通過，10.905 秒。涵蓋對話、草稿、資料交易、標註編輯與匯出、三種朗讀模式、錄音狀態與取消、網路及關閉清理。先前確認的草稿重設缺陷仍未修改，原有測試未涵蓋該情境。
- Ruff 靜態／格式 49 檔、pip check、來源 manifest 75 檔、zsh 語法、本機啟動器 codesign 驗證通過。
- 五模型各執行文字、合成圖片與定位，共 15 項傳輸／結構檢查成功。0.8B 仍誤認合成圖的顏色分布與物件；其他四個模型的左右顏色回答正確。所有模型的框仍需人工核對，Gemma 漏掉紅色區塊；不將結構通過當作定位準確率。
- 正式主視窗文字／圖片流程通過，約 5.9 秒。
- Whisper 合成中文辨識通過，約 0.84 秒，得到「您好,请帮我整理今天的工作重点。」；暫存已清理。速度受快取與當下負載影響，非效能基準。
- 獨立分段 TTS 輸出兩段有效 WAV，無錯誤；真實模型與 TTS 並行測試亦通過，生成完成前開始朗讀，三段音訊有效，管線約 2.291 秒。這兩項只輸出暫存 WAV。
- 已告知後使用 `/usr/bin/say -v Meijia -r 175` 播放「您好，這是本機中文語音測試。」；程序正常退出（0），但未取得使用者實際聽見或音質滿意的確認。
- Qt 音訊裝置列舉：輸出為「Mac mini的揚聲器」「24HC1QR」，輸入清單為空。真實麥克風收音測試因未偵測到輸入裝置而未進行，未錄音、未修改麥克風權限；需接上可用裝置後再測。

本輪沒有修改程式功能、升級套件、重打包或上傳資料。外接麥克風、使用者實際聆聽、長時間負載及真正斷網驗收仍不可視為已通過。
