# 發布與不要上傳的清單

[回專案首頁](../README.md) · [Mac 安裝圖解](INSTALL_MAC.md)

`.gitignore` 是 Git 使用的排除清單；這份文件負責讓維護者理解規則。它不會刪除本機檔案，也不會自動移除已經提交的資料。詳細機制見 [GitHub 官方說明](https://docs.github.com/en/get-started/git-basics/ignoring-files)。

## 哪些檔案可以放進 GitHub

| 類別 | 預計上傳 |
| --- | --- |
| 程式 | `main.py`、`labchat/`、`scripts/`、`restore.command`、`install.command`、兩平台啟動檔 |
| 安裝與開發設定 | `requirements*.txt`（含 Mac SHA256）、`Brewfile`、`environment.lock.json`、`pyproject.toml`、`.gitignore`、`.gitattributes` |
| 測試 | `tests/` 中的原始碼，不含執行時輸出 |
| 必要素材 | `logo.png`、`assets/` |
| 圖文教學 | `README.md`、`docs/`、根目錄 Markdown 文件 |
| 公開測試素材 | `測試圖/` 中維護者指定公開的 6 張 JPG 及 README；約 3.3MB |
| 歷史交接基線 | `HANDOFF_MANIFEST.json`；僅對應舊來源包，不是 GitHub 安裝前提 |

`docs/images/` 的截圖使用暫存示範資料與人工合成圖片，刻意納入發布；不要將私人使用截圖放進這個資料夾。

例外是維護者已指定公開的 `annotation-room-example.png` 場景截圖，以及 `測試圖/` 的 6 張素材。這些是明確選定的公開示範，不表示可任意上傳其他私人圖片。`測試圖/` 現在不是忽略目錄；私人測試請放入 `private/`。

## 哪些內容會被排除

| 不上傳的內容 | 規則範例 | 原因 |
| --- | --- | --- |
| Python 環境與快取 | `.venv/`、`__pycache__/`、`.ruff_cache/` | 新電腦需重建，體積大且不可直接搬用 |
| 本機執行環境 | `.runtime/` | 依新機建立啟動環境與簽章 |
| 日誌與診斷 | `.logs/`、`*.log` | 執行機器資料，不屬原始碼 |
| 模型權重 | `models/`、`.ollama/`、`*.gguf`、`*.safetensors` 等 | 大型外部依賴，依來源與授權另行下載 |
| 對話與本機資料庫 | `*.sqlite3`、`*.sqlite`、`*.db` 及附屬檔 | 私人對話、草稿與個人設定 |
| 匯出與個人資料目錄 | 根目錄 `exports/`、`recordings/`、`user_data/`、`private/`、`backups/` | 私人圖片、對話、錄音與備份 |
| 錄音／音訊輸出 | `*.wav`、`*.mp3`、`*.m4a`、`*.flac` | 不放進原始碼版本紀錄 |
| 環境檔與憑證 | `.env*`、`*.pem`、`*.key`、`credentials*.json`、`secrets*.json` | 避免帳號金鑰或本機設定外傳 |
| 封裝與系統暫存 | `dist/`、`*.zip`、`*.dmg`、`.DS_Store` | 發布產物及暫存不與來源混放 |

`.env.example`／`.env.*.example` 可加入版本，但只能放假值或欄位說明，不可含實際金鑰。`.git` 本身是 Git 管理資料，不是被推送的專案檔案；GitHub CLI 的登入憑證也不應複製進專案。

**排除規則無法辨識任意檔名的私人內容。** 私人圖片另存到普通 PNG、對話另存成任意 JSON，仍可能被列入候選；因此每次上傳前仍須檢查實際清單。刻意使用 `git add -f` 可以繞過忽略規則，請勿用來加入模型或私人檔案。

## 第一次上傳的檢查順序

### 1. 確認專案、帳號與遠端

在專案根目錄執行：

```sh
pwd
git remote -v
git config --local user.name
git config --local user.email
gh auth status
```

本專案的預定遠端為 `https://github.com/orinaisl33-max/ollama-VLM.git`。檢查登入狀態即可，不要列印或分享 Token。

### 2. 預覽上傳候選與忽略規則

```sh
git status --short
git add --dry-run .
git check-ignore .venv .runtime .logs models
```

確認候選包含程式、測試、文件與教學圖片，不含模型、私人資料或本機環境。忽略規則只能保護尚未追蹤的檔案；已追蹤的資料需另行處理，不能只加 `.gitignore` 就認為已移除。

### 3. 清單確認後才加入並檢查暫存區

```sh
git add .
git diff --cached --stat
git diff --cached --name-only
```

此時仍未上傳。檢查內容、來源素材與權利範圍；不要替專案或第三方 Logo／模型自行宣告未經確認的開源授權。現有文件與素材不能因為放上 GitHub 就視為已授予任意重用權。

### 4. 建立第一筆提交

```sh
git commit -m "Initial source and illustrated installation guide"
```

### 5. 核對遠端後上傳

```sh
git ls-remote origin
```

全新且空白的儲存庫可能沒有輸出。若已有分支或檔案，先檢查遠端內容並整合，不要用 force push 覆蓋。

確認遠端狀態與欲發布內容後才執行：

```sh
git push -u origin main
```

發布完成後，在 GitHub 檢查 README 圖片及連結、程式目錄、儲存庫可見性與實際分支。Private 專案的下載者需要獲邀；只有改成 Public 才能讓一般未登入訪客讀取來源，這需要由擁有者另行決定。

## 若誤加入私人檔案

尚未提交時先從暫存區移除指定檔案，再檢查忽略規則。若已提交或推送，刪除最新版本不會抹除歷史；若含金鑰，需撤銷該金鑰並依 GitHub 的敏感資料移除流程處理，勿只刪除畫面上的檔案就認為解決。

## 本次準備狀態

已建立圖文首頁、安裝指南、教學圖片與排除清單。準備與預覽不等於已提交或上傳；以實際 `git status`、提交及遠端結果為準。
