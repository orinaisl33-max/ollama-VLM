"""Shared limits and product content; no Qt dependency."""

from dataclasses import dataclass

APP_TITLE = "人工智慧系統實驗室 · 展示工具"
BASE_URL = "http://127.0.0.1:11434"
MAX_PROMPT_CHARS = 4000
MAX_HISTORY_CHARS = 8000
MAX_HISTORY_TURNS = 3
MAX_ANSWER_CHARS = 32000
MAX_TRANSCRIPT_CHARS = 120000
IDLE_TIMEOUT_MS = 180000
TOTAL_TIMEOUT_MS = 600000


@dataclass(frozen=True)
class Model:
    label: str
    identifier: str
    note: str
    vision: bool = True
    official_url: str = ""
    grounding: bool = True


MODELS = (
    Model("均衡模式 · 2B", "qwen3.5:2b", "日常展示建議 · 文字與圖片理解"),
    Model("品質模式 · 4B", "qwen3.5:4b", "記憶體需求較高 · 8GB 請先實測"),
    Model("輕量模式 · 0.8B", "qwen3.5:0.8b", "適合簡單任務 · 以資源節省為優先"),
    Model("法國 Mistral · 3B", "ministral-3:3b", "Ministral 3 · 文字與圖片理解 · 8GB需觀察記憶體"),
    Model("Google Gemma · 4B", "gemma3:4b", "Gemma 3 · 文字與圖片理解 · 記憶體需求較高"),
    Model(
        "DeepSeek R1 · 1.5B · 純文字",
        "deepseek-r1:1.5b",
        "輕量蒸餾推理模型 · 僅文字，不支援圖片／AI 框選",
        vision=False,
    ),
    Model(
        "Qwen3-VL · 2B · 圖文",
        "qwen3-vl:2b-instruct",
        "輕量視覺語言模型 · Instruct 版 · 文字與靜態圖片理解",
    ),
    Model(
        "NVIDIA Nemotron · 4B · 純文字",
        "nemotron-3-nano:4b-q4_K_M",
        "NVIDIA Nemotron 3 Nano · Q4 量化 · 僅文字，不支援圖片／AI 框選",
        vision=False,
    ),
    Model(
        "LiquidAI VL · 450M · 圖文",
        "hf.co/LiquidAI/LFM2.5-VL-450M-GGUF:Q4_K_M",
        "超輕量圖文試驗選項 · 中文需核對 · AI 框請改用其他圖文模型",
        official_url="https://huggingface.co/LiquidAI/LFM2.5-VL-450M-GGUF",
        grounding=False,
    ),
)


def find_model(identifier: str) -> Model | None:
    return next((model for model in MODELS if model.identifier == identifier), None)


TEXT_SYSTEM_PROMPT = (
    "你是人工智慧系統實驗室的本機文字助理，預設使用繁體中文，直接、簡短地回答需求。"
    "可協助摘要、程式解說與文字推理；資訊不足時明確說明，不編造。"
    "目前選擇的模型僅支援文字，沒有圖片理解能力；如需看圖或 AI 建議框，"
    "請使用者切換到介面標示支援圖片的模型。"
    "本工具使用本機 Ollama，另有對話保存、草稿、Mac 語音輸入與本機朗讀。"
    "沒有執行使用者程式碼或代操作匯出按鈕；不宣稱已替使用者完成實際操作。"
)
SYSTEM_PROMPT = (
    "你是「人工智慧系統實驗室」展示工具的 AI 助理。預設使用繁體中文，專業且易懂。"
    "先回應需求。簡單問題只用一至兩句，不延伸例外或追問。複雜任務再以簡短條列補充。"
    "摘要保留事實、負責人與期限，缺漏資訊明確標示。程式解說包含邏輯與可確認的結果。"
    "圖片分析區分可見事實與推測，看不清楚就說明。不確定的資訊不可編造。計數要區分「種類」與「顆數」，列出幾類就只能總結幾類。遮擋或成串物件不給精確總數，改說至少可見多少或無法可靠計數。不可編造圖片沒有的容器、物件或顏色。"
    "本工具透過 127.0.0.1 的 Ollama 在使用者電腦執行推論，不是雲端服務。"
    "模型下載需要網路；聊天功能不會將問題或圖片送往雲端推論。"
    "支援文字與靜態圖片理解，可按「附加圖片」選取 PNG、JPEG 或 WebP。"
    "沒有附圖時應請使用者先附加圖片，不可宣稱本工具不支援圖片。"
    "圖片僅隨當次聊天提問傳送，後續需重新附加才能再次觀察。介面會暫存最近圖片供「框選／匯出」功能使用；新對話會清除。使用者要求框選時，請指引按「框選／匯出」，輸入搜尋目標後按「AI 建議框」，或手動拖曳畫框並匯出。AI 框為模型估計，需人工核對；聊天文字不會自動畫框，也沒有可靠信心分數。"
    "本工具有本機對話紀錄與草稿保存，可從側邊欄或對話紀錄開啟、搜尋、匯入或匯出文字。保存可關閉；圖片與框需另行明確開啟保存。回答以介面功能為準，不宣稱已替使用者操作按鈕或匯出檔案。"
    "本工具可用 macOS 本機語音朗讀，可選關閉、分段朗讀或完成後朗讀。Mac 可按麥克風輸入將語音轉文字，確認後再傳送。尚未支援影片或圖片生成。"
)


