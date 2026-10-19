# 本機語音輸入（Mac 測試版）

> 新 Mac 若需重建全部九模型與語音，可使用 [完整復刻精靈](docs/REBUILD_MAC.md)。若只加裝語音、不需要額外聊天模型，依本頁手動步驟即可。

## 操作

1. 關閉舊視窗，再雙擊專案根目錄的 `run.command`。
2. 按「使用麥克風語音輸入」，首次使用時允許 macOS 麥克風權限。
3. 說完按「停止錄音」，每次最長 30 秒。介面以單調計時器顯示剩餘秒數，最後 5 秒加強提示；到時自動停止並開始辨識。
4. 辨識時顯示轉圈提示，可按「取消」。
5. 結果會接在原有輸入文字後方。先核對並修改，再按「傳送」。不會自動傳送。

開始錄音會停止既有朗讀，並暫停模型切換、新對話與語音播放控制；AI 正在回答時不開放錄音。錄音不自動送給聊天模型，也不作為對話附件保存。

## 本機安裝

本次重新核實 `whisper-cli --version` 為 Homebrew `whisper.cpp` 1.9.1（先前記錄的 1.9.5 有誤），下載多語言 `small` 權重。現有 Python Qt 環境提供 QtMultimedia，不另加 Python 語音套件。

換另一台 Mac 時需重新安裝引擎與模型：

```bash
brew install whisper.cpp
mkdir -p models
curl -fL --retry 2 -o models/ggml-small.bin.part https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
shasum -a 256 models/ggml-small.bin.part
# 先確認雜湊符合下方數值，再執行：
mv models/ggml-small.bin.part models/ggml-small.bin
```

SHA256：`1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b`。
來源：[whisper.cpp](https://github.com/ggml-org/whisper.cpp)、[模型與校驗碼](https://huggingface.co/ggerganov/whisper.cpp/blob/main/ggml-small.bin)。模型約 488 MB（466 MiB），不要下載名稱帶 `.en` 的英文限定版本。

`models/` 不進入現有來源交接 ZIP。移機需依本頁重新下載。Windows 版按鈕停用，尚未驗證 Windows 錄音流程。

## Mac 麥克風權限

`run.command` 透過 `scripts/mac_python.py` 建立專案內 `.runtime/LabChat.app` 作為本機 Python 啟動環境，包含麥克風用途宣告及本機 ad-hoc 簽章。不修改系統 Python、不修改系統隱私權設定。這是可重新建立的本機執行檔，並非可搬移的獨立安裝包；不進入交接 ZIP。

請使用 `run.command` 啟動。直接執行 `python main.py` 可能因缺少 macOS 用途宣告而無法取得麥克風權限。

拒絕權限後，可至「系統設定 → 隱私權與安全性 → 麥克風」允許實際顯示的程式，再重新啟動。無裝置或無權限會顯示提示，仍可繼續打字。只在主動按下錄音時要求權限，不在啟動時錄音。

## 資源、準確度與資料

- 全程本機辨識，首次安裝需要網路；執行辨識不需雲端服務。
- 固定中文辨識，支援一般國語及部分中英混合。可能輸出簡體字，沒有強制繁簡轉換。人名、專業詞、台語與雜音需實測，不承諾固定準確率。
- 接近靜音或短於 0.3 秒的錄音不送入模型。這是音量檢查，並非完整語音活動偵測，也不能完全防止幻覺。
- 一次最長 30 秒；音訊最多 32 MiB；辨識逾時 180 秒；輸出文字檔最多 32,000 bytes；填入時仍遵守原有提問長度上限。
- 優先使用裝置支援的 16 kHz、單聲道、16-bit PCM；不支援時轉換一般裝置格式。
- 錄音期間僅放在記憶體；辨識期間在系統私有臨時資料夾產生 WAV 與文字結果，成功、取消、失敗、正常關閉後刪除。程式或系統異常崩潰時，可能殘留臨時資料夾；不宣稱安全抹除。
- 不把語音或辨識文字寫入應用程式日誌。填入輸入框後，文字會依原有「草稿／對話紀錄」設定處理。
- Whisper 以獨立子程序執行，完成後退出並釋放辨識模型；不持續常駐。既有 Ollama 模型可能仍常駐，8GB 電腦請先用 2B 模式並關閉不必要程式；兩種引擎同時佔用的峰值仍須實測。
- 操作開始時會停止 TTS，但不包含聲學回音消除。請等喇叭聲音結束再說話。

## 已驗證與待測

自動化測試不使用真實麥克風，也不變更系統權限。合成語音測試使用 Meijia 產生的中文 WAV，已實際通過 small 模型辨識，包含模型載入約 13.8 秒；這不是使用者聲音的準確率或速度保證。

真實麥克風權限授予、收音距離、噪音與個人口音，需要由使用者操作測試。可先說：「請幫我整理今天的工作重點」，確認結果再測專業詞與中英混合。

開發者可執行 `QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/smoke_dictation.py` 測試合成音訊。Metal GPU 在受限沙盒可能不可用，需在一般本機終端執行。
