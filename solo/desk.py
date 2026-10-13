"""Desktop effects while a game is on: the Omarchy desktop joins the table.

- Borders: a Dragon flashes the window borders gold, a Demon red, and they stay a dark
  red while the hero is dying (Hyprland, through `hyprctl eval`).
- Screen: the whole screen answers too, through a Hyprland screen shader (shaders/). A
  Dragon floods it with gold, a Demon drains it and closes in red, a blow jolts it, an
  omen ripples it cold; while the hero is dying a dark red rim closes in, and when they
  die the screen goes grey for a while.
- Sound: the table's sounds (sounds.py), for the plugin to play.
- Candlelight: the screen warms while the Book is open (hyprsunset, as Omarchy's night
  light does), and goes back to what it was when it closes.
- Omens: what a hidden clock stirs up arrives as a desktop notification.
- Screensaver: while the Book is open, Omarchy's screensaver shows the hero's portrait
  and the GM's last words instead of the logo.

Every change keeps what it replaced in a runtime folder and puts it back exactly: the
border colours, the player's own screen shader, the screen temperature, the screensaver
text. When the original can't be read, the effect is skipped rather than guessed. `solo
desk restore` puts everything back (the plugin runs it when the Book closes and when it
loads). Each effect can be switched off in the table settings (fx.json). Nothing here
touches a campaign.
"""

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import textwrap
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import SoloError, library, sounds

EFFECTS = ("borders", "screen", "sound", "candle", "omens", "screensaver")
COLOURS = {"dragon": "rgba(e8b923ff)", "demon": "rgba(d62828ff)", "dying": "rgba(7a0c0cff)"}
# A flash: the border colour (if any), and how the screen rises, holds and falls, in seconds.
FLASHES = {
    "dragon": ("dragon", 0.1, 0.1, 1.3),
    "demon": ("demon", 0.1, 0.15, 1.4),
    "hit": (None, 0.0, 0.05, 0.55),
}
OMEN = (0.7, 1.6, 1.4)
DEATH = (1.6, 6.0, 2.4)
SHADERS = Path(__file__).with_name("shaders")
STEP = 0.07      # seconds between the steps of a moment on the screen
PACE = 1.0       # scales every wait (the tests set it to 0)
CANDLE = 3400
GLYPH = "\U000F1155"  # Nerd Font md-dice_d20, as in the bar
SCREENSAVER = Path.home() / ".config/omarchy/branding/screensaver.txt"


def settings():
    """Which effects are on (all of them unless the player switched one off)."""
    try:
        saved = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    return {name: bool(saved.get(name, True)) for name in EFFECTS}


def set_settings(changes):
    now = settings()
    for name, on in changes.items():
        if name not in EFFECTS:
            raise SoloError(f"no effect {name!r}; effects: {', '.join(EFFECTS)}")
        now[name] = bool(on)
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(now, indent=1) + "\n", encoding="utf-8")
    for name in EFFECTS:
        if not now[name]:
            _undo(name)
    return now


# Flashes ------------------------------------------------------------------------------

def flash(kind):
    """A Dragon, a Demon or a blow: the borders flash (Dragons gold, Demons red) and the
    screen floods, jolts or drains, then everything goes back to what it was (or to the
    dying red, if that is held)."""
    if kind not in FLASHES:
        raise SoloError(f"no flash {kind!r}; flashes: {', '.join(FLASHES)}")
    colour, rise, hold, fall = FLASHES[kind]
    on = settings()
    border = bool(colour) and on["borders"] and _border_begin(COLOURS[colour])
    screen = _screen_begin() if on["screen"] else None
    if not border and not screen:
        return False
    for level, seconds in _steps(rise, hold, fall):
        if screen and not _screen_step(screen, kind, level=level):
            screen = None
        _wait(seconds)
    if border:
        _border_end()
    if screen:
        _screen_end(screen)
    return True