IMAGE_SYSTEM_PROMPT = (
    "你是人工智慧系統實驗室的視覺助理，使用繁體中文。只根據本次圖片回答，舊對話不是圖片證據。"
    "先直接回答使用者的圖片問題；詢問位置、顏色或文字時，明確回答對應內容。只有問數量時才用簡短表格：種類、清楚可見數量、不確定性。"
    "不要估算遮擋部分、不要推算總量或寫「共約」。成串或重疊而無法分辨者，數量填「無法可靠計數」。"
    "不要自行增加容器、顏色或物件。不同顏色的同類物件算同一種類；種類合計必須和列出的不同種類一致。"
    "先逐區檢查畫面，再回答；不確定就明確說明。回答簡短，不重複結語。"
    "使用者要求畫框時，請指引按介面的「框選／匯出」，使用 AI 建議框或人工框選；AI 框需要核對。"
)


def build_messages(
    history: list[dict], prompt: str, image: str | None, *, model=None
) -> list[dict]:
    """Send complete recent pairs, bounded by characters (not an exact token count)."""
    configuration = find_model(model)
    if configuration is not None and not configuration.vision and image:
        raise ValueError("所選模型僅支援文字，請切換圖文模型後再附圖。")
    base_prompt = (
        TEXT_SYSTEM_PROMPT
        if configuration is not None and not configuration.vision
        else SYSTEM_PROMPT
    )
    system = (IMAGE_SYSTEM_PROMPT if image else base_prompt) + (
        "本次已附加圖片，請直接觀察後回答。" if image else "本次沒有附加圖片，不可宣稱已看到圖片。"
    )
    if configuration is not None and configuration.vision and not configuration.grounding:
        system += "目前模型可看圖聊天，但本工具未啟用此模型的 AI 建議框；可手動畫框與匯出，AI 定位請切換 Qwen 圖文模型。"
    selected: list[dict] = []
    budget = MAX_HISTORY_CHARS - len(prompt)
    # New images are independent evidence: do not reuse unverified older visual claims.
    visual_history = [] if image else history
    for index in range(len(visual_history) - 2, -1, -2):
        pair = visual_history[index : index + 2]
        size = sum(len(item["content"]) for item in pair)
        if size > budget or len(selected) >= MAX_HISTORY_TURNS * 2:
            break
        selected[0:0] = [dict(item) for item in pair]
        budget -= size
    user = {"role": "user", "content": prompt}
    if image:
        user["images"] = [image]
    return [{"role": "system", "content": system}, *selected, user]


def retain_turn(history: list[dict], prompt: str, answer: str) -> list[dict]:
    """Keep complete pairs only; never keep image data in conversation history."""
    result = history + [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": answer},
    ]
    while result and (
        len(result) > MAX_HISTORY_TURNS * 2
        or sum(len(item["content"]) for item in result) > MAX_HISTORY_CHARS
    ):
        del result[:2]
    return result
