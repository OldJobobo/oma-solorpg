"""The `solo` command. Mechanical commands print JSON, prose commands print Markdown,
and problems go to stderr with exit status 1."""

import argparse
import json
import os
import random
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# The commands that author packs, run the GM or drive the desktop import those modules where they run: a play
# command, which the Table and the GM wait on, loads none of them.
from . import SoloError, campaign, creation, dice, library, mechanics, packs
# What the prose commands print is written in digest.py. The tests reach it from here too: _clock_line is only theirs.
from .digest import _chronicle_nudge, _clock_line, _elapsed, _hero_line, _now, _progress_lines, history_text, npc_card, recall_text, resume_digest, scene_digest
from .library import REPO

PLUGIN_ID = "cabral.oma-solorpg"
SKILLS = ("solo-gm", "solo-import", "solo-rules-import", "solo-campaign")
AGENT_SKILL_DIRS = (".claude/skills", ".agents/skills", ".codex/skills", ".pi/agent/skills")
# What the GM may run without asking. Only commands that read or play this campaign:
# setup, new, use, play, character --out and import write elsewhere on disk, and a shared
# adventure's text could talk the GM into running them.
GM_COMMANDS = (
    "scene", "npc", "rule", "state", "log", "rebuild", "validate", "resume", "recall", "history",
    "check", "push", "act", "burn", "track", "rest", "roll", "table", "ask", "move", "commit", "say",
    "fight", "attack", "enemy", "ally", "wound", "defend", "dragon", "repair", "ability", "journey", "camp", "cast", "prepare", "learn", "death-roll", "rally", "hero", "threat", "search", "scavenge", "mark", "advance", "voice", "light",
)
# `solo prefs` is left out on purpose: the player's lines and veils are theirs to change.
PLAY_PROMPT = (
    "You are the game master of the solo campaign in this folder. Follow the solo-gm skill "
    "(or read AGENTS.md). Run `solo resume` and do exactly what it says."
)
# Claude Code runs these after every player message and every GM reply, so the campaign
# keeps the conversation word for word without the GM having to remember to.
HOOK = "solo say --hook"
HOOK_EVENTS = ("UserPromptSubmit", "Stop")


def main(argv=None):
    args = _parser(_command(sys.argv[1:] if argv is None else argv)).parse_args(argv)
    try:
        args.run(args)
        # Output still buffered goes now, so a reader that has gone (solo log | head) is met here.
        sys.stdout.flush()
    except SoloError as error:
        print(f"solo: {error}", file=sys.stderr)
        _trace(argv, str(error))
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # The reader stopped reading, and that is all: what is left of the output goes nowhere, so
        # Python's own flush on the way out doesn't meet the closed pipe again (as its docs advise).
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        _trace(argv, None)
        return 1
    except Exception as error:
        # A bug, or a pack the checks let through. The panel shows stderr to the player as
        # it is, so it gets one line; SOLO_DEBUG=1 gives the traceback instead.
        if os.environ.get("SOLO_DEBUG"):
            raise
        message = f"something went wrong ({type(error).__name__}: {error}); run it again with SOLO_DEBUG=1 for the details"
        print(f"solo: {message}", file=sys.stderr)
        _trace(argv, message)
        return 1
    else:
        _trace(argv, None)
        return 0


class _Parser(argparse.ArgumentParser):
    """A usage mistake in one line, not the usage block: the panel shows stderr as it is.
    Subcommands inherit this class from their parent."""

    def error(self, message):
        self.exit(2, f"solo: {message} (see {self.prog} --help)\n")

    def _get_validation_formatter(self):
        # Python 3.14 checks each argument with a formatter that first sets up help's colours, and importing
        # them took ten milliseconds of every command. The check reads no colours; --help still has them.
        return _Uncoloured(prog=self.prog)


class _Uncoloured(argparse.HelpFormatter):
    def _set_color(self, color):
        pass


def _trace(argv, error):
    """SOLO_TRACE=<file>: one JSON line per command, refused ones included, so a play test
    can see what the GM tried and not only what the log kept."""
    path = os.environ.get("SOLO_TRACE")
    if path:
        line = {"at": datetime.now().isoformat(timespec="seconds"), "argv": list(sys.argv[1:] if argv is None else argv), "error": error}
        try:
            # An argument holding a byte that isn't UTF-8 reaches Python as half a character: it is written as the
            # JSON escape it reads back as (\udce9), so the line is still UTF-8 and the command still ends as it did.
            with open(path, "a", encoding="utf-8", errors="backslashreplace") as trace:
                trace.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as error:  # the command already ran; a lost trace line mustn't fail it
            print(f"solo: couldn't write the trace ({error})", file=sys.stderr)


# Campaign management ------------------------------------------------------------------

def cmd_new(args):
    """Everything but the adventure has a default: its system, a random hero, and a
    folder under ~/Games/solo/campaigns named after both."""
    adventure_path = library.find_adventure(args.adventure) if args.adventure else library.only("adventure")
    adventure = packs.load_adventure(adventure_path, drafts=False)
    if adventure["draft"]:
        raise SoloError(f"{adventure['title']} is still being written: it can begin once draft = true is gone from its adventure.toml")
    system_name = args.system or adventure["system"]
    if not system_name:
        raise SoloError(f"{adventure['title']} doesn't name its system: add system = \"...\" to adventure.toml or pass --system")
    system_path = library.find_system(system_name)
    system = packs.load_system(system_path)
    gaps = packs.missing(system)
    if gaps:
        # Before a hero is made: a pack of names only has no creation tables, and its pre-made heroes can't be played on it either.
        raise SoloError(f"{adventure['title']} can't begin until the rules it plays on are built. " + packs.missing_text(system, gaps) + ".")
    if args.character and (Path(args.character).expanduser() / "campaign.toml").exists():
        sheet = campaign.hero(Path(args.character).expanduser(), name=args.name)
    else:
        sheet = creation.character(system, args.character, name=args.name, seed=args.seed, adventure=adventure)
    root = Path(args.dir).expanduser() if args.dir else library.new_campaign_dir(adventure_path.name, sheet.get("name", "hero"))
    prefs = {"tone": args.tone, "lines": args.line, "veils": args.veil}
    root = campaign.create(root, system_path, adventure_path, sheet, args.title, prefs=prefs)
    _write_agent_files(root)
    with campaign.session(root) as c:
        title, pc = c.config["title"], c.state["pc"]
    print(f"Started {title} in {root}")
    print(f"Hero: {_hero_line(pc)}")
    if args.play:
        _play(root)
    else:
        print("Open the Book with: solo play (or Open the Book on the oma-solorpg Table)")


def cmd_library(args):
    _json(library.listing())


