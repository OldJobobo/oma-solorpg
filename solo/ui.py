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
    font = saved.get("book_serif_font", "")
    result["book_serif_font"] = font if isinstance(font, str) and len(font) <= 256 and not any(ord(c) < 32 for c in font) else ""
    return result


def set_scale(scale):
    """Compatibility for the original explicit CLI option: set both scales."""
    if not _valid(scale):
        raise SoloError("scale must be 1, 1.25, 1.5, 1.75 or 2")
    return set_scales(book_scale=scale, table_scale=scale)


def set_scales(book_scale=None, table_scale=None, book_serif_font=None):
    changes = {key: value for key, value in (("book_scale", book_scale), ("table_scale", table_scale)) if value is not None}
    for value in changes.values():
        if not _valid(value):
            raise SoloError("scale must be 1, 1.25, 1.5, 1.75 or 2")
    if book_serif_font is not None:
        if not isinstance(book_serif_font, str) or len(book_serif_font) > 256 or any(ord(c) < 32 for c in book_serif_font):
            raise SoloError("Book serif font must be an installed serif family, or empty for system default")
        if book_serif_font:
            from .fonts import serif_fonts
            if book_serif_font not in serif_fonts():
                raise SoloError("Book serif font is not an installed reading serif. Reopen Settings to refresh the list.")
        changes["book_serif_font"] = book_serif_font
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