def dying(on, failures=0):
    """While the hero is dying the borders hold a dark red and a red rim closes round the
    screen, further with every failed death roll; `off` puts it all back."""
    now = settings()
    changed = False
    with _lock():
        if on and now["borders"]:
            original = _saved("border") or _border_now()
            if original is not None:
                _save("border", original)
                _save("border.hold", "dying")
                _set_border(COLOURS["dying"])
                changed = True
        elif not on:
            _forget("border.hold")
            changed = _restore_border()
        if on and now["screen"]:
            if _saved("shader") is None and (own := _shader_now()) is not None:
                _save("shader", own)
            if _saved("shader") is not None:
                _save("shader.hold", {"weak": min(1.0, 0.4 * max(0, int(failures)))})
                if _saved("shader.owner") is None:  # a flash under way puts the hold up when it ends
                    _settle_screen()
                changed = True
        elif not on:
            _forget("shader.hold")
            if _saved("shader.owner") is None:
                changed = _restore_shader() or changed
    return changed


def death():
    """The hero is dead: the dying red lets go, and the screen fades to grey and cold,
    stays so a while, and comes back."""
    with _lock():
        _forget("border.hold")
        _restore_border()
        _forget("shader.hold")
        if not settings()["screen"]:
            if _saved("shader.owner") is None:
                _restore_shader()
            return False
    screen = _screen_begin()
    if screen is None:
        return False
    for level, seconds in _steps(*DEATH):
        if not _screen_step(screen, "death", level=level):
            return True  # something newer has the screen now
        _wait(seconds)
    _screen_end(screen)
    return True


# Borders ------------------------------------------------------------------------------

def _border_begin(colour):
    with _lock():
        original = _saved("border") or _border_now()
        if original is None:
            return False
        _save("border", original)
        _set_border(colour)
    return True


def _border_end():
    with _lock():
        held = _saved("border.hold")
        if held:
            _set_border(COLOURS[held])
        else:
            _restore_border()


def _border_now():
    """The active border as Hyprland reports it: {"colors": [...], "angle": n}, or None
    when it can't be read (then nothing gets changed)."""
    if not shutil.which("hyprctl"):
        return None
    out = _run(["hyprctl", "getoption", "general:col.active_border", "-j"])
    try:
        custom = json.loads(out or "").get("custom", "")
    except (ValueError, AttributeError):
        return None
    colours = [f"rgba({c[2:]}{c[:2]})" for c in re.findall(r"\b([0-9a-fA-F]{8})\b", custom)]
    angle = re.search(r"(\d+)deg", custom)
    if len(colours) == 1 and colours[0].lower() in COLOURS.values():
        return None  # one of ours, left by an effect that couldn't put the border back: never the player's
    return {"colors": colours, "angle": int(angle.group(1)) if angle else 0} if colours else None


def _set_border(colour):
    _apply_border({"colors": [colour], "angle": 0})


def _apply_border(border):
    """Whether Hyprland took the border."""
    colours = ", ".join(f'"{c}"' for c in border["colors"])
    value = f'"{border["colors"][0]}"' if len(border["colors"]) == 1 else f'{{ colors = {{ {colours} }}, angle = {int(border.get("angle", 0))} }}'
    lua = f"hl.config({{ general = {{ col = {{ active_border = {value} }} }} }})"
    if _run(["hyprctl", "eval", lua]) is not None:
        return True
    # Hyprland from before the Lua config.
    angle = f" {int(border.get('angle', 0))}deg" if len(border["colors"]) > 1 else ""
    return _run(["hyprctl", "keyword", "general:col.active_border", " ".join(border["colors"]) + angle]) is not None


def _restore_border():
    """Put the player's border back. What was saved is forgotten only once it is back: when hyprctl
    fails, the next restore tries again, and nothing takes the effect's colour for the player's."""
    original = _saved("border")
    if original and _apply_border(original):
        _forget("border")
        return True
    return False


# The screen ----------------------------------------------------------------------------
#
# A moment on the screen (a flash, an omen, a death) takes it with a token, bakes its
# shader at each step and puts it up, then hands the screen back. A newer moment takes
# the token over and the older one stops where it is, leaving the newer one to hand back.
# What the screen goes back to is the dying rim when that is held, or else the player's
# own shader (or none), saved before the first change.

def _screen_begin():
    with _lock():
        if _saved("shader") is None:
            original = _shader_now()
            if original is None:
                return None
            _save("shader", original)
        token = uuid.uuid4().hex
        _save("shader.owner", token)
    return token


