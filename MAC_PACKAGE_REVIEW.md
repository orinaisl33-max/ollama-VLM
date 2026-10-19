# Mac mini M4 來源交接包檢查

交付日期：2026-10-16。這次已依使用者指示重建 `dist/labchat-mac-handoff.zip`；Windows ZIP 不更新。

## 檔案與使用入口

- `MAC_MINI_M4_START.md`：使用者教學與可直接貼給Codex的重建指令。
- `MAC_CODEX_HANDOFF.md`：目前架構、資料版本、資源邊界與近期修正。
- `HANDOFF_MANIFEST.json`：ZIP內逐檔大小與SHA256，清單本身不自我雜湊。
- 同名 `.zip.sha256`：ZIP整檔校驗；原機使用者應保留可信校驗碼。

## 包含項目

完整 `labchat/*.py`、`main.py`、Logo、測試、必要腳本、鎖定runtime與開發套件清單、Mac啟動器、所有專案根目錄MD教學。跨平台Windows文件與啟動器保留作背景，Mac依專用指南操作。

最新功能包含：完整高度對話側欄、深淺色、精簡輸入與集中設定、使用者藍色提問區塊、時間標記、對話／草稿與選用圖片保存、Markdown安全呈現、模型下載設定、服務檢查結果視窗、三種朗讀模式、麥克風圖示與30秒倒數、定位等待計時、人工／AI框與Labelme匯出。錄音原生QAudio::State訊號錯誤已以100ms裝置錯誤輪詢避開。

## 排除項目

`.venv`、`.runtime`、`.logs`、`models`、`dist`、快取、私人圖片／音訊、SQLite資料庫與其journal、原機測試artifacts。不包含完整Codex舊對話、帳號、登入或權限。

因此新M4需要安裝工具、重新建venv、下載模型與中文聲音；本包不構成完整離線安裝媒體。資料庫另行搬移需使用者授權、先備份並關閉兩邊程式。

## 驗證方式與界線

交付時對ZIP執行CRC檢查、解壓至全新暫存目錄、執行包內verify_handoff、逐檔對照工作區來源，檢查排除項目及啟動檔權限，並在解壓來源重新跑測試。實際結果與檔案數、ZIP雜湊記錄在ZIP外的 `dist/MAC_M4_DELIVERY_CHECK.txt`，避免產生清單自我引用。

原機最新175項回歸測試通過，Ruff／格式／compileall／pip check／zsh語法檢查通過。套件與模型安裝命令核對官方來源，Whisper small SHA256同時比對官方LFS指標與本機檔案。未在本次交付重新進行公開漏洞資料庫掃描。

未在Mac mini M4實機安裝、錄音、試聽或長時負載驗證；新機必須產生自己的 `M4_VALIDATION.md`，不能把本機測試當作M4驗收。套件／模型可能更新，標籤非內容鎖定；不承諾跨機效能或模型答案完全一致。
