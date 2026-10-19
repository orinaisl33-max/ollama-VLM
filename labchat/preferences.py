"""Small, validated UI preferences; never commands, paths or recording permissions."""

from .config import MODELS

DEFAULTS = {
    "appearance": "light",
    "model": MODELS[0].identifier,
    "voice": "",
    "speech_mode": "off",
    "speech_rate": 175,
    "microphone": "",
}


def validate_preferences(value):
    if not isinstance(value, dict) or not set(value) <= set(DEFAULTS):
        raise ValueError("Invalid preference fields")
    result = {**DEFAULTS, **value}
    if (
        result["appearance"] not in ("light", "dark")
        or result["model"] not in {model.identifier for model in MODELS}
        or result["speech_mode"] not in ("off", "stream", "complete")
        or type(result["speech_rate"]) is not int
        or result["speech_rate"] not in (145, 175, 205, 235)
    ):
        raise ValueError("Invalid preference value")
    voice = result["voice"]
    if not isinstance(voice, str) or len(voice) > 200 or any(ord(c) < 32 for c in voice):
        raise ValueError("Invalid voice preference")
    microphone = result["microphone"]
    if (
        not isinstance(microphone, str)
        or len(microphone) > 1024
        or len(microphone) % 2
        or any(c not in "0123456789abcdef" for c in microphone)
    ):
        raise ValueError("Invalid microphone identifier")
    return result