def _screen_step(token, name, **values):
    with _lock():
        if _saved("shader.owner") != token:
            return False
        _set_shader(_bake(name, **values))
    return True


def _screen_end(token):
    with _lock():
        if _saved("shader.owner") == token:
            _forget("shader.owner")
            _settle_screen()


def _settle_screen():
    held = _saved("shader.hold")
    if held:
        _set_shader(_bake("dying", weak=held["weak"]))
    else:
        _restore_shader()


def _restore_shader():
    original = _saved("shader")
    if original is not None:
        _set_shader(original["path"])
        _forget("shader")
    return original is not None


def _steps(rise, hold, fall):
    """(level, seconds) for each step of a moment: up to 1 over `rise`, held for `hold`,
    then easing back toward nothing over `fall`."""
    ups = max(1, round(rise / STEP))
    steps = [(round(((i + 1) / ups) ** 0.7, 2), rise / ups or STEP) for i in range(ups)]
    steps[-1] = (1.0, steps[-1][1] + hold)
    downs = max(2, round(fall / STEP))
    steps += [(round((1 - i / downs) ** 1.8, 2), fall / downs) for i in range(1, downs)]
    return steps


def _bake(name, **values):
    """The shader with its values written in, as a file of its own (a new path each time
    the values change, so Hyprland loads it afresh)."""
    source = (SHADERS / f"{name}.frag").read_text(encoding="utf-8")
    for key, value in values.items():
        source = source.replace("{{" + key + "}}", f"{float(value):.3f}")
    folder = _runtime() / "shaders"
    folder.mkdir(exist_ok=True)
    path = folder / f"{name}-{hashlib.sha1(source.encode()).hexdigest()[:12]}.frag"
    if not path.exists():
        path.write_text(source, encoding="utf-8")
    return str(path)


def _shader_now():
    """The player's own screen shader as Hyprland reports it: {"path": ...} ("" for none),
    or None when it can't be read (then the screen is left alone)."""
    if not shutil.which("hyprctl"):
        return None
    try:
        option = json.loads(_run(["hyprctl", "getoption", "decoration:screen_shader", "-j"]) or "")
        path = str(option.get("str", option.get("value", ""))).strip()
    except (ValueError, AttributeError):
        return None
    if path == "[[EMPTY]]" or path.startswith(str(_runtime() / "shaders")):
        path = ""  # none, or one of ours left behind by a moment that never finished
    return {"path": path}


def _set_shader(path):
    lua = f"hl.config({{ decoration = {{ screen_shader = {_lua_string(path)} }} }})"
    if _run(["hyprctl", "eval", lua]) is None:
        # Hyprland from before the Lua config.
        _run(["hyprctl", "keyword", "decoration:screen_shader", path or "[[EMPTY]]"])


def _lua_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


# Sound ----------------------------------------------------------------------------------

def sound(name):
    """Play one of the table's sounds, if sound is on."""
    if name not in sounds.RECIPES:
        raise SoloError(f"no sound {name!r}; sounds: {', '.join(sounds.names())}")
    return settings()["sound"] and sounds.play(name)


def sound_kit():
    """Every sound made ready, and how to play them: {"play": command or None, "sounds":
    {name: path}}. The plugin plays them itself, so they land exactly with the Book."""
    return {"play": sounds.player(), "sounds": {name: str(sounds.path(name)) for name in sounds.names()}}


# Candlelight ----------------------------------------------------------------------------

def candle(on):
    """Warm the screen while the Book is open, like Omarchy's night light, and put the
    temperature back afterwards. Only when hyprsunset is running."""
    with _lock():
        if on and settings()["candle"]:
            now = _temperature()
            if now is None:
                return False
            if _saved("temperature") is None:
                _save("temperature", now)
            _run(["hyprctl", "hyprsunset", "temperature", str(min(now, CANDLE))])
        else:
            original = _saved("temperature")
            if original is None:
                return False
            _run(["hyprctl", "hyprsunset", "temperature", str(original)])
            _forget("temperature")
    if shutil.which("omarchy-shell"):
        _run(["omarchy-shell", "-q", "nightlight", "refresh"])
    return True


