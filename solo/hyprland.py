"""Read resolved compositor options, never Lua source or theme files."""

import json
import math
import re
import subprocess

OPTIONS = (
    "general:gaps_out", "decoration:rounding", "general:border_size",
    "general:col.active_border", "decoration:shadow:enabled",
    "decoration:shadow:range", "decoration:shadow:color", "decoration:shadow:offset",
)


def _number(value, maximum=1000):
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError("invalid compositor dimension")
    return value


def _gradient(value):
    tokens = value.split()
    angle = float(tokens.pop()[:-3]) if tokens and tokens[-1].endswith("deg") else 0
    if not math.isfinite(angle) or not tokens or not all(re.fullmatch(r"[0-9a-fA-F]{8}", token) for token in tokens):
        raise ValueError("invalid compositor colour")
    return {"colors": ["#" + token for token in tokens], "angle": angle, "enabled": len(tokens) > 1}


def decode_appearance(output):
    # hyprctl --batch -j emits adjacent JSON objects, not a JSON array.
    decoder = json.JSONDecoder()
    values = {}
    remaining = output.strip()
    while remaining:
        value, end = decoder.raw_decode(remaining)
        values[value["option"]] = value
        remaining = remaining[end:].strip()
    gaps = [_number(float(part)) for part in values[OPTIONS[0]]["css"].split()]
    if len(gaps) == 1:
        gaps *= 4
    elif len(gaps) == 2:
        gaps *= 2
    elif len(gaps) == 3:
        gaps.append(gaps[1])
    if len(gaps) != 4:
        raise ValueError("invalid compositor gaps")
    border = _gradient(values[OPTIONS[3]]["gradient"])
    offset = values[OPTIONS[7]]["vec2"]
    if len(offset) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1000 for v in offset):
        raise ValueError("invalid shadow offset")
    enabled = values[OPTIONS[4]]["bool"]
    if type(enabled) is not bool:
        raise ValueError("invalid shadow state")
    return {
        "available": True,
        "gaps": dict(zip(("top", "right", "bottom", "left"), gaps)),
        "rounding": _number(values[OPTIONS[1]]["int"]),
        "border_width": _number(values[OPTIONS[2]]["int"]),
        "border": border,
        "shadow": {"enabled": enabled, "range": _number(values[OPTIONS[5]]["int"]),
                   "color": _gradient(values[OPTIONS[6]]["gradient"])["colors"][0], "offset": offset},
    }


def appearance():
    try:
        result = subprocess.run(["hyprctl", "--batch", "-j", "; ".join("getoption " + key for key in OPTIONS)],
                                capture_output=True, text=True, timeout=3, check=True)
        return decode_appearance(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError, IndexError):
        return {"available": False, "error": "Hyprland appearance unavailable. Using shell appearance until the next reload or open."}
