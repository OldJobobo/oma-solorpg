"""Where things live.

Bundled content ships in the repository, which is also the plugin folder: system packs in
packs/, playable adventures in examples/. The player's own packs and every campaign live
under SOLO_HOME (default ~/Games/solo), outside the repository, so packs built from books
they bought never get published with it. A name found in SOLO_HOME hides a bundled one.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from . import SoloError, creation, packs

REPO = Path(__file__).resolve().parent.parent

# kind: (folder under SOLO_HOME, folder in the repository, files that mark a pack)
_KINDS = {
    "system": ("systems", "packs", ("system.toml",)),
    "adventure": ("adventures", "examples", ("adventure.toml", "scenes.json")),
}


def home():
    return Path(os.environ.get("SOLO_HOME") or Path.home() / "Games" / "solo").expanduser()


def outside_repository(path, default=None):
    """`path`, whole, for an importer to write a book's pack, table or text into: never the repository, which is published
    and holds no book (NOTICE.md). `default` is where it goes when the player names nowhere, for the error to say."""
    path = Path(path).expanduser().resolve()
    if path == REPO or REPO in path.parents:
        raise SoloError(f"{path} is inside the repository: a book's text stays out of it" + (f" (the default is {default})" if default else ""))
    return path


def state_home():
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "solo"


def current():
    """The current campaign folder recorded by `solo new`, `use` and `play`, if it still exists."""
    pointer = state_home() / "current"
    path = Path(pointer.read_text(encoding="utf-8").strip()) if pointer.exists() else None
    return path if path and (path / "campaign.toml").exists() else None


def find_system(name):
    return _find("system", name)


def find_adventure(name):
    return _find("adventure", name)


def only(kind):
    """The one pack of this kind, for commands where the player didn't name one."""
    entries = _entries(kind)
    if len(entries) == 1:
        return entries[0]
    else:
        names = ", ".join(p.name for p in entries) or "none"
        raise SoloError(f"which {kind}? available: {names}")


def new_campaign_dir(adventure_id, hero):
    """~/Games/solo/campaigns/<adventure>-<hero>, with -2, -3 ... when that is taken."""
    base = packs.slug(f"{adventure_id} {hero}").replace("_", "-") or "campaign"
    root = home() / "campaigns" / base
    number = 2
    while root.exists():
        root = root.with_name(f"{base}-{number}")
        number += 1
    return root


def listing():
    """Everything the panel's Home and New adventure screens show. A pack that doesn't load
    (one half-built from a book) is left out and said why under `problems`, so it never
    takes the rest of the library down with it. Each adventure says whether a campaign can
    begin on it (`ready`), why not (`why`, a sentence) and the name of the system it plays
    on (`system_name`), which a pack of names only has before its rules are built."""
    systems, problems = [], []
    # {system id: (its name, or None when it doesn't load; why nothing can begin on it, or "")}
    rules = {}
    for path in _entries("system"):
        try:
            system = packs.load_system(path)
            gaps = packs.missing(system)
            unreadable = packs.format_problems(packs.declared_formats(system))
            if unreadable:
                # Written for a newer engine than this one: not offered, and the player is told to update.
                problems.append(f"system {path.name}: {unreadable[0]}")
                rules[packs.slug(path.name)] = (system["name"], f"This engine can't read the rules it plays on: {unreadable[0]}.")
                continue
            if gaps:
                # Only a game's names so far: nothing can be played on it until the book's rules are built.
                problems.append(f"system {path.name}: " + packs.missing_text(system, gaps))
                rules[packs.slug(path.name)] = (system["name"], packs.missing_text(system, gaps) + ".")
                continue
            systems.append({
                "id": path.name,
                "name": system["name"],
                "family": system["family"],
                "path": str(path),
                "creation": creation.tables(system),
                "characters": [
                    {"id": cid, "name": sheet.get("name", cid), "info": ", ".join(map(str, sheet.get("info", {}).values()))}
                    for cid, sheet in system["characters"].items()
                ],
            })
            rules[packs.slug(path.name)] = (system["name"], "")
        except SoloError as error:
            problems.append(f"system {path.name}: {error}")
            rules[packs.slug(path.name)] = (None, f"The system pack it plays on, {path.name}, doesn't load: {error}")
    adventures = []
    for path in _entries("adventure"):
        try:
            spec = packs.load_data(path / "adventure.toml") if (path / "adventure.toml").exists() else {}
            premade = packs._load_folder(path / "characters")
        except SoloError as error:
            problems.append(f"adventure {path.name}: {error}")
            continue
        unreadable = packs.format_problems([(f"{path.name}/adventure.toml", spec.get("format"))])
        if unreadable:
            problems.append(f"adventure {path.name}: {unreadable[0]}")
            continue
        if spec.get("draft"):
            # A campaign an agent is still writing (make campaign): not ready to begin.
            problems.append(f"adventure {path.name}: still being written (draft = true in adventure.toml)")
            continue
        named = spec.get("system")
        system_name, why = (rules.get(packs.slug(named), (None, f"It plays on {named}, and there is no system pack by that name.")) if named
                            else (None, "It doesn't say which system it plays on (system = \"...\" in its adventure.toml)."))
        adventures.append({
            "id": path.name,
            "title": spec.get("title", path.name),
            "system": named,
            "summary": spec.get("summary", ""),
            "path": str(path),
            # Heroes written for this adventure (a pre-generated party), offered before the system's.
            "characters": [{"id": cid, "name": sheet.get("name", cid), "info": ", ".join(map(str, sheet.get("info", {}).values()))}
                           for cid, sheet in premade.items() if not sheet.get("replacement")],
            # Whether a campaign can begin on it, and a sentence saying why not: the rules it plays on aren't built from the player's books yet.
            "ready": not why,
            "why": why,
            "system_name": system_name,
        })
    now = current()
    folders = sorted(p for p in (home() / "campaigns").glob("*") if (p / "campaign.toml").exists())
    if now is not None and now not in folders:
        folders.append(now)
    campaigns = sorted((_campaign_card(p, now) for p in folders), key=lambda c: c["played"], reverse=True)
    # The Hall of the Fallen: every hero who died, with their last words.
    fallen = [f for c in campaigns for f in c.get("fallen") or []]
    return {"home": str(home()), "current": str(now) if now else None,
            "systems": systems, "adventures": adventures, "campaigns": [{k: v for k, v in c.items() if k != "fallen"} for c in campaigns],
            "fallen": fallen, "problems": problems}


