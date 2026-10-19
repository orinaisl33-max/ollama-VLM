"""Validated UTC epoch timestamps; presentation uses the computer's local clock."""

import math
from datetime import datetime


def validate_timestamp(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not 0 <= value <= 4102444800 or not math.isfinite(value):
        raise ValueError("Invalid timestamp")
    return float(value)


def clock_label(value):
    value = validate_timestamp(value)
    return datetime.fromtimestamp(value).strftime("%H:%M") if value is not None else ""
