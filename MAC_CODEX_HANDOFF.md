# 給 Mac mini M4 接手的 Codex

> **GitHub 新使用者請先閱讀 [目前 Mac 安裝圖解](docs/INSTALL_MAC.md)。本文件保留較早的來源包／移機流程；舊 ZIP 與 HANDOFF_MANIFEST 的校驗不是目前 GitHub 安裝步驟。首次安裝用 install.command，日常啟動用 run.command。**

交付日期：2026-10-16。本次使用者已授權打包最新Mac來源；先前「尚未打包」僅為歷史紀錄。新機本身的操作以當前使用者授權、本機AGENTS.md及權限為準。

## 入口與優先順序

1. `MAC_MINI_M4_START.md`：給使用者的教學、可直接貼給Codex的完整提示詞、逐步建置與驗收指令。
2. 本文件：目前架構與近期修正。
3. `README.md`、`FEATURES.md`、`VOICE_INPUT.md`：功能與語音細節。
4. `SECURITY_REVIEW.md`頂部最新複查、`QUALITY.md`末尾最新驗證。
5. `CODEX_HANDOFF.md`：完整開發歷史；其中Windows安裝指令不適用本機。

先驗證來源，再安裝環境，最後才修改程式。ZIP內的 `HANDOFF_MANIFEST.json` 與 `scripts/verify_handoff.py` 提供逐檔校驗；校驗後開發修改會讓原manifest不符，屬預期行為，不能把它當作新版本簽章。

## 目前版本與安裝邊界

- 原機 MacBook Air M2 8GB；Python3.11.15、PySide6 6.12.0、Ollama0.40.0，僅供基準。M4應使用原生arm64，記錄實際版本。
- 由 `requirements.lock.txt` 重建新的 `.venv`，開發驗收再安裝 `requirements-dev.txt`。不要複製舊venv／runtime或修改系統Python。
- Qt鎖版目標macOS14以上；新機若無相容套件，先排查而非直接解除鎖版。
- 來源包不含Ollama／Whisper模型、原生引擎、macOS中文音色、私人SQLite、日誌與測試圖片。
- 原機有 `qwen3.5:2b`、`ministral-3:3b`、`gemma3:4b`；新機重新下載並記錄ID，另外兩個Qwen選項為選用。
- 本機API固定起點127.0.0.1:11434；只允許loopback、停用系統proxy、不自動重新導向。單模型、單並行、4096context。
- Whisper使用Homebrew `whisper.cpp` 的 `whisper-cli` 與 `models/ggml-small.bin` 多語言small。模型SHA256在教學與VOICE_INPUT.md。
- `run.command` → `scripts/mac_python.py` → 本機生成 `.runtime/LabChat.app` → `main.py`；用途宣告與ad-hoc簽章在新機重建，不是固定舊程式包。

## 模組與重要保護

| 模組 | 責任與限制 |
| --- | --- |
| window.py | 左側完整歷史、右側聊天與精簡輸入；設定選單集中進階功能；操作狀態互斥 |
| client.py / protocol.py / security.py | 非同步Ollama、取消／逾時、串流大小與Unicode驗證、本機位址限制 |
| conversations.py / conversation_io.py | 交易SQLite、schema5、草稿與保存偏好；JSON匯出v2／匯入v1或v2 |
| timestamps.py | epoch保存、以目前電腦時區顯示HH:MM；無舊時間不補造，不送模型 |
| reader.py / theme.py | MarkdownNoHTML、拒絕外部資源與連結導航；深淺色共用主題 |
| dictation.py | 30秒本機錄音、倒數、獨立Whisper程序、暫存清理、核對文字再送 |
| speech.py / speech_stream.py / speech_widgets.py | `/usr/bin/say` stdin朗讀、三模式、有限句子佇列、停止／關閉清理 |
| annotation.py / grounding.py / labelme_export.py | 人工與AI框、復原重做、匯出、定位計時與相容重試 |
| service_widgets.py / model_settings.py | 可見服務檢查、白名單下載、取消與進度；下載需使用者確認 |

## 最近必須保留的修正

- 使用者提問淺藍區塊，AI依主題保持清楚對比；完成後安全呈現Markdown，原文字保存不變。
- 進階設定集中於「設定」，圖片操作按情境顯示；錄音期間不切換模型／對話，開始錄音停止TTS。
- 問題顯示送出時間，AI顯示成功完成時間。時間插入需清除Qt游標選取，避免覆寫回答；有回歸測試。
- AI標題旁等待／生成轉圈與經過秒數，定位旁「已運行MM:SS」；完成／取消後顯示耗時，相容重試連續計時。
- 麥克風按鈕為向量圖示與「使用麥克風語音輸入」。**不能重新接回 `QAudioSource.stateChanged → _audio_state`**：實機有原生 `QAudio::State` 轉換TypeError；先前@Slot()也未解決。現改由100ms倒數timer與start後讀取source.error()。
- 標註視窗初始尺寸與位置限制在父視窗所在螢幕可用範圍。
- 手動「檢查本機服務」開啟非阻塞進度／結果視窗；啟動時自動檢查不彈窗。不下載或載入模型。
- 文字／圖片／模型輸出不可成為shell或Python指令。TTS文字走stdin、下載與Whisper使用QProcess參數陣列。
- SQLite未加密；私圖預設不保存。測試一律暫存DB，不讀寫使用者真實紀錄。AI建議框與數量不是已驗證真值。

## 新機驗收

原機最新完整測試 **175項通過**，Ruff／格式／compileall／pip check／zsh語法通過。這些只代表原機，不等於M4已驗證。

按教學先重建，再執行測試與真實模型驗收。請保留此來源架構，遇到不相容記錄原因，未經指示不升級整套依賴、不刪私人資料、不靜默替換模型、不改成雲端服務。

請產生 `M4_VALIDATION.md`，區分「通過／失敗／未測」，特別記錄真實麥克風、權限、TTS與離線測試、外接螢幕、模型ID與記憶體壓力。不要沿用歷史數字冒充新機結果，不宣稱零風險。後續打包與上傳依新指令進行。