def _campaign_card(root, now):
    try:
        state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):  # unreadable, not UTF-8, or not JSON
        state = {}
    pc = state.get("pc") or {}
    said = (state.get("last_said") or {}).get("text", "")
    log = root / "events.jsonl"
    played = datetime.fromtimestamp(log.stat().st_mtime).isoformat(timespec="minutes") if log.exists() else ""
    try:
        title = packs.load_data(root / "campaign.toml").get("title", root.name)
    except SoloError:  # a damaged campaign.toml still lists, by its folder, so it can be deleted
        title = root.name
    return {
        "path": str(root),
        "title": title,
        "hero": pc.get("name", ""),
        "info": ", ".join(map(str, pc.get("info", {}).values())),
        "scene": state.get("scene_title") or "",
        # The first line of the GM's last words, so the list shows where each game stopped.
        "said": next((line.strip() for line in said.splitlines() if line.strip()), ""),
        "played": played,
        "current": root == now,
        # How it ended (the hero died, or the GM closed the adventure), or empty while it's going.
        "ended": (state.get("ended") or {}).get("text", ""),
        "dead": bool(pc.get("dead")),
        "fallen": _earlier(root, state) + ([_fallen(root, state)] if pc.get("dead") and state.get("fallen") else []),
    }


def _earlier(root, state):
    """Heroes who died earlier in a story someone else carried on."""
    return [
        {"path": str(root), "name": h["name"], "info": ", ".join(map(str, h.get("info", {}).values())),
         "adventure": state.get("title", ""), "scene": h["fallen"].get("scene") or "", "by": h["fallen"].get("by") or "",
         "epitaph": h["fallen"].get("epitaph") or "", "at": (h["fallen"].get("at") or "")[:10], "portrait": []}
        for h in state.get("heroes") or [] if h.get("fate") == "died" and h.get("fallen")
    ]


def _fallen(root, state):
    pc, fallen = state["pc"], state["fallen"]
    return {
        "path": str(root), "name": pc.get("name", ""), "info": ", ".join(map(str, pc.get("info", {}).values())),
        "adventure": state.get("title", ""), "scene": fallen.get("scene") or "", "by": fallen.get("by") or "",
        "epitaph": fallen.get("epitaph") or "", "at": (fallen.get("at") or "")[:10],
        "portrait": (state.get("portrait") or {}).get("lines", []),
    }


def _find(kind, name):
    """A pack folder from a path, or from a name looked up in SOLO_HOME, then the repository."""
    path = Path(name).expanduser()
    match = next((p for p in _entries(kind) if packs.slug(p.name) == packs.slug(name)), None)
    if path.is_dir():
        return path.resolve()
    elif match is not None:
        return match
    else:
        names = ", ".join(p.name for p in _entries(kind)) or "none"
        raise SoloError(f"no {kind} called {name!r}; available: {names}")


def _entries(kind):
    mine, bundled, markers = _KINDS[kind]
    found, seen = [], set()
    for folder in (home() / mine, REPO / bundled):
        for path in sorted(folder.iterdir()) if folder.is_dir() else []:
            if path.is_dir() and path.name not in seen and any((path / m).exists() for m in markers):
                seen.add(path.name)
                found.append(path)
    return found
