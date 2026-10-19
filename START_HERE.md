# 移機包：從這裡開始

> **GitHub 新使用者請先閱讀 [目前 Mac 安裝圖解](docs/INSTALL_MAC.md)。本文件保留較早的來源包／移機流程；舊 ZIP 與 HANDOFF_MANIFEST 的校驗不是目前 GitHub 安裝步驟。首次安裝用 install.command，日常啟動用 run.command。**

> **2026-10-16 Mac mini M4 最新交付入口：請先讀 [MAC_MINI_M4_START.md](MAC_MINI_M4_START.md)。本次已授權更新 Mac 來源 ZIP，較早的「尚未打包」敘述是歷史紀錄。Windows ZIP 本次未重建。**

這是「人工智慧系統實驗室 · 展示工具」的原始碼與 Codex 交接包，不是已安裝完成的應用程式，也不是離線套件／模型安裝包。

## Mac 使用者先看這裡

Mac 移機請先讀 `MAC_SETUP.md`、`MAC_CODEX_HANDOFF.md` 與 `MAC_PACKAGE_REVIEW.md`；下方 PowerShell 範例只適用 Windows。Mac 在 ZIP 所在目錄執行 `shasum -a 256 -c labchat-mac-handoff.zip.sha256`，解壓後進入 labchat 目錄，執行 `python3.11 scripts/verify_handoff.py` 驗證來源。Python3.12使用者改成 `python3.12`。macOS需14以上，新機重建環境與下載模型，語音使用新機本地聲音。

## Windows 檔案閱讀順序

1. `PACKAGE_REVIEW.md`：封裝檢查範圍、排除項目與驗證限制。
2. `WINDOWS_SETUP.md`：Windows 安裝、環境、模型與實機驗收。
3. `CODEX_HANDOFF.md`：貼給下一台 Codex 的提示詞、架構及待辦。
4. `README.md`：操作說明；前段啟動命令以 Mac 為主，Windows 請依專用指南。
5. `SECURITY_REVIEW.md`、`QUALITY.md`、`INSTALLATION.md`：原機歷史驗證，不代表新電腦已完成驗證。

## 下載後確認完整性

上傳時一起保存 ZIP 和同名 `.zip.sha256`。下載到 Windows 後先在 PowerShell 執行：

```powershell
Get-FileHash .\labchat-windows-handoff.zip -Algorithm SHA256
Get-Content .\labchat-windows-handoff.zip.sha256
```

核對兩者雜湊相同，也可比對原機保留的校驗碼。校驗碼可檢查內容是否改變，不是數位簽章；如果 ZIP 與校驗碼一起被更換，不能靠此驗證來源身分。

解壓後在 `labchat` 目錄執行下列命令，只需先安裝 Python，不需 Qt 或模型：

```powershell
py -3.11 scripts\verify_handoff.py
```

若安裝的是 Python 3.12，改用 `py -3.12`。預期顯示 `Verified ... source files`。失敗時停止安裝，重新下載並比較雜湊；勿忽略檔案不符。

`HANDOFF_MANIFEST.json` 列出每個來源檔案的 SHA-256 與大小，不包含清單本身。校驗應在修改程式之前進行；開發修改後不符是預期現象，需重新建立發行包。驗證器不掃描解壓目錄中額外的檔案，請解壓至新的空目錄。

Mac 語音輸入需另依 VOICE_INPUT.md 安裝引擎與模型，並使用 run.command 啟動取得麥克風權限。Windows 語音輸入停用，TTS 尚未實作；Windows 安裝、GUI、DPI、模型推論仍需實機驗收。模型、虛擬環境、私人測試圖、歷史標註與日誌不在本包。完整舊 Codex 對話也不在包內，接續背景已整理於交接文件。
