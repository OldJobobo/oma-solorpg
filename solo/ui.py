"""Player-owned Book and Table appearance; Settings always uses the Table scale."""

import fcntl
import json
import os
import tempfile

from . import SoloError
from .library import state_home

SCALES = (1, 1.25, 1.5, 1.75, 2)


def _valid(scale):
    return type(scale) in (int, float) and scale in SCALES


def settings():
    try:
        saved = json.loads((state_home() / "ui.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    # The original shared scale becomes the starting value for both surfaces.
    # A scoped choice then takes precedence, without resetting the other one.
    legacy = saved.get("scale", 1)
    result = {}
    for key in ("book_scale", "table_scale"):
        value = saved.get(key, legacy)
        result[key] = value if _valid(value) else 1
    result["honor_hyprland"] = saved.get("honor_hyprland") is True
    return result


def set_scale(scale):
    """Compatibility for the original explicit CLI option: set both scales."""
    if not _valid(scale):
        raise SoloError("scale must be 1, 1.25, 1.5, 1.75 or 2")
    return set_scales(book_scale=scale, table_scale=scale)


def set_scales(book_scale=None, table_scale=None, honor_hyprland=None):
    changes = {key: value for key, value in (("book_scale", book_scale), ("table_scale", table_scale)) if value is not None}
    for value in changes.values():
        if not _valid(value):
            raise SoloError("scale must be 1, 1.25, 1.5, 1.75 or 2")
    if honor_hyprland is not None:
        if type(honor_hyprland) is not bool:
            raise SoloError("honor_hyprland must be a boolean")
        changes["honor_hyprland"] = honor_hyprland
    if not changes:
        return settings()
    path = state_home() / "ui.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # A Book click and a Table/CLI edit may arrive together. Serialize the
    # read-modify-write so neither can replace the other surface's preference.
    with path.with_suffix(".lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = {**settings(), **changes}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
                temporary = stream.name
                json.dump(now, stream)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)
    return now