def cmd_character(args):
    adventure = packs.load_adventure(library.find_adventure(args.adventure)) if args.adventure else None
    system_name = args.system or (adventure or {}).get("system")
    system = packs.load_system(library.find_system(system_name) if system_name else library.only("system"))
    sheet = campaign.character_sheet(creation.character(system, " ".join(args.words), name=args.name, seed=args.seed, adventure=adventure), system)
    if args.out:
        Path(args.out).expanduser().write_text(json.dumps(sheet, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {args.out}: {_hero_line(sheet)}")
    else:
        _json(sheet)


def _write_agent_files(root):
    """The files an agent reads in a campaign folder. AGENTS.md and CLAUDE.md are ours and
    rewritten, so older campaigns get the current protocol; settings.json is merged, so
    anything the player added there stays."""
    root = Path(root)
    (root / "AGENTS.md").write_text(agents_md(), encoding="utf-8")
    # A Claude Code opened here reads CLAUDE.md, which pulls in AGENTS.md. A Book turn's Claude Code reads no
    # settings files, CLAUDE.md among them, and is handed agents_md() itself (gm.Claude).
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    _merge_settings(root / ".claude" / "settings.json")


def agents_md():
    """A campaign's AGENTS.md: the GM's protocol in short, and where its skill is."""
    skill = str(REPO / "skills" / "solo-gm" / "SKILL.md")
    return (REPO / "templates" / "AGENTS.md").read_text(encoding="utf-8").replace("{{skill}}", skill)


def _merge_settings(path):
    """Claude Code settings: the GM plays through solo without prompts, can't edit the
    campaign by hand, and the hooks record the conversation."""
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        print(f"note: {path} isn't valid JSON, so it was left alone and the conversation won't be recorded automatically")
        return
    permissions = settings.setdefault("permissions", {})
    for key, wanted in (("allow", [f"Bash(solo {name}:*)" for name in GM_COMMANDS]), ("deny", ["Edit", "Write"])):
        permissions[key] = permissions.get(key, []) + [rule for rule in wanted if rule not in permissions.get(key, [])]
    hooks = settings.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        groups = hooks.setdefault(event, [])
        if not any(h.get("command") == HOOK for group in groups for h in group.get("hooks", [])):
            groups.append({"hooks": [{"type": "command", "command": HOOK}]})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def cmd_use(args):
    root = Path(args.dir).expanduser().resolve()
    if (root / "campaign.toml").exists():
        campaign.set_current(root)
        print(f"Current campaign: {root}")
    else:
        raise SoloError(f"{root} isn't a campaign folder (no campaign.toml)")


def cmd_delete(args):
    """Delete a campaign folder for good: the story, the hero, the log. The panel asks
    first and passes --yes; at a terminal it asks here. Never from inside a GM turn."""
    from . import gm
    root = Path(args.dir).expanduser().resolve()
    if os.environ.get("SOLO_BOOK"):
        raise SoloError("the GM can't delete campaigns")
    elif not (root / "campaign.toml").exists():
        raise SoloError(f"{root} isn't a campaign folder (no campaign.toml)")
    elif gm.status(root).get("status") in ("thinking", "writing"):
        raise SoloError("the GM is writing in this campaign: stop it first")
    elif not args.yes:
        with campaign.session(root) as c:
            title, hero = c.config["title"], c.state["pc"].get("name", "")
        if not sys.stdin.isatty():
            raise SoloError("deleting can't be undone: add --yes to confirm")
        elif input(f"Delete {title} ({hero}) and everything in {root}? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Kept.")
            return
    if library.current() == root:
        (library.state_home() / "current").unlink(missing_ok=True)
    shutil.rmtree(root)
    print(f"Deleted {root}")


def cmd_play(args):
    _play(campaign.find(args.dir or args.campaign), terminal=args.terminal)


def _play(root, terminal=False):
    """Open the Book on a campaign: the plugin's story window, with the default agent as
    GM behind it. With an agent the Book can't drive (or --terminal), open the agent in a
    terminal instead, or focus it when it is already open. The GM needs `solo` on PATH and
    the skills, so their links are made here too (a plugin installed with `omarchy plugin
    add` never ran `solo setup`)."""
    import subprocess
    from . import gm
    campaign.set_current(root)
    for line in _links(skill_dirs=_installed_skill_dirs()):
        if not line.startswith("ok"):
            print(line)
    _write_agent_files(root)
    shell = shutil.which("omarchy-shell")
    plugged = shell and (Path.home() / ".config/omarchy/plugins" / PLUGIN_ID).exists()
    if plugged and not terminal and gm.supported(gm.default_agent()):
        with campaign.session(root) as c:
            opening = c.state["last_said"] is None
        if opening and gm.status(root).get("status") not in ("thinking", "writing"):
            # Nothing said yet: the GM opens the adventure while the Book comes up.
            subprocess.Popen([str(REPO / "bin" / "solo"), "-C", str(root), "gm", "turn"], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run([shell, "shell", "summon", PLUGIN_ID, json.dumps({"book": True})], capture_output=True)
        print(f"Opened the Book on {root}.")
        return
    window = _gm_window(root)
    agent = shutil.which("omarchy-agent")
    named, omarchys = os.environ.get("AGENT", "").strip(), gm.omarchy_agent()
    if window is not None:
        subprocess.run(["hyprctl", "dispatch", "focuswindow", f"address:{window}"], capture_output=True)
        print(f"The GM is already open for {root}; focused its window.")
    elif named and named != omarchys:
        # omarchy-agent opens Omarchy's default, not the agent AGENT names. That one is opened here, at a terminal, as
        # bin/ask-agent opens it; from the Table, or an agent that takes no prompt, the player is told how.
        if named in ("claude", "codex") and shutil.which(named) and sys.stdin.isatty():
            os.chdir(root)
            os.execvpe(named, [named, PLAY_PROMPT], {**os.environ, "PWD": str(root), "SOLO_GM": str(root)})
        print(f"AGENT names {named}, and omarchy-agent opens Omarchy's default agent{f' ({omarchys})' if omarchys else ''} instead. "
              f"Open {named} in {root} and give it this:\n\n{PLAY_PROMPT}")
    elif agent is None:
        print(f"omarchy-agent isn't available. Open your coding agent in {root} and ask it to follow the solo-gm skill.")
    else:
        # SOLO_GM marks every process of this GM session, which is how _gm_window finds it.
        subprocess.Popen(
            [agent, "--prompt", PLAY_PROMPT], cwd=root, env={**os.environ, "PWD": str(root), "SOLO_GM": str(root)},
            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if plugged:
            subprocess.run([shell, "shell", "summon", PLUGIN_ID, "{}"], capture_output=True)
        print(f"Opened Omarchy's default agent{f' ({omarchys})' if omarchys else ''} in {root}.")


def _gm_window(root):
    """The Hyprland window of a GM that `solo play` started for this campaign: the first
    ancestor of a process carrying SOLO_GM=<root> that Hyprland lists as a window."""
    import subprocess
    hyprctl = shutil.which("hyprctl")
    listed = subprocess.run([hyprctl, "clients", "-j"], capture_output=True, text=True) if hyprctl else None
    try:
        windows = {client["pid"]: client["address"] for client in json.loads(listed.stdout)} if listed else {}
    except (json.JSONDecodeError, KeyError, TypeError):
        windows = {}
    marker = f"SOLO_GM={root}".encode()
    for proc in Path("/proc").glob("[0-9]*") if windows else []:
        try:
            pid = int(proc.name) if marker in (proc / "environ").read_bytes().split(b"\0") else 0
        except OSError:
            pid = 0
        while pid > 1 and pid not in windows:
            pid = _parent(pid)
        if pid in windows:
            return windows[pid]
    return None


def _parent(pid):
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return 0


def cmd_setup(args):
    import subprocess
    skill_dirs = _installed_skill_dirs()
    for line in _links(plugin=args.plugin, skill_dirs=skill_dirs):
        print(line)
    for line in _preflight(skill_dirs):
        print(line)
    if args.plugin and shutil.which("omarchy-shell"):
        subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], capture_output=True)
    if args.plugin and not shutil.which("omarchy"):
        # With omarchy here, make install enables the plugin itself right after this.
        print(f"Plugin linked. Enable it with: omarchy plugin enable {PLUGIN_ID}")


# Who reads each skills folder, and how setup tells they are installed: their command on PATH, or the
# folder they keep in your home. Codex reads ~/.agents/skills as well as its own.
SKILL_READERS = {".claude/skills": ("claude", ".claude"), ".agents/skills": ("codex", ".agents"),
                 ".codex/skills": ("codex", ".codex"), ".pi/agent/skills": ("pi", ".pi")}


def _installed_skill_dirs():
    """The skills folders of the agents on this machine, so setup doesn't make folders for agents nobody uses."""
    home = Path.home()
    return [folder for folder in AGENT_SKILL_DIRS
            if shutil.which(SKILL_READERS[folder][0]) or (home / SKILL_READERS[folder][1]).is_dir()]


def _preflight(skill_dirs):
    """What playing needs, a line each: ok, or what to do about it."""
    import importlib.util
    from . import gm
    version = ".".join(str(n) for n in sys.version_info[:3])
    lines = [("ok", f"Python {version}")]
    if str(Path.home() / ".local/bin") in os.environ.get("PATH", "").split(":"):
        lines.append(("ok", "~/.local/bin is on PATH, so solo runs by name"))
    else:
        lines.append(("todo", "~/.local/bin isn't on PATH, so call solo by its full path or add it to PATH"))
    missing = [name for name in ("omarchy", "omarchy-shell") if not shutil.which(name)]
    if missing:
        lines.append(("todo", f"{' and '.join(missing)} not found: the d20, the Table and the Book are a plugin for Omarchy's shell. "
                              "Without them, play in your agent from a terminal (solo new, then solo play --terminal)"))
    else:
        lines.append(("ok", "omarchy and omarchy-shell, for the plugin"))
    if shutil.which("hyprctl"):
        lines.append(("ok", "hyprctl, for the desktop effects"))
    else:
        lines.append(("optional", "hyprctl not found, so no desktop effects: they need Hyprland, and the game plays without them"))
    # In the Book's own words (`solo gm agent`), so the two never disagree about the agent or what to do.
    agent = gm.default_agent()
    why = gm.why_not(agent)
    lines.append(("ok", f"the GM is {agent}, which the Book runs") if why is None else ("todo", why))
    if not skill_dirs:
        lines.append(("todo", "no agent found (claude, codex or pi), so no skills were linked: install one and run make install again"))
    if importlib.util.find_spec("pymupdf"):
        lines.append(("ok", "PyMuPDF, for importing your books"))
    else:
        lines.append(("optional", "PyMuPDF not found: only make dragonbane and the other imports need it. "
                                  "On Omarchy: sudo pacman -S python-pymupdf (the README's Troubleshooting has the rest)"))
    return [f"{word:8} {text}" for word, text in lines]


def _links(plugin=False, skill_dirs=AGENT_SKILL_DIRS):
    """Symlinks only, so running it again is harmless. Real files are never replaced."""
    home = Path.home()
    links = [(home / ".local/bin/solo", REPO / "bin" / "solo")]
    links += [(home / folder / skill, REPO / "skills" / skill) for folder in skill_dirs for skill in SKILLS]
    if plugin:
        links.append((home / ".config/omarchy/plugins" / PLUGIN_ID, REPO))
    return [_link(link, target) for link, target in links]


def _link(link, target):
    if link.is_symlink() and link.resolve() == target.resolve():
        return f"ok       {link}"
    elif link.is_symlink():
        link.unlink()
        link.symlink_to(target)
        return f"updated  {link} -> {target}"
    elif link.exists():
        return f"skipped  {link}: a real file is there, move it away to link {target}"
    else:
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
        return f"linked   {link} -> {target}"


# Reading the table ----------------------------------------------------------------------

def cmd_scene(args):
    with _open(args) as c:
        print(scene_digest(c))


def cmd_npc(args):
    with _open(args) as c:
        print(npc_card(c, packs.slug(args.id)))


def cmd_rule(args):
    topic = " ".join(args.topic)
    with _open(args) as c:
        folders = [*(d / "rules" for d in c.system["dirs"]), c.adventure["dir"] / "rules"]
        extra = packs.engine_rules(c.system)
        text = rule_text(topic, packs.rule_matches(folders, topic, extra), packs.rule_pages(folders, extra), _tables_about(c, topic))
    print(text)


def rule_text(topic, matches, pages, tables):
    """What `solo rule` says: the page the topic names, or the one that says most about it,
    with the others that mention it; a short list when several are as likely; the tables the
    topic names. Nothing found is an answer too: the GM rules on it and writes it down."""
    table_line = [f"Tables: {', '.join(f'{name} (solo table {tid})' for tid, name in tables)}"] if tables else []
    if not topic.strip():
        return "\n".join(["The rules here, by title (with the words they're found by):",
                          *[f"- {p['title']}" + (f" ({', '.join(p['search'])})" if p.get("search") else "") for p in pages if not p.get("quiet")]])
    if not matches:
        if table_line:
            return "\n".join(table_line)
        raise SoloError(f"no rule mentions {topic!r} (rules here: {', '.join(p['title'] for p in pages)}). "
                        "If the rules don't cover it, it's yours to rule: a skill roll or the oracle, "
                        "then write the answer down (a fact) so it stays the same")
    (best, page), rest = matches[0], matches[1:]
    if len(matches) == 1 or best >= packs._EXACT or best >= 2 * rest[0][0]:
        others = [p["title"] for _, p in rest[:6]]
        return "\n".join([page["text"].strip(), *([""] + table_line if table_line else []),
                          *(["", f"Also about {topic}: {', '.join(others)}"] if others else [])])
    lines = [f"{len(matches)} pages mention {topic!r}, the likeliest first. Ask for one by title:"]
    lines += [f"- {p['title']}" + (f": {_mention(p['text'], topic)}" if _mention(p["text"], topic) else "") for _, p in matches[:10]]
    return "\n".join(lines + table_line)


def _mention(text, topic):
    """The first line of a page (after its title) that holds the topic's first word."""
    word = topic.lower().split()[0]
    for line in text.splitlines()[1:]:
        if re.search(rf"\b{re.escape(word)}", line.lower()) and not line.lower().startswith("search:"):
            line = " ".join(line.split()).lstrip("-# ")
            return line if len(line) <= 140 else line[:137].rsplit(" ", 1)[0] + "..."
    return ""


def _tables_about(c, topic):
    """Tables whose id or name holds every word of the topic."""
    words = topic.lower().split()
    found = []
    for tid, table in {**c.system["tables"], **c.adventure["tables"]}.items():
        name = str(table.get("name", tid))
        if words and all(re.search(rf"\b{re.escape(w)}", f"{tid.replace('_', ' ')} {name}".lower()) for w in words):
            found.append((tid, name))
    return found[:8]


def cmd_state(args):
    with _open(args) as c:
        state = c.state
        view = {k: state[k] for k in ("title", "scene", "scene_title", "pc", "factions", "promises", "clocks", "clues", "chaos", "combat", "prefs", "ended")}
        view["consequences"] = {cid: k for cid, k in state["consequences"].items() if k["status"] == "open"}
        view["progress"] = {tid: t for tid, t in state["progress"].items() if not t["ended"]}
        view["kit"] = campaign.snapshot(c.system, state)["kit"]
        view["time"] = _elapsed(state["time"])
        view["npcs_met"] = {nid: n for nid, n in state["npcs"].items() if n["met"]}
        _json(view)


def cmd_log(args):
    if args.n < 0:
        raise SoloError(f"-n is how many of the last events to show, from 0 up; not {args.n}")
    with _open(args) as c:
        for event in c.events[-args.n:] if args.n else []:
            print(f"#{event['seq']} {campaign.gm_line(event)}")


def cmd_strike(args):
    """The player's X-card: cut the GM's last message, and add a line or a veil from the same place."""
    if os.environ.get("SOLO_BOOK"):
        raise SoloError("the X-card is the player's: the GM can't strike its own messages")
    with _open(args) as c:
        event = c.strike(args.note)
        if args.line or args.veil:
            c.set_prefs(lines=args.line, veils=args.veil)
        _json({"struck": event["target"], "prefs": c.state["prefs"]})


def cmd_review(args):
    """A campaign played for real, checked the way a play test is: what to write the next scenario about."""
    from . import review
    with _open(args) as c:
        print(review.render(review.review(c, args.trace), c.state["title"]))


def cmd_report(args):
    """A report for a bug: what happened by ids, numbers and dice, with the books' words left out."""
    from . import report
    with _open(args) as c:
        text = report.report(c, events=args.n, messages=0 if args.no_messages else args.messages)
    if args.out:
        Path(args.out).expanduser().write_text(text, encoding="utf-8")
        print(f"wrote {args.out}: read it before you post it")
    else:
        print(text, end="")


def cmd_resume(args):
    with _open(args) as c:
        print(resume_digest(c, book=args.book))


def cmd_recall(args):
    with _open(args) as c:
        print(recall_text(c, " ".join(args.words), limit=args.n))


def cmd_history(args):
    with _open(args) as c:
        print(history_text(c), end="")


def cmd_rebuild(args):
    # From the log alone: the replay a long campaign keeps goes, and is kept again from this one.
    (campaign.find(args.campaign) / ".solo" / "replay.marshal").unlink(missing_ok=True)
    with _open(args) as c:
        c.save()
        print(f"state.json rebuilt from {len(c.events)} events")
        for problem in c.state["problems"]:
            print(f"  {problem}")


def cmd_validate(args):
    if args.system or args.adventure:
        adventure = packs.load_adventure(library.find_adventure(args.adventure)) if args.adventure else None
        name = args.system or (adventure or {}).get("system")
        if not name:
            raise SoloError("which system? pass --system (the adventure doesn't name one)")
        system = packs.load_system(library.find_system(name))
        problems = packs.validate(system, adventure)
    else:
        with _open(args) as c:
            system, adventure, problems = c.system, c.adventure, c.problems
    if problems:
        raise SoloError(f"{len(problems)} problem(s):\n  " + "\n  ".join(problems))
    else:
        print("ok: " + " and ".join(p["dir"].name for p in (system, adventure) if p))
        for warning in [*packs.format_notes(packs.declared_formats(system, adventure)), *(packs.lint(adventure) if adventure else [])]:
            print(f"worth a look: {warning}")


def cmd_campaign(args):
    """Campaigns generated from a premise: roll one, roll its next mission, roll for its
    author, and check what stands between it and play."""
    from . import generate
    if args.action == "new":
        if not args.target:
            raise SoloError('which adventure? solo campaign new <id> --premise "..."')
        target = Path(args.target).expanduser()
        root = target if len(target.parts) > 1 or args.target.startswith((".", "~")) else library.home() / "adventures" / args.target
        system = args.system or "dragonbane"
        made = generate.new(root, library.find_system(system), args.premise, tone=args.tone or "", missions=args.missions,
                            title=args.title, seed=args.seed, system_name=Path(system).name)
        mission = made["mission"]
        print(f"Rolled {made['title']} in {made['dir']} (seed {made['seed']}, {made['rolls']} rolls): the hub, "
              f"and mission 1 of {made['missions']} ({', '.join(mission['scenes'])}).")
        print("It's marked draft and every file says \"rolled, not yet written\": write it up with the solo-campaign skill, "
              f"then solo campaign check {made['dir']}.")
    elif args.action == "next":
        made = generate.next_mission(Path(args.target).expanduser() if args.target else campaign.find(args.campaign))
        print(f"Rolled mission {made['mission']} of {made['missions']} into {made['dir']} ({made['rolls']} rolls): "
              f"{', '.join(made['scenes'])}, as chapters/mission_{made['mission']}.toml (draft).")
        for text in made["threads"]:
            print(f"- comes back: {text}")
        if not made["threads"]:
            print("- nothing the hero did is still open, so nothing was rolled to come back: read solo history anyway")
        print(f"Write it up from what the hero did (solo -C {made['campaign']} history), then solo campaign check {made['dir']}.")
    elif args.action == "roll":
        if not args.target or not args.what:
            raise SoloError('solo campaign roll <adventure> <table | meaning | dice> --for "what it decides"')
        record = generate.roll(library.find_adventure(args.target), " ".join(args.what), args.purpose)
        print(f"#{record['n']} {record['table']} ({record['dice']}): {record['result']}")
        print(f'cite it where it is used: source = "rolled: #{record["n"]}"')
    else:
        if not args.target:
            raise SoloError("which adventure? solo campaign check <adventure>")
        report = generate.check(library.find_adventure(args.target))
        for line in report["notes"]:
            print(line)
        if report["problems"]:
            raise SoloError(f"{len(report['problems'])} thing(s) before it can be played:\n  " + "\n  ".join(report["problems"]))
        print("ok: written, every roll used or explained")


def cmd_inventory(args):
    """Start a book's inventory from its extract: a file per chapter, an item per section and table."""
    from . import audit
    written = audit.scaffold(Path(args.pack).expanduser(), args.extract, source=args.source)
    print(f"wrote {len(written)} files in {Path(args.pack).expanduser()}: " + ", ".join(written))
    print("Every page with text is cited by a todo item. Refine each chapter file, map every item, "
          "and run solo audit until it's clean.")


def cmd_audit(args):
    """The pack against its inventory.toml and the book's pages."""
    from . import audit
    if args.adventure:
        path, kind = library.find_adventure(args.adventure), "adventure"
    else:
        path, kind = library.find_system(args.system) if args.system else library.only("system"), "system"
    report = audit.audit(path, kind, extract=args.extract)
    print(audit.render(report), end="")
    if audit.failed(report):
        raise SoloError(f"{path.name}: something is unaccounted for (above)")


def cmd_compare(args):
    """Two system packs side by side."""
    from . import compare
    first, second = (library.find_system(name) if not Path(name).expanduser().is_dir() else Path(name).expanduser() for name in (args.first, args.second))
    print(compare.render(compare.compare(first, second), (first.name, second.name), 0 if args.all else 8), end="")


def cmd_outline(args):
    """The adventure's shape for its author: GM-only, spoilers and all."""
    if args.adventure:
        adventure = packs.load_adventure(library.find_adventure(args.adventure))
    else:
        with _open(args) as c:
            adventure = c.adventure
    print(packs.outline(adventure), end="")


# Acting --------------------------------------------------------------------------------

def cmd_check(args):
    with _open(args) as c:
        event = c.check(" ".join(args.stat), args.boons, args.banes, rng=_rng())
        _report(c, event, push=_push_options(c, event), threat=_threat_opening(c, event))


def cmd_act(args):
    with _open(args) as c:
        event = c.act(" ".join(args.move), stat=args.stat, adds=args.add, track=args.track, rng=_rng())
        _report(c, event, says=_move_says(c, event), burn=_burn_option(c, event))


def cmd_burn(args):
    with _open(args) as c:
        event = c.burn(rng=_rng())
        _report(c, event, says=_move_says(c, event))


def cmd_track(args):
    words = " ".join(args.words)
    with _open(args) as c:
        if args.action == "add":
            _report(c, c.track_add(words, args.kind or "", args.rank))
        elif args.action == "mark":
            _report(c, c.track_mark(words, args.times))
        elif args.action == "set":
            # A bare number sets the ticks; +4 and -4 (kept as text) move them.
            _report(c, c.track_set(words, ticks=int(args.ticks) if args.ticks and args.ticks.isdigit() else args.ticks, rank=args.rank))
        elif args.action == "end":
            _report(c, c.track_end(words, args.how))
        else:
            print("\n".join(_progress_lines(c.state)) or "No progress tracks yet: solo track add \"<name>\" --kind vow --rank dangerous")


_TWIST = ("The challenge dice match: a twist. On a hit, an opportunity or a turn in the hero's favour; "
          "on a miss, things get worse in a way nobody saw coming (ask the oracle if unsure).")


def _move_says(c, event):
    """The move's own words for the result the dice gave, and what a match adds."""
    words = c.system["moves"][event["move"]]["outcomes"][event["outcome"]["hit"]]
    return f"{words} {_TWIST}" if event["outcome"]["match"] else words


def _burn_option(c, event):
    """What burning momentum would do to the roll just made, if it would do anything."""
    burn = campaign.burn_option(c.state)
    if burn:
        return (f"solo burn (the player's choice, until the next commit, move or move made: ask before any of them): momentum {burn['momentum']} "
                f"cancels the challenge dice under it, {burn['hit'].replace('_', ' ')} instead of {event['outcome']['hit'].replace('_', ' ')}, "
                f"and goes back to {burn['reset']}")


def _threat_opening(c, event):
    """GMs forget that a failure out of a fight can give a looming threat its opening."""
    live = [cid for cid, clock in c.state["clocks"].items() if clock.get("threat") and not clock["stopped"]]
    if live and not c.state["combat"] and not event["outcome"]["success"]:
        return (f"if the failure stands and gives it an opening: solo threat advance {live[0]}"
                + (f" (threats: {', '.join(live)})" if len(live) > 1 else ""))


def cmd_push(args):
    with _open(args) as c:
        _report(c, c.push(args.condition, rng=_rng(), sole_survivor=args.sole_survivor))


def cmd_rest(args):
    with _open(args) as c:
        _report(c, c.rest(args.kind, heal=args.heal, rng=_rng(), tend=args.tend, use=args.use))


def cmd_roll(args):
    with _open(args) as c:
        _report(c, c.roll(args.expr, args.reason, rng=_rng()))


def cmd_table(args):
    with _open(args) as c:
        _report(c, c.table(args.id, rng=_rng()))


def cmd_ask(args):
    with _open(args) as c:
        if args.meaning:
            _report(c, c.meaning(args.question, rng=_rng()))
        elif not args.question:
            raise SoloError('ask a yes/no question, or use --meaning for two words to interpret')
        else:
            _report(c, c.ask(args.question, likely=args.likely, npc=args.npc, rng=_rng(), kind=args.kind))


def cmd_fight(args):
    with _open(args) as c:
        if args.end:
            _report(c, c.end_fight())
        elif args.round:
            _report(c, c.next_round(rng=_rng(), use=args.use))
        elif args.join:
            _report(c, c.join(args.foes, rng=_rng()))
        else:
            _report(c, c.fight(args.foes, rng=_rng()))


def cmd_attack(args):
    with _open(args) as c:
        _report(c, c.attack(args.target, args.weapon, args.boons, args.banes, distance=args.range, defended=args.defended, kind=args.type, use=args.use, rng=_rng()))


def cmd_enemy(args):
    with _open(args) as c:
        event = c.enemy(args.foe, rng=_rng())
        # A monster's result without damage is an effect (a fear roll, a hold): the GM runs it now.
        effect = f"run this now, then narrate it: {event['text']}" if event.get("text") and not event.get("incoming") else None
        _report(c, event, effect=effect)


def cmd_ally(args):
    with _open(args) as c:
        _report(c, c.ally(args.npc, args.foe, rng=_rng()))


def cmd_wound(args):
    with _open(args) as c:
        _report(c, c.wound(args.foe, args.amount, args.why, armor=not args.through_armor, double=args.double, kind=args.kind, rng=_rng()))


def cmd_hero(args):
    with _open(args) as c:
        event = c.take_over(" ".join(args.character), name=args.name, seed=args.seed)
        _report(c, event)


def cmd_threat(args):
    with _open(args) as c:
        if args.action == "add":
            _report(c, c.threat(" ".join(args.words), threat_id=args.id, recurring=args.recurring, rng=_rng(), label=args.label))
        elif args.action == "random":
            _report(c, c.threat(None, threat_id=args.id, recurring=args.recurring, rng=_rng(), label=args.label))
        elif args.action == "advance":
            _report(c, c.advance_threat(" ".join(args.words) or None, args.by, rng=_rng()))
        else:
            _report(c, c.end_threat(" ".join(args.words) or None))


def cmd_search(args):
    with _open(args) as c:
        event = c.search(rng=_rng())
        _report(c, event, push=_push_options(c, event))


def cmd_scavenge(args):
    with _open(args) as c:
        _report(c, c.scavenge(again=args.again, rng=_rng()))


def cmd_defend(args):
    with _open(args) as c:
        _report(c, c.defend(args.how, args.weapon, rng=_rng(), use=args.use))


def cmd_journey(args):
    with _open(args) as c:
        event = c.journey(args.km, mounted=args.mounted, road=args.road, difficult=args.difficult, use=args.use, rng=_rng())
        _report(c, event)


def cmd_camp(args):
    with _open(args) as c:
        _report(c, c.camp(rng=_rng()))


def cmd_cast(args):
    with _open(args) as c:
        _report(c, c.cast(" ".join(args.spell), power=args.power, targets=args.target, boons=args.boons, banes=args.banes, body=args.body,
                          grimoire=args.grimoire, school=args.school, defended=args.defended, rng=_rng()))


def cmd_prepare(args):
    with _open(args) as c:
        _report(c, c.prepare(" ".join(args.spell), drop=args.drop))


def cmd_learn(args):
    with _open(args) as c:
        _report(c, c.learn(" ".join(args.spell), source=args.source, rng=_rng()))


def cmd_ability(args):
    with _open(args) as c:
        _report(c, c.use(" ".join(args.name), cost=args.cost))


def cmd_dragon(args):
    with _open(args) as c:
        _report(c, c.dragon(args.choice, args.foe, rng=_rng()))


def cmd_repair(args):
    with _open(args) as c:
        _report(c, c.repair(args.weapon, rng=_rng(), artisan=args.artisan))


def cmd_death_roll(args):
    with _open(args) as c:
        _report(c, c.save_self(rng=_rng()) if args.heal else c.death_roll(rng=_rng()))


def cmd_rally(args):
    with _open(args) as c:
        _report(c, c.rally(rng=_rng()))


def cmd_voice(args):
    with _open(args) as c:
        event = c.voice(args.skill, " ".join(args.text), rng=_rng())
        _report(c, event, heard=event["heard"])


def cmd_light(args):
    with _open(args) as c:
        _report(c, c.snuff() if args.out else c.light(args.source, rng=_rng()))


def cmd_mark(args):
    with _open(args) as c:
        _report(c, c.mark(" ".join(args.skill), args.reason))


def cmd_advance(args):
    with _open(args) as c:
        _report(c, c.advance(rng=_rng()))


def cmd_prefs(args):
    changes = args.tone is not None or args.line or args.veil or args.clear
    if changes and os.environ.get("SOLO_BOOK"):
        raise SoloError("the table settings are the player's: the GM can read them, never change them")
    with _open(args) as c:
        if changes:
            c.set_prefs(args.tone, args.line, args.veil, clear=args.clear)
        _json(c.state["prefs"])


def cmd_move(args):
    with _open(args) as c:
        _report(c, c.move(args.exit, force=args.force, rng=_rng()))


def cmd_commit(args):
    try:
        payload = json.loads(sys.stdin.read() if args.json == "-" else args.json)
    except ValueError as error:  # a JSONDecodeError, a number too long to read (over 4300 digits), or stdin that isn't UTF-8
        raise SoloError(f"the commit isn't valid JSON: {error}") from None
    except RecursionError:
        raise SoloError("the commit isn't valid JSON here: it nests deeper than Python reads (a commit is an object a few levels deep)") from None
    with _open(args) as c:
        event = c.commit(payload, rng=_rng())
        _report(c, event, chronicle=None if event["changes"].get("chronicle") else _chronicle_nudge(c))


def cmd_say(args):
    if args.hook:
        _say_from_hook(sys.stdin.read())
    else:
        text = sys.stdin.read() if args.text == ["-"] else " ".join(args.text)
        root = campaign.find(args.campaign)
        if args.player and os.environ.get("SOLO_BOOK"):
            # `solo gm turn` records what the player wrote; anything else would be the GM's words under their name.
            raise SoloError("the player's words are theirs: the Book records them as they send them, and the GM can't add to them")
        elif not args.player and _recorded_for_the_gm(root):
            # A GM that records a draft and then sends something else leaves two replies in the story.
            print("not recorded: your final message is recorded for you here, so just send it")
            return
        with campaign.session(root) as c:
            event = c.say(text, "player" if args.player else "gm")
        print(f"recorded #{event['seq']}" if event else "already recorded")


def _recorded_for_the_gm(root):
    """Whether the GM's reply is recorded without it: in a Book turn (`solo gm turn` records
    the final message), or in Claude Code with the campaign's transcript hook."""
    if os.environ.get("SOLO_BOOK"):
        return True
    elif not os.environ.get("CLAUDECODE"):
        return False
    try:
        settings = json.loads((Path(root) / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return any(h.get("command") == HOOK for group in settings.get("hooks", {}).get("Stop", []) for h in group.get("hooks", []))


def _say_from_hook(raw):
    """Record one side of the conversation from a Claude Code hook. It never fails the
    turn and prints nothing: output from a UserPromptSubmit hook would reach the GM."""
    if os.environ.get("SOLO_BOOK"):
        # A Book turn records both sides itself, the GM's words after dropping its notes;
        # the hook's raw copy would differ from that and show twice.
        return
    from . import gm
    try:
        data = json.loads(raw)
        cwd = Path(data.get("cwd") or Path.cwd())
        root = next((f for f in (cwd, *cwd.parents) if (f / "campaign.toml").exists()), None)
        if data.get("hook_event_name") == "UserPromptSubmit":
            prompt = (data.get("prompt") or "").strip()
            by, text = "player", ("" if prompt.startswith(("/", gm.PREAMBLE)) else prompt)
        else:
            said = data.get("last_assistant_message")
            by, text = "gm", said if isinstance(said, str) and said.strip() else _last_reply(data.get("transcript_path"))
        if root is not None and text.strip():
            with campaign.session(root) as c:
                c.say(text, by)
    except (SoloError, OSError, ValueError, AttributeError, KeyError, TypeError) as error:
        print(f"solo say --hook: {error}", file=sys.stderr)


def _last_reply(transcript):
    """The text of the last assistant message in a Claude Code transcript (JSONL). One
    message can span several lines, one per content block, all with the same id."""
    if not transcript or not Path(transcript).exists():
        return ""
    blocks = []
    for line in Path(transcript).read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        message = entry.get("message") if isinstance(entry, dict) and entry.get("type") == "assistant" else None
        content = message.get("content") if isinstance(message, dict) else None
        texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"] if isinstance(content, list) else []
        if any(t.strip() for t in texts):
            key = message.get("id") or entry.get("uuid")
            blocks = (blocks if blocks and blocks[0] == key else [key]) + texts
    return "\n\n".join(t.strip() for t in blocks[1:] if t.strip())


def cmd_gm(args):
    """The Book's side of the GM: run a turn, stop it, report on it, or set its pace (JSON)."""
    from . import gm
    if args.action == "pace":
        # The player's, for every campaign: it needs none.
        if args.text and os.environ.get("SOLO_BOOK"):
            raise SoloError("the GM's pace is the player's to set: the GM can read it, never change it")
        _json({"pace": gm.set_pace(" ".join(args.text)) if args.text else gm.pace()})
    elif args.action == "budget":
        _budget(args)
    else:
        root = campaign.find(args.campaign)
        if args.action == "turn":
            text = sys.stdin.read() if args.text == ["-"] else " ".join(args.text)
            _write_agent_files(root)
            result = gm.turn(root, text or None, agent=args.agent)
            # The note is for the player too (the turn ran with their own Claude Code settings), here as in the Book.
            _json({k: result[k] for k in ("status", "error", "note") if result.get(k)})
            if result["status"] == "error":
                raise SoloError(result["error"])
        elif args.action == "stop":
            gm.stop(root)
            print("stopped")
        elif args.action == "agent":
            agent = gm.default_agent()
            why = gm.why_not(agent)
            _json({"agent": agent, "book": gm.supported(agent), **({"why": why} if why else {})})
        else:
            _json(gm.status(root))


def _budget(args):
    """What a GM session may spend, the player's to see and raise (never the GM's: solo gm isn't a GM command).
    The limits are for every campaign; the count is the campaign's, and --reset starts it again."""
    from . import gm
    if (args.text or args.turns or args.reset) and os.environ.get("SOLO_BOOK"):
        # Claude Code's GM may not run `solo gm` at all. A Codex GM has no list of allowed commands, so it is refused
        # here; it could clear SOLO_BOOK, which is why the limits and the count are kept out of the campaign folder.
        raise SoloError("the GM's budget is the player's to set: the GM can read it, never raise or reset it")
    if args.text and not args.text[0].replace(".", "", 1).isdigit():
        raise SoloError(f"a budget is dollars, a number: solo gm budget 20 (or --turns 400), not {args.text[0]!r}")
    limit = gm.set_budget(usd=float(args.text[0]) if args.text else None, turns=args.turns) if args.text or args.turns else gm.budget()
    try:
        root = campaign.find(args.campaign)
    except SoloError:
        root = None
    if root is not None and args.reset:
        gm.reset_spend(root)
    saved = json.loads((root / ".solo" / "agent.json").read_text(encoding="utf-8")).get("session") if root and (root / ".solo" / "agent.json").exists() else None
    _json({"limit": limit, **({"spent": {k: v for k, v in gm.spent(root, saved).items() if k != "session"}} if root else {})})


def cmd_desk(args):
    """Desktop effects for the plugin: flash, dying, death, candle, omen, screensaver,
    sound, restore, settings."""
    from . import desk
    words = args.words
    if args.after:
        time.sleep(min(max(0.0, args.after), 10.0))
    if args.effect == "flash":
        desk.flash(words[0] if words else "dragon")
    elif args.effect == "dying":
        failures = words[1] if len(words) > 1 else "0"
        if not failures.isdigit():
            raise SoloError(f"expected a count of failed death rolls, not {failures!r}")
        desk.dying(_on(words), failures=int(failures))
    elif args.effect == "death":
        desk.death()
    elif args.effect == "candle":
        desk.candle(_on(words))
    elif args.effect == "sound":
        if words:
            desk.sound(words[0])
        else:
            _json(desk.sound_kit())
    elif args.effect == "omen":
        desk.omen(" ".join(words))
    elif args.effect == "screensaver":
        desk.screensaver(_on(words), root=campaign.find(args.campaign) if _on(words) else None)
    elif args.effect == "restore":
        _json(desk.restore())
    else:
        changes = {}
        for word in words:
            name, _, value = word.partition("=")
            changes[name] = _on([value])
        _json(desk.set_settings(changes) if changes else desk.settings())


def _on(words):
    value = (words[0] if words else "on").lower()
    if value not in ("on", "off", "true", "false"):
        raise SoloError(f"expected on or off, not {value!r}")
    return value in ("on", "true")


def cmd_extract(args):
    from . import extract
    out, manifest = extract.extract(args.pdf, args.out, tables=not args.no_tables)
    print(f"wrote {out}")
    print(f"{manifest['pages']} pages, {manifest['chars']:,} characters (about {manifest['chars'] // 4:,} tokens), "
          f"{manifest['chapters']} chapter{'' if manifest['chapters'] == 1 else 's'} from the {manifest['toc_from']}"
          + (f", {manifest['tables']} table{'' if manifest['tables'] == 1 else 's'}" if manifest["tables"] is not None else ""))
    if manifest.get("labels_from") == "footers":
        print("The PDF has no page labels: the printed page numbers were read off the footers (manifest.json, labels).")
    if manifest["toc_from"] != "outline":
        print("The PDF has no bookmarks: toc.json is a guess from font sizes. Check it against the book's contents page.")
    if manifest["scanned"]:
        listed = ", ".join(map(str, manifest["scanned"]))
        print(f"{len(manifest['scanned'])} pages have almost no text and a picture: {listed}. A cover, a chapter opener or full-page art looks like this and needs nothing; "
              "if a page that should hold text is among them (it is a scan), run ocrmypdf on the PDF and extract again.")


def cmd_import(args):
    from . import booktables, datasworn, foundry
    if args.source == "datasworn":
        report = datasworn.build(packs.load_data(Path(args.json).expanduser()), Path(args.out).expanduser())
        print(f"wrote {report['moves']} moves, {report['tables']} tables and {report['assets']} assets into {args.out}")
        print("left out (not under CC BY, or not read): " + "; ".join(f"{kind} {what}" for kind, what in report["left_out"].items()))
        print("the yes/no odds its ask-the-oracle tables give (system.toml's [oracle] odds): " + ", ".join(f"{level} {chance}" for level, chance in report["odds"].items()))
        print("\n".join(f"note: {note}" for note in report["notes"]))
    elif args.source == "book":
        _import_book(args)
    elif args.source == "table":
        text = sys.stdin.read() if args.file == "-" else Path(args.file).expanduser().read_text(encoding="utf-8")
        path, problems = booktables.write(text, Path(args.out).expanduser(), name=args.name, formula=args.formula, source=args.pages and f"p. {args.pages}")
        print(f"wrote {path}")
        if problems:
            raise SoloError("check it against the book's page (the picture in tables/ when columns scrambled): " + "; ".join(problems))
    else:
        if args.kind == "adventure":
            written = foundry.import_adventure(args.paths, args.out, journal=args.journal)
        elif args.kind == "rules":
            written = foundry.import_rules(args.paths, args.out)
        else:
            written = foundry.import_character(args.paths, args.out, system=packs.load_system(library.find_system(args.system)))
        print(f"wrote {written}")


def _import_book(args):
    """The packs of the books some importer knows, built and audited against the books' own pages: one book, or every PDF in a folder (in the order the packs go on
    one another)."""
    from . import audit, books, extract
    path = Path(args.path).expanduser()
    many = path.is_dir() and not (path / "manifest.json").exists()
    if many and args.out:
        raise SoloError("--out is the folder of one pack: point at one PDF, or give --systems and --adventures for the folders of all of them")
    # A book that can't be read, or that no importer knows, doesn't stop the others: each is said, and the import fails at the end.
    folders, failed = [], []
    for source in (sorted(path.glob("*.pdf")) if many else [path]):
        if source.is_dir():
            folders.append(source)
            continue
        try:
            folder, manifest = extract.extract(source, None if many else args.sources, tables=False)
        except SoloError as error:
            print(f"\n{source.name}: {error}")
            failed.append(f"{source.name} (it can't be read)")
            continue
        print(f"read {manifest['pages']} pages of {source.name} into {folder}")
        folders.append(folder)
    known, unknown, broken = books.plan(folders)
    for folder, error in broken:
        print(f"\n{Path(folder).name} can't be read: {error}")
        failed.append(f"{Path(folder).name} (it can't be read)")
    for folder, recipe in known:
        try:
            target, written, notes = books.build(folder, args.out, args.replace, args.systems, args.adventures)
        except SoloError as error:
            print(f"\n{recipe.NAME}: {error}")
            failed.append(f"{recipe.NAME} (it wasn't built)")
            continue
        except Exception as error:
            # A page the importer trips over without naming it: said, like any book that isn't built, and the other books are built all the same.
            if os.environ.get("SOLO_DEBUG"):
                raise
            print(f"\n{recipe.NAME}: the importer stopped ({type(error).__name__}: {error}); this may be another printing than it was written for. "
                  "Run it again with SOLO_DEBUG=1 for the details.")
            failed.append(f"{recipe.NAME} (the importer stopped)")
            continue
        print(f"\n{recipe.NAME}: built {len(written)} files in {target}")
        print("\n".join(f"  note: {note}" for note in notes))
        report = audit.audit(target, books.kind_of(recipe))
        print(f"  audit: {report['counts']['mapped']} items mapped, {len(report['unclaimed'])} unclaimed, {len(report['problems'])} problems, "
              f"{len(report['unverified'])} unverified, {len((report['pages'] or {}).get('uncited', []))} pages uncited")
        if audit.failed(report):
            print(audit.render(report), end="")
            failed.append(f"{target.name} (the pack and the book's pages disagree)")
    for folder in unknown:
        print(f"\n{books.unknown(folder)}")
        failed.append(f"{Path(folder).name} (no importer knows it)")
    if failed:
        raise SoloError(f"not every book became a pack: {'; '.join(failed)}. See above.")


# How long a push is on offer, for the GM: the next commit or move (campaign._GOES_ON) lets the roll stand.
_PUSH_UNTIL = ("the next commit or move (or rest, journey, torch lit or new round), which lets the roll stand: "
               "ask the player, and end the turn on the question with nothing committed")


def _push_options(c, event):
    if event["outcome"]["pushable"]:
        cost = c.system["push"].get("cost", "condition")
        if cost == "condition":
            taken = c.state["pc"]["conditions"]
            options = {"cost": "take a condition", "choose_from": [x for x in c.system["conditions"] if x not in taken]}
            ability = c._ability("push")
            if ability:
                options["or"] = f"{ability.get('name')}: pay {', '.join(f'{v} {t}' for t, v in ability['push'].items())} instead (solo push --sole-survivor)"
            return {**options, "until": _PUSH_UNTIL}
        else:
            return {"cost": cost, "until": _PUSH_UNTIL}
    else:
        return None


def _report(c, event, **extra):
    """The event, a one-line summary, and everything else the command did, in order: what
    came before the roll (a search's stretch passing, a threat moving) and what it set off
    (clock ticks, table rolls), and any consequence whose moment it brought."""
    c.come_due()
    then = [campaign.gm_line(e) for e in c.events[c.opened:] if e["seq"] != event["seq"]]
    report = {"summary": campaign.gm_line(event), **{k: v for k, v in extra.items() if v}, "then": then, "now": _now(c), "event": event}
    _json({k: v for k, v in report.items() if v != []})


def _json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _open(args):
    return campaign.session(campaign.find(args.campaign))


def _rng():
    """SOLO_SEED makes rolls repeatable (tests, demos); otherwise dice use the system RNG.
    A command's dice are seeded by SOLO_SEED and the seq of the event it writes first, so a
    seeded run repeats roll for roll and one command doesn't roll what the last one did.
    Events written under it carry the seed, so the log and the Book show it."""
    seed = dice.fixed_seed()
    return random.Random(f"{seed}:{campaign.next_seq()}") if seed is not None else None


def _prefs_arguments(sub):
    sub.add_argument("--tone", help='how the story should feel: "grim and quiet", "pulpy"')
    sub.add_argument("--line", action="append", default=[], help="something that never happens in the story (repeatable)")
    sub.add_argument("--veil", action="append", default=[], help="something that happens only off screen (repeatable)")


def command_names():
    """Every `solo` command, GM or not."""
    return sorted(_parser()._subparsers._group_actions[0].choices)


class _Unbuilt:
    """Another command's parser, while one command runs: whatever is added to it goes nowhere."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: self


def _command(argv):
    """The command in `solo -C <folder> scene ...`, read before parsing, or None (none given, or help asked first)."""
    words = iter(argv)
    for word in words:
        if word in ("-h", "--help"):
            return None
        elif word in ("-C", "--campaign"):
            next(words, None)
        elif not word.startswith("-"):
            return word
    return None


def _parser(only=None):
    """Every command's parser, or with `only` that command's alone, so a click on the Table or a command
    the GM runs doesn't build the sixty others first."""
    parser = _Parser(prog="solo", description="Local engine for solo tabletop play.")
    parser.add_argument("-C", "--campaign", help="campaign folder (default: found from the working directory, then the current one)")
    # `prog` given, argparse doesn't make a formatter (and its colours) to work out "solo" for the commands' usage.
    commands = parser.add_subparsers(required=True, metavar="command", prog="solo")
    built = []

    def command(name, run, text):
        if only and name != only:
            return _Unbuilt()
        sub = commands.add_parser(name, help=text, description=text)
        sub.set_defaults(run=run)
        built.append(name)
        return sub

    sub = command("new", cmd_new, "start a campaign: solo new red-tusk")
    sub.add_argument("adventure", nargs="?", help="adventure name (see solo library) or folder")
    sub.add_argument("--character", help='character file, pre-made hero (ragna), choices like "dwarf fighter" (default: random), or an earlier campaign\'s folder to bring its hero along')
    sub.add_argument("--name", help="the hero's name")
    sub.add_argument("--seed", type=int, help="rebuild the same random hero (the panel's preview uses this)")
    sub.add_argument("--dir", help="campaign folder (default: ~/Games/solo/campaigns/<adventure>-<hero>)")
    sub.add_argument("--title")
    sub.add_argument("--system", help="system pack name or folder (default: the one the adventure names)")
    sub.add_argument("--play", action="store_true", help="open the GM once the campaign is ready")
    _prefs_arguments(sub)
    command("library", cmd_library, "systems, adventures and campaigns (JSON)")
    sub = command("character", cmd_character, "roll or build a hero without starting a campaign (JSON)")
    sub.add_argument("words", nargs="*", help="creation choices like: dwarf fighter old; or a pre-made hero's id")
    sub.add_argument("--system", help="system pack name or folder (default: the one --adventure names)")
    sub.add_argument("--adventure", help="also offer this adventure's own pre-made heroes")
    sub.add_argument("--name", help="the hero's name")
    sub.add_argument("--seed", type=int, help="rebuild the same random hero")
    sub.add_argument("--out", help="write the sheet to this .json file")
    command("use", cmd_use, "make a campaign the current one").add_argument("dir")
    sub = command("delete", cmd_delete, "delete a campaign folder for good (asks first, or --yes)")
    sub.add_argument("dir")
    sub.add_argument("--yes", action="store_true", help="don't ask")
    sub = command("play", cmd_play, "open the Book (or the default agent in a terminal) on a campaign")
    sub.add_argument("dir", nargs="?")
    sub.add_argument("--terminal", action="store_true", help="open the agent in a terminal instead of the Book")
    sub = command("setup", cmd_setup, "link solo into ~/.local/bin and the skills into the agents' skill folders")
    sub.add_argument("--plugin", action="store_true", help="also link the omarchy-shell panel plugin")

    command("scene", cmd_scene, "the current scene, for the GM (Markdown)")
    command("npc", cmd_npc, "an NPC's profile and live state (Markdown)").add_argument("id")
    command("rule", cmd_rule, "a rules page by title or topic (none: every page)").add_argument("topic", nargs="*")
    sub = command("strike", cmd_strike, "the player's X-card: cut the GM's last message (the Book and recall leave it out; the GM is told not to come back to it)")
    sub.add_argument("--note", help="what to avoid, in the player's words")
    sub.add_argument("--line", action="append", default=[], help="also make this a line: something that never happens in the story (repeatable)")
    sub.add_argument("--veil", action="append", default=[], help="also make this a veil: something that happens only off screen (repeatable)")
    sub = command("review", cmd_review, "check this campaign as a play test would: refused commands, bookkeeping in the story, foes that never struck back, consequences never paid, a person with two names (Markdown)")
    sub.add_argument("--trace", help="a trace file (SOLO_TRACE); default: the campaign's own .solo/trace.jsonl, which the Book's turns write")
    sub = command("report", cmd_report, "a bug report for this campaign, safe to post: ids, numbers and dice, with rules pages and pack text left out (Markdown)")
    sub.add_argument("-n", type=int, default=25, help="how many recent events (default 25)")
    sub.add_argument("--messages", type=int, default=6, help="how many of the last messages to include (default 6)")
    sub.add_argument("--no-messages", action="store_true", help="leave the story's own words out too")
    sub.add_argument("--out", help="write it to a file instead of printing it")
    command("state", cmd_state, "the character and the table at a glance (JSON)")
    command("log", cmd_log, "recent events").add_argument("-n", type=int, default=15)
    sub = command("resume", cmd_resume, "where the table stopped: the GM's last words and what came after (Markdown)")
    sub.add_argument("--book", action="store_true", help="the player reads the Book, so don't repeat the last words")
    sub = command("recall", cmd_recall, "search the whole campaign for something: every word said, notes, facts, memories (Markdown)")
    sub.add_argument("words", nargs="+", help="what to look for: smith hammer")
    sub.add_argument("-n", type=int, default=8, help="how many matches (default 8)")
    command("history", cmd_history, "the whole campaign in order, chapter by chapter, for the GM (Markdown)")
    command("rebuild", cmd_rebuild, "rebuild state.json from the event log")
    sub = command("validate", cmd_validate, "check packs (default: the campaign's)")
    sub.add_argument("--system", help="system pack folder")
    sub.add_argument("--adventure", help="adventure pack folder")

    sub = command("compare", cmd_compare, "two system packs side by side: a pack built from a book against one an agent wrote (Markdown)")
    sub.add_argument("first", help="a system pack folder or name")
    sub.add_argument("second", help="the one to compare it to")
    sub.add_argument("--all", action="store_true", help="every difference, not the first few of each area")
    sub = command("audit", cmd_audit, "a pack against its inventory.toml and the book's pages (Markdown)")
    group = sub.add_mutually_exclusive_group()
    group.add_argument("--system", help="system pack name or folder (default: the only one)")
    group.add_argument("--adventure", help="adventure pack name or folder")
    sub.add_argument("--extract", help="solo extract's folder for the book (default: the inventory's extract)")

    sub = command("outline", cmd_outline, "an adventure's scenes, gates, clocks and the facts it reads, for its author (spoilers)")
    sub.add_argument("--adventure", help="adventure pack name or folder (default: the campaign's)")

    sub = command("check", cmd_check, "roll a skill or attribute")
    sub.add_argument("stat", nargs="+")
    sub.add_argument("--boons", type=int, default=0)
    sub.add_argument("--banes", type=int, default=0)
    sub = command("act", cmd_act, "make a move (Ironsworn): the roll it asks for, and the move's words for the result")
    sub.add_argument("move", nargs="+", help="a move by id or name: face_danger, strike, fulfill_your_vow")
    sub.add_argument("--stat", help="what the roll adds, from the ones the move lists (edge, heart, iron ...), or highest / lowest of them")
    sub.add_argument("--add", type=int, default=0, help="adds: the +1s a move, an asset or a bond gives")
    sub.add_argument("--track", help="a progress move: the vow, journey or fight it reads (default: the only one open)")
    command("burn", cmd_burn, "burn momentum on the last action roll: challenge dice under it are cancelled, momentum resets")
    sub = command("track", cmd_track, "progress tracks (Ironsworn): add <name> --kind vow --rank dangerous, mark <id> [--times 2], set <id> [--ticks 8] [--rank epic], end <id> --how fulfilled, list")
    sub.add_argument("action", choices=["add", "mark", "set", "end", "list"])
    sub.add_argument("words", nargs="*", help="add: the track's name; mark, set, end: its id")
    sub.add_argument("--kind", help="add: vow, journey or combat (a fight)")
    sub.add_argument("--rank", help="add, set: troublesome, dangerous, formidable, extreme or epic")
    sub.add_argument("--times", type=int, default=1, help="mark: how many marks (a foe's harm: one each)")
    sub.add_argument("--ticks", help="set: the ticks (a number sets them; +4 or -4 moves them)")
    sub.add_argument("--how", default="done", help="end: how it ended (fulfilled, forsaken, won, lost)")
    sub = command("push", cmd_push, "push the last check")
    sub.add_argument("--condition", help="condition to take (Dragonbane)")
    sub.add_argument("--sole-survivor", action="store_true", help="pay willpower instead of a condition (the Sole Survivor heroic ability)")
    sub = command("rest", cmd_rest, "rest: recover, heal conditions, let time pass")
    sub.add_argument("kind", help="a rest from the system pack: round, stretch, shift")
    sub.add_argument("--heal", help="the condition to heal first")
    sub.add_argument("--tend", action="store_true", help="the hero tends their own wounds: a HEALING roll for more HP (solo rules)")
    sub.add_argument("--use", action="append", default=[], metavar="ABILITY", help="a heroic ability this uses (paid in WP): Fast Healer, on a stretch rest")
    sub = command("roll", cmd_roll, "roll a dice expression: 2d20kl, 5d6cs>=6, d66, 1d6+@stress")
    sub.add_argument("expr")
    sub.add_argument("--reason")
    command("table", cmd_table, "roll on a table").add_argument("id")
    sub = command("ask", cmd_ask, "ask the oracle a yes/no question, or --meaning for two words")
    sub.add_argument("question", nargs="?")
    sub.add_argument("--meaning", action="store_true", help="words to interpret, for questions a yes or no can't answer")
    sub.add_argument("--kind", help="with a fortune chart: yes_no (default), number, scale, power, quality, reaction")
    odds = sub.add_mutually_exclusive_group()
    odds.add_argument("--likely", help=f"one of: {', '.join(campaign.LIKELIHOOD)} (Ironsworn: small chance, unlikely, 50/50, likely, almost certain)")
    odds.add_argument("--npc", help="take the odds from this NPC's attitude and promises")
    sub = command("move", cmd_move, "take an exit")
    sub.add_argument("exit")
    sub.add_argument("--force", metavar="REASON", help="jump to any scene and record why")
    sub = command("fight", cmd_fight, "start a fight with NPCs (repeat an id for several), --join more, --round, --end")
    sub.add_argument("foes", nargs="*", help="npc ids: priest cultist cultist")
    group = sub.add_mutually_exclusive_group()
    group.add_argument("--join", action="store_true", help="these foes enter the fight under way")
    group.add_argument("--round", action="store_true", help="next round: new initiative cards")
    group.add_argument("--end", action="store_true", help="the fight is over")
    sub.add_argument("--use", action="append", default=[], metavar="ABILITY", help="a heroic ability this uses (paid in WP): --round: Lightning Fast, Veteran")
    sub = command("attack", cmd_attack, "the hero attacks a foe with a carried weapon")
    sub.add_argument("target", nargs="?", help="the foe (default: the only one standing)")
    sub.add_argument("--with", dest="weapon", help="the weapon (default: the first carried)")
    sub.add_argument("--boons", type=int, default=0)
    sub.add_argument("--banes", type=int, default=0)
    sub.add_argument("--use", action="append", default=[], metavar="ABILITY", help="a heroic ability this uses (paid in WP): Dragonslayer, Massive Blow, Iron Fist")
    sub.add_argument("--defended", choices=["dodge", "parry"], help="the foe dodges or parries the blow, which costs it one of its actions")
    sub.add_argument("--type", choices=["slashing", "piercing", "bludgeoning"], help="the damage a weapon that cuts and stabs does")
    sub.add_argument("--range", type=int, metavar="METERS", help="how far the foe is: a shot too near or too far gets a bane, a blow out of reach is refused")
    command("enemy", cmd_enemy, "a foe attacks the hero").add_argument("foe", nargs="?", help="the foe (default: the only one standing)")
    sub = command("ally", cmd_ally, "an NPC on the hero's side attacks a foe, once a round")
    sub.add_argument("npc", help="the ally: orc_leader")
    sub.add_argument("foe", nargs="?", help="the foe (default: the only one standing)")
    sub = command("wound", cmd_wound, "harm by something other than a weapon blow: fire, a spell, a trap, a fall (a foe in a fight, or the hero)")
    sub.add_argument("foe", help="a foe in the fight, or hero")
    sub.add_argument("amount", help="dice or a number: 2d6, 4; or all")
    sub.add_argument("--why", required=True, help="what does the harm, in the story's words")
    sub.add_argument("--through-armor", action="store_true", help="armor doesn't help (fire, a hand through the chest)")
    sub.add_argument("--double", action="store_true", help="double damage (a weakness the adventure names: fire against a wooden foe)")
    sub.add_argument("--kind", help="the kind of damage, for a foe that resists or is immune to it: fire, magic, slashing, piercing, bludgeoning")
    sub = command("threat", cmd_threat, "a looming danger on a D6 counter: add <what happens>, random, advance <id> [--by 2], end <id>")
    sub.add_argument("action", choices=["add", "random", "advance", "end"])
    sub.add_argument("words", nargs="*", help="add: what happens when it triggers; advance, end: the threat's id (default: the only one)")
    sub.add_argument("--id", help="add, random: the threat's id (default: from its words)")
    sub.add_argument("--label", help="add, random: a short name for the table (default: from the id)")
    sub.add_argument("--recurring", action="store_true", help="inherent to the mission or place: starts over after it triggers")
    sub.add_argument("--by", type=int, default=1, help="advance: how far (2 for a Demon on a task against time)")
    command("search", cmd_search, "search an area with care: a stretch passes, then SPOT HIDDEN and the search table")
    sub = command("scavenge", cmd_scavenge, "rummage through something specific: supplies, a nest, a fallen foe's gear")
    sub.add_argument("--again", action="store_true", help="the same place again: it takes a stretch")
    sub = command("defend", cmd_defend, "answer an incoming hit: evade, parry or take")
    sub.add_argument("how", choices=["evade", "parry", "resist", "take"])
    sub.add_argument("--with", dest="weapon", help="parry: the weapon (default: the first that can); resist: the attribute or skill (wil)")
    sub.add_argument("--use", action="append", default=[], metavar="ABILITY", help="a heroic ability this uses (paid in WP): Defensive, Fast Footwork, Shield Block")
    sub = command("journey", cmd_journey, "travel a number of kilometers a shift at a time, until the hero arrives or something needs the GM")
    sub.add_argument("km", type=int)
    sub.add_argument("--mounted", action="store_true", help="on horseback: twice as far a shift")
    sub.add_argument("--road", action="store_true", help="along a road or a clear path: nobody gets lost, so no roll")
    sub.add_argument("--difficult", action="store_true", help="difficult terrain: a bane on the pathfinder's roll")
    sub.add_argument("--use", action="append", default=[], metavar="ABILITY", help="a heroic ability that helps the pathfinder (Pathfinder)")
    command("camp", cmd_camp, "find a place to rest in the wild: the roll that decides whether the shift can be a rest")
    sub = command("cast", cmd_cast, "cast a spell the hero knows: pay its WP, roll the school, and do what it does")
    sub.add_argument("spell", nargs="+")
    sub.add_argument("--power", type=int, default=1, help="the power level, 1 to 3: each costs the same again")
    sub.add_argument("--target", action="append", default=[], help="the foe a damage spell is for (repeat for the ones it goes on to)")
    sub.add_argument("--boons", type=int, default=0)
    sub.add_argument("--banes", type=int, default=0)
    sub.add_argument("--body", help="draw power from the body (d6): that many WP at once, and as much harm")
    sub.add_argument("--grimoire", action="store_true", help="cast a spell that isn't prepared, from the grimoire (twice as long)")
    sub.add_argument("--school", help="a general spell: the school to cast it with (default: the hero's best)")
    sub.add_argument("--defended", choices=["dodge", "parry"], help="how a foe avoids a spell that can be avoided")
    sub = command("prepare", cmd_prepare, "hold a spell ready (as many as the rules allow; --drop another to make room)")
    sub.add_argument("spell", nargs="+")
    sub.add_argument("--drop", help="the prepared spell to put aside")
    sub = command("learn", cmd_learn, "learn a spell, from a teacher or a grimoire (a school mark, and a roll)")
    sub.add_argument("spell", nargs="+")
    sub.add_argument("--from", dest="source", default="teacher", help="teacher (default) or grimoire")
    sub = command("ability", cmd_ability, "pay for a heroic ability and log it, for one the GM runs from its rule page")
    sub.add_argument("name", nargs="+", help="the ability: Fearless")
    sub.add_argument("--cost", type=int, help="what an ability that costs what the hero chooses to spend costs")
    sub = command("dragon", cmd_dragon, "a Dragon on the hero's attack: choose double, attack (a free one on another foe) or pierce")
    sub.add_argument("choice")
    sub.add_argument("foe", nargs="?", help="attack: the other foe")
    sub = command("repair", cmd_repair, "mend a weapon that broke or was damaged: a CRAFTING roll, or --artisan")
    sub.add_argument("weapon")
    sub.add_argument("--artisan", action="store_true", help="an artisan sees to it: no roll")
    sub = command("death-roll", cmd_death_roll, "the dying hero's roll against death (or --heal: try to save their own life)")
    sub.add_argument("--heal", action="store_true", help="instead, a HEALING roll to save their own life (solo rules)")
    command("rally", cmd_rally, "the dying hero rallies themselves to act again, still dying (solo rules)")
    sub = command("hero", cmd_hero, "after the hero dies, the player carries on with another in the same story")
    sub.add_argument("character", nargs="+", help="one of the adventure's replacement heroes, a pre-made hero, or choices like: human thief")
    sub.add_argument("--name", help="the new hero's name")
    sub.add_argument("--seed", type=int, help="rebuild the same random hero")
    sub = command("voice", cmd_voice, "one of the hero's skills speaks up, if a quiet roll succeeds")
    sub.add_argument("skill")
    sub.add_argument("text", nargs="+", help="what the skill would say")
    sub = command("light", cmd_light, "light a carried torch (it burns down as time passes), or --out")
    sub.add_argument("source", nargs="?", help="a light source from the system pack (default: the first, a torch)")
    sub.add_argument("--out", action="store_true", help="put the light out")
    sub = command("mark", cmd_mark, "mark a skill for advancement")
    sub.add_argument("skill", nargs="+")
    sub.add_argument("--reason", help="why, such as the end-of-session question it answers")
    command("advance", cmd_advance, "end of session: roll for every marked skill")
    sub = command("prefs", cmd_prefs, "the player's table settings: tone, lines, veils (JSON)")
    _prefs_arguments(sub)
    sub.add_argument("--clear", action="store_true", help="start the settings over")
    command("commit", cmd_commit, "apply consequences").add_argument("json", help="the commit as JSON, or - to read stdin")
    sub = command("say", cmd_say, "record what the GM told the player, word for word (or --player: what they said)")
    sub.add_argument("text", nargs="*", help="the text, or - to read stdin")
    sub.add_argument("--player", action="store_true", help="the player said it")
    sub.add_argument("--hook", action="store_true", help="read a Claude Code hook's JSON from stdin")

    sub = command("gm", cmd_gm, "the Book's GM: turn [text | -], stop, status, agent, pace [quick|normal|careful], budget [dollars]")
    sub.add_argument("action", choices=["turn", "stop", "status", "agent", "pace", "budget"])
    sub.add_argument("text", nargs="*", help="turn: what the player says (none: the GM opens or picks up the story); pace: the new pace; budget: dollars a session may spend")
    sub.add_argument("--agent", help="turn: an agent other than the default (claude, codex)")
    sub.add_argument("--turns", type=int, help="budget: GM turns a session may run (for an agent that doesn't say what a turn costs)")
    sub.add_argument("--reset", action="store_true", help="budget: start counting this campaign's session again")

    sub = command("desk", cmd_desk, "desktop effects: flash dragon|demon|hit, dying on [failures]|off, death, candle on|off, omen <text>, screensaver on|off, sound [name], restore, settings [name=on|off]")
    sub.add_argument("--after", type=float, default=0, metavar="SECONDS", help="wait first (to land with the Book's dice)")
    sub.add_argument("effect", choices=["flash", "dying", "death", "candle", "omen", "screensaver", "sound", "restore", "settings"])
    sub.add_argument("words", nargs="*")

    sub = command("extract", cmd_extract, "a book's PDF as text by page and chapter, for importing (needs PyMuPDF)")
    sub.add_argument("pdf")
    sub.add_argument("--out", help="folder to write (default: ~/Games/solo/sources/<book>)")
    sub.add_argument("--no-tables", action="store_true", help="skip table detection (faster on a long book)")

    sub = command("import", cmd_import, "build pack files: from a Foundry export, a book's roll table, or Datasworn's Ironsworn")
    sources = sub.add_subparsers(dest="source", required=True, metavar="source")
    sub = sources.add_parser("datasworn", help="Ironsworn's moves, oracles and assets (the CC BY parts) from Datasworn's classic.json")
    sub.add_argument("json", help="Datasworn's Ironsworn ruleset: classic.json, from github.com/rsek/datasworn")
    sub.add_argument("--out", required=True, help="the system pack folder: moves/, tables/ and assets/ are written in it")
    sub = sources.add_parser("foundry", help="adventures, rules and characters from Foundry VTT's Export Data")
    sub.add_argument("kind", choices=["adventure", "rules", "character"])
    sub.add_argument("paths", nargs="+", help="exported JSON files or folders of them")
    sub.add_argument("--out", required=True, help="adventure folder, system pack folder, or character file")
    sub.add_argument("--journal", help="adventure: only this journal (name or id)")
    sub.add_argument("--system", default="dragonbane", help="character: system pack to map onto (name or folder)")
    sub = sources.add_parser("book", help="a book's pack, built from its bookmarks and layout by the importer that knows it (the core rules, ...)")
    sub.add_argument("path", help="the book's PDF (extracted first, needs PyMuPDF), the folder solo extract left, or a folder of PDFs: every one an importer knows")
    sub.add_argument("--out", help="the pack folder to build, for one book (default: the importer's own, in ~/Games/solo/systems or adventures)")
    sub.add_argument("--systems", help="the folder the system packs are built in (default ~/Games/solo/systems), and where an adventure finds the rules it is for; to compare with packs you have, build in another and use solo compare")
    sub.add_argument("--adventures", help="the folder the adventure packs are built in (default ~/Games/solo/adventures)")
    sub.add_argument("--sources", help="where the PDF is extracted to (default: ~/Games/solo/sources/<book>)")
    sub.add_argument("--replace", action="store_true", help="build over a pack this made before (never one made any other way)")
    sub = sources.add_parser("table", help="a roll table from solo extract's Markdown (tables/p0042-1.md) or pasted lines (-)")
    sub.add_argument("file", help="the table as Markdown rows or roll lines (\"1-2 Frozen in place\"), or - to read stdin")
    sub.add_argument("--out", required=True, help="the pack's tables/<id>.toml to write")
    sub.add_argument("--name", help="the table's name (default: from the file name)")
    sub.add_argument("--formula", help="the dice, when neither the header nor the ranges say (1d6, 2d6, d66, 1d100)")
    sub.add_argument("--pages", help="the book's pages it is on, for its source line: 45 or 45-46")

    sub = command("campaign", cmd_campaign, "a campaign from a premise: new <id> --premise ..., next [campaign folder], roll <adventure> <what> --for ..., check <adventure>")
    sub.add_argument("action", choices=["new", "next", "roll", "check"])
    sub.add_argument("target", nargs="?", help="new: the adventure's id or folder; next: the campaign folder (default: this one); roll, check: the adventure")
    sub.add_argument("what", nargs="*", help="roll: a table of the packs, meaning, or dice (2d6)")
    sub.add_argument("--premise", help="new: what the campaign is about, in a sentence")
    sub.add_argument("--tone", help="new: grim, hopeful, weird ...")
    sub.add_argument("--missions", type=int, default=3, help="new: how many missions (default 3)")
    sub.add_argument("--system", help="new: the system pack (default: dragonbane)")
    sub.add_argument("--title", help="new: the campaign's title (default: from its hub)")
    sub.add_argument("--seed", type=int, help="new: the dice's seed, to roll the same campaign again")
    sub.add_argument("--for", dest="purpose", help="roll: what the roll decides")

    sub = command("inventory", cmd_inventory, "start a book's inventory from solo extract's folder: a file per chapter, an item per section and table")
    sub.add_argument("pack", help="the pack folder the inventory is for (created if missing)")
    sub.add_argument("--extract", required=True, help="solo extract's folder for the book")
    sub.add_argument("--source", help="the book's name (default: from the PDF's file name)")
    # A command that isn't one gets every parser, so argparse lists the commands there are.
    return parser if built or not only else _parser()