def _temperature():
    out = _run(["hyprctl", "hyprsunset", "temperature"]) if shutil.which("hyprctl") else None
    found = re.search(r"\d+", out or "")
    return int(found.group()) if found else None


# Notifications ----------------------------------------------------------------------------

def omen(text):
    """Something the hidden clock stirred up, felt on the desktop: a notification, and the
    screen ripples cold for a moment."""
    now = settings()
    told = now["omens"] and notify("An omen", text)
    screen = _screen_begin() if now["screen"] else None
    if screen:
        phase = 0.0
        for level, seconds in _steps(*OMEN):
            if not _screen_step(screen, "omen", level=level, phase=phase):
                return told
            _wait(seconds)
            phase += seconds
        _screen_end(screen)
    return told or bool(screen)


def notify(title, text):
    """A desktop notification. The text can be a pack's (an omen's words), and must never be taken for an
    option: notify-send (GLib) stops reading options at "--"; omarchy-notification-send has no such mark
    and knows its options by their exact names, so text that starts with a dash gets a zero-width space first."""
    if shutil.which("omarchy-notification-send"):
        text = f"​{text}" if text.startswith("-") else text
        return _run(["omarchy-notification-send", "--app-name", "oma-solorpg", "-g", GLYPH, title, text]) is not None
    elif shutil.which("notify-send"):
        return _run(["notify-send", "--app-name", "oma-solorpg", "--", title, text]) is not None
    return False


# Screensaver --------------------------------------------------------------------------------

def screensaver(on, root=None):
    """While on, the screensaver shows the hero and the GM's last words. The player's own
    screensaver text is kept beside it and put back when it goes off."""
    backup = SCREENSAVER.with_name(SCREENSAVER.name + ".solo-play")
    if on and settings()["screensaver"] and root and SCREENSAVER.parent.is_dir():
        try:
            state = json.loads((Path(root) / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not backup.exists():
            if SCREENSAVER.exists():
                shutil.copy2(SCREENSAVER, backup)
            else:
                backup.write_text("", encoding="utf-8")
        SCREENSAVER.write_text(screensaver_text(state), encoding="utf-8")
        return True
    elif backup.exists():
        if backup.stat().st_size:
            os.replace(backup, SCREENSAVER)
        else:
            SCREENSAVER.unlink(missing_ok=True)
            backup.unlink()
        return True
    return False


def screensaver_text(state):
    pc = state.get("pc") or {}
    lines = list((state.get("portrait") or {}).get("lines") or [])
    lines += ["", pc.get("name", ""), state.get("scene_title") or ""]
    said = (state.get("last_said") or {}).get("text", "")
    first = next((p.strip() for p in said.split("\n\n") if p.strip()), "")
    if first:
        lines += [""] + textwrap.wrap(" ".join(first.split()), 60)[:4]
    return "\n".join(lines).rstrip() + "\n"


# Putting it all back ------------------------------------------------------------------------

def restore():
    """Undo every effect still in place: borders, screen, candlelight, screensaver."""
    return {name: _undo(name) for name in ("borders", "screen", "candle", "screensaver")}


def _undo(name):
    if name == "borders":
        with _lock():
            _forget("border.hold")
            return _restore_border()
    elif name == "screen":
        with _lock():
            _forget("shader.owner")
            _forget("shader.hold")
            return _restore_shader()
    elif name == "candle":
        return candle(False)
    elif name == "screensaver":
        return screensaver(False)
    return False


# Plumbing --------------------------------------------------------------------------------

def _settings_path():
    return library.state_home() / "fx.json"


def _runtime():
    base = os.environ.get("XDG_RUNTIME_DIR")
    folder = Path(base) / "solo-play" if base else library.state_home() / "runtime"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@contextmanager
def _lock():
    with open(_runtime() / "desk.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _saved(key):
    try:
        return json.loads((_runtime() / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(key, value):
    (_runtime() / f"{key}.json").write_text(json.dumps(value), encoding="utf-8")


def _forget(key):
    (_runtime() / f"{key}.json").unlink(missing_ok=True)


def _wait(seconds):
    time.sleep(seconds * PACE)


def _run(command):
    """stdout of a desktop command, or None when it's missing or fails. Effects never
    raise: a game goes on without them."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None
