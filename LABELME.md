# Labelme 匯出與新增視覺模型

本輪新增兩個本機模型選項：

| 介面名稱 | Ollama標籤 | 能力 |
| --- | --- | --- |
| 法國 Mistral · 3B | `ministral-3:3b` | Ministral 3文字與圖片理解 |
| Google Gemma · 4B | `gemma3:4b` | Gemma 3文字與圖片理解 |

預設仍保留原均衡模式，不會自動切換或同時呼叫多個模型。介面按「檢查服務」後依本機回傳顯示安裝狀態；模型下載不包含在來源ZIP。M2／8GB使用4096context起點，一次一個模型，記憶體用量大於下載檔大小；速度與辨識品質需實際比較。

其他電腦如需要這兩個選項，安裝Ollama後另外執行：

```sh
ollama pull ministral-3:3b
ollama pull gemma3:4b
```

## 在本工具匯出 Labelme

1. 附加圖片並開啟「檢視／框選」。
2. 取得AI建議框或手動標註，核對名稱、漏框及位置；可移動／縮放修正。
3. 按「匯出 Labelme JSON」，選擇保存位置。
4. 在Labelme使用Open開啟該JSON，即可查看圖片與矩形並繼續標註。

**JSON內嵌的是未畫框的前處理PNG，不需要原機圖片路徑。最長邊最多1024像素，並非原始高解析圖片。** 像素座標與imageWidth／imageHeight都對應這張內嵌圖片。請勿手動改成原圖尺寸，否則框會錯位。

## 格式與來源資訊

- `version`：格式相容性驗證目標7.8.1；本工具執行時不需要安裝Labelme。
- `flags`：圖片層級旗標物件。
- `shapes`：每個框為一個`shape_type: "rectangle"`，`points`為左上／右下兩個像素座標點，允許小數。不是本工具原本0–1000的正規化座標。
- 每個shape包含`label`、`group_id: null`、`description`、`flags`、`mask: null`。
- `flags.ai_suggested`標記是否仍為AI建議框。人工移動或改名後依本工具現有規則標為人工，這個旗標不是準確率或信心分數。
- `imagePath`只使用匯出JSON同名的PNG基本檔名，不含原始私人絕對路徑。
- `imageData`是未畫框PNG的base64；`imageHeight`／`imageWidth`與實際內容一致。JSON本身包含圖片內容，請當作含私人圖片的檔案管理；未加密。

例如400×200圖片上的正規化框[100,200,800,700]會轉為points[[40.0,40.0],[320.0,140.0]]，而非直接把原正規化數字填進Labelme。

## 與其他匯出按鈕的差別

| 按鈕 | 內容 | 用途 |
| --- | --- | --- |
| 匯出標註PNG | 已畫上框與標籤的圖片 | 分享視覺結果 |
| 匯出專案JSON | 本工具0–1000座標、來源及圖片雜湊，沒有內嵌圖 | 由本工具「匯入專案JSON」恢復框 |
| 匯出Labelme JSON | 內嵌無框圖片、Labelme矩形像素座標 | 在Labelme開啟繼續標註 |

本工具目前的匯入按鈕只接受專案JSON，**不接受Labelme JSON**。若其他資料集工具要求獨立PNG檔，需要從內嵌imageData另行取出原始無框圖片，不能把已畫框的展示PNG當作乾淨訓練影像。此次匯出不自動建立第二張PNG，避免圖片／JSON版本不一致或覆寫原圖。

## 驗證與限制

匯出前驗證圖片PNG內容、尺寸、容量、名稱、矩形範圍與來源；寫入使用QSaveFile原子替換。空框清單可匯出，供Labelme進一步手動標註。AI結果需人工核對，換模型不代表定位或事件判斷一定正確。

Labelme的官方讀檔實作及公開模型頁為核對依據；本機驗證結果另記在QUALITY.md。Labelme7.8.1需要Python3.12以上，但**這不改變本專案的Python3.11環境**；相容性驗證在獨立暫存環境進行，無新增正式執行相依。

- [Labelme官方JSON讀檔程式](https://github.com/labelmeai/labelme/blob/main/labelme/_label_file.py)
- [Ministral 3 3B](https://ollama.com/library/ministral-3:3b)
- [Gemma 3 4B](https://ollama.com/library/gemma3:4b)

本輪依使用者指示不重新打包。既有Mac／Windows來源ZIP不含本次更新；新增模型的權重也不會被放進來源包。
