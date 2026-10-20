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
from . import SoloError, campaign, combat, creation, dice, library, mechanics, oracle, packs
from .library import REPO
from .packs import ATTITUDES

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


def _trace(argv, error):
    """SOLO_TRACE=<file>: one JSON line per command, refused ones included, so a play test
    can see what the GM tried and not only what the log kept."""
    path = os.environ.get("SOLO_TRACE")
    if path:
        line = {"at": datetime.now().isoformat(timespec="seconds"), "argv": list(sys.argv[1:] if argv is None else argv), "error": error}
        try:
            with open(path, "a", encoding="utf-8") as trace:
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
    if args.character and (Path(args.character).expanduser() / "campaign.toml").exists():
        sheet = campaign.hero(Path(args.character).expanduser(), name=args.name)
    else:
        sheet = creation.character(packs.load_system(system_path), args.character, name=args.name, seed=args.seed, adventure=adventure)
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
        print("Open the GM with: solo play (or the Open the GM button in the oma-solorpg panel)")


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
    skill = str(REPO / "skills" / "solo-gm" / "SKILL.md")
    (root / "AGENTS.md").write_text((REPO / "templates" / "AGENTS.md").read_text(encoding="utf-8").replace("{{skill}}", skill), encoding="utf-8")
    # Claude Code reads CLAUDE.md, which pulls in AGENTS.md.
    (root / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    _merge_settings(root / ".claude" / "settings.json")


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
    if window is not None:
        subprocess.run(["hyprctl", "dispatch", "focuswindow", f"address:{window}"], capture_output=True)
        print(f"The GM is already open for {root}; focused its window.")
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
        print(f"Opened the default agent in {root}.")


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
    agent = gm.default_agent()
    if not agent:
        lines.append(("todo", "no default agent: choose Claude Code, Codex or Pi with omarchy default agent, or set AGENT=claude"))
    elif not shutil.which(agent):
        lines.append(("todo", f"the default agent is {agent}, and {agent} isn't on PATH: install it, or choose another with omarchy default agent"))
    elif gm.supported(agent):
        lines.append(("ok", f"the GM is {agent}, which the Book runs"))
    else:
        lines.append(("todo", f"the default agent is {agent}, which the Book can't run: it opens in a terminal instead (solo play --terminal), "
                              "or choose Claude Code, Codex or Pi with omarchy default agent"))
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
        return (f"solo burn (the player's choice): momentum {burn['momentum']} cancels the challenge dice under it, "
                f"{burn['hit'].replace('_', ' ')} instead of {event['outcome']['hit'].replace('_', ' ')}, and goes back to {burn['reset']}")


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
    text = sys.stdin.read() if args.json == "-" else args.json
    try:
        payload = json.loads(text)
    except ValueError as error:  # a JSONDecodeError, or a number too long to read (over 4300 digits)
        raise SoloError(f"the commit isn't valid JSON: {error}") from None
    with _open(args) as c:
        event = c.commit(payload, rng=_rng())
        _report(c, event, chronicle=None if event["changes"].get("chronicle") else _chronicle_nudge(c))


def cmd_say(args):
    if args.hook:
        _say_from_hook(sys.stdin.read())
    else:
        text = sys.stdin.read() if args.text == ["-"] else " ".join(args.text)
        root = campaign.find(args.campaign)
        if not args.player and _recorded_for_the_gm(root):
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
            _json({k: result[k] for k in ("status", "error") if result.get(k)})
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
        # A Codex GM has no list of allowed commands, so the refusal is here.
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


def cmd_ui(args):
    """Player-owned app appearance, independent of campaigns and desktop effects."""
    from . import ui
    if args.hyprland_appearance:
        if any(value is not None for value in (args.scale, args.book_scale, args.table_scale, args.honor_hyprland)):
            raise SoloError("use --hyprland-appearance on its own")
        from .hyprland import appearance
        _json(appearance())
        return
    changes = args.scale is not None or args.book_scale is not None or args.table_scale is not None or args.honor_hyprland is not None
    if changes and os.environ.get("SOLO_BOOK"):
        raise SoloError("interface settings are the player's to set: the GM can read them, never change them")
    if args.scale is not None:
        if args.book_scale is not None or args.table_scale is not None or args.honor_hyprland is not None:
            raise SoloError("use --scale on its own, or set --book-scale and --table-scale")
        _json(ui.set_scale(args.scale))
    else:
        _json(ui.set_scales(book_scale=args.book_scale, table_scale=args.table_scale,
                            honor_hyprland=None if args.honor_hyprland is None else args.honor_hyprland == "on"))


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
    folders = []
    for source in (sorted(path.glob("*.pdf")) if many else [path]):
        if source.is_dir():
            folders.append(source)
        else:
            folder, manifest = extract.extract(source, None if many else args.sources, tables=False)
            print(f"read {manifest['pages']} pages of {source.name} into {folder}")
            folders.append(folder)
    known, unknown = books.plan(folders)
    failed = []
    for folder, recipe in known:
        target, written, notes = books.build(folder, args.out, args.replace, args.systems, args.adventures)
        print(f"\n{recipe.NAME}: built {len(written)} files in {target}")
        print("\n".join(f"  note: {note}" for note in notes))
        report = audit.audit(target, books.kind_of(recipe))
        print(f"  audit: {report['counts']['mapped']} items mapped, {len(report['unclaimed'])} unclaimed, {len(report['problems'])} problems, "
              f"{len(report['unverified'])} unverified, {len((report['pages'] or {}).get('uncited', []))} pages uncited")
        if audit.failed(report):
            print(audit.render(report), end="")
            failed.append(target.name)
    for folder in unknown:
        print(f"\nno importer knows {Path(folder).name}: an agent with the solo-rules-import or solo-import skill can read it (make adventure, make supplement)")
    if failed:
        raise SoloError(f"{', '.join(failed)}: the pack and the book's pages disagree (above)")


# Rendering ------------------------------------------------------------------------------

def scene_digest(c):
    """What the GM needs for this turn. GM-only text stays inside its ::: gm fences."""
    state, adventure = c.state, c.adventure
    scene_id = state["scene"]
    scene = adventure["scenes"][scene_id]
    lines = [f"# {scene.get('title', scene_id)} ({scene_id})", ""]
    lines += _prefs_lines(state)
    lines += _problem_lines(c)
    if state["ended"]:
        lines += [f"The adventure has ended: {state['ended']['text']}", ""]
    if scene.get("climax"):
        lines += ["This is a climax scene.", ""]
    lines += _scene_check_lines(c)
    lines += [packs.scene_text(adventure, scene_id).strip(), ""]
    lines += _light_lines(c)
    if state["voices"]:
        lines += ["## What the hero noticed (their skills spoke up; the player has read these)",
                  *[f"- {v['label']}: {v['text']}" for v in state["voices"]], ""]
    lines += _back_here_lines(c)
    lines += _due_lines(c)
    true_now = [b["text"] for b in scene.get("branches", []) if packs.evaluate(b["when"], state)]
    if true_now:
        lines += ["## True now", *[f"- {text}" for text in true_now], ""]
    every = packs.exits(adventure, scene_id)
    shut = {sid: spec for sid, spec in every.items() if not packs.is_open(spec, state)}
    lines += ["## Exits", *([f"- {sid}: {spec['label']}" + _travel(c, spec) for sid, spec in every.items() if sid not in shut] or ["- none"]), ""]
    if shut:
        lines += ["## Closed for now (GM only: don't mention a way the hero hasn't found)",
                  *[f"- {sid}: {spec['label']}; opens when {spec['when']}" for sid, spec in shut.items()], ""]
    here = campaign.people_here(adventure, state)
    # The text may name someone the story has since taken elsewhere: they aren't here any more.
    moved = [nid for nid in scene.get("npcs", []) if nid in state["npcs"] and nid not in here]
    if here or moved:
        lines += ["## People here", *[_npc_line(c, nid) for nid in here]]
        if moved:
            lines.append("- Not here any more, though the text names them (the story has put them elsewhere): " + ", ".join(
                f"{state['npcs'][nid]['name']} (now at {_scene_title(c, state['npcs'][nid]['location'])})" for nid in moved))
        lines.append("")
    if scene.get("tables"):
        lines += ["## Tables for this scene", *[f"- {t}" for t in scene["tables"]], ""]
    if state["clocks"]:
        lines += ["## Clocks", *[_clock_line(c, cid) for cid in state["clocks"]], ""]
    lines += _fact_lines(c)
    if state["combat"]:
        lines += ["## Fight", *[f"- {line}" for line in _now(c) if not line.startswith("ended")], ""]
    lines += _progress_lines(state)
    chaos = [] if c.system.get("oracle", {}).get("chart") in ("fortune", "odds") else [f"Chaos factor: {state['chaos']}"]
    story = _hero_story(state)
    load = combat.encumbrance(c.system, state["pc"])
    lines += ["## Character", _pc_line(state), *([f"Load: {load['carried']:g} of {load['capacity']}" + ("; OVER-ENCUMBERED (solo rule encumbrance)" if load["over"] else "")] if load else []),
              _skills_line(state), *(["Their story (hero.* facts): " + "; ".join(story)] if story else []), *chaos, ""]
    nudge = _chronicle_nudge(c)
    if nudge:
        lines += ["## Your chronicle", nudge, ""]
    recent = [e for e in c.events if e["type"] != "said"][-6:]
    lines += ["## Recent", *[f"- #{e['seq']} {campaign.gm_line(e)}" for e in recent]]
    return "\n".join(lines)


def _back_here_lines(c):
    """A place the hero comes back to holds what they left there. How long they were away,
    and what happened here before, from the log."""
    state, entries = c.state, c.chronology()
    arrivals = [e for e in entries if any(m["kind"] in ("arrive", "return") for m in e["moments"])]
    if not arrivals or arrivals[-1]["scene"] != state["scene"]:
        return []
    now = arrivals[-1]
    before = [a for a in arrivals[:-1] if a["scene"] == state["scene"]]
    if not before:
        return []
    after_last = next(a for a in arrivals if a["seq"] > before[-1]["seq"])
    left = max(e["time"] for e in entries if before[-1]["seq"] <= e["seq"] < after_last["seq"])
    happened = [m for m in campaign.moments(entries) if m["scene"] == state["scene"] and m["seq"] < now["seq"]
                and m["kind"] not in ("arrive", "return", "begin", "chronicle")]
    visits = {1: "once", 2: "twice"}.get(len(before), f"{len(before)} times")
    lines = [f"## Back here (the hero was here {visits} before, and left {_ago(state['time'] - left)} ago)"]
    if happened:
        lines += ["What happened here then, latest last:", *[_moment_line(m, where=False) for m in happened[-8:]]]
    lines += ["The place and its people lived on while the hero was away: show what they left and what changed since "
              "(the people and facts below, anything due), not the text as if it were new.", ""]
    return lines


def _due_lines(c):
    due = [(cid, k) for cid, k in c.state["consequences"].items() if campaign.ready(c.adventure, c.state, k)]
    if not due:
        return []
    return ["## Due now (GM only: what the hero did comes back. Pay it off in the story, this turn or the next, "
            "then commit it done: {\"consequence\": {\"id\": \"<id>\", \"status\": \"done\"}})",
            *[f"- {cid}: {k['text']}" + (f" (concerns {c.state['npcs'].get(k['npc'], {}).get('name', k['npc'])})" if k["npc"] else "")
              for cid, k in due], ""]


def _fact_lines(c):
    """What the story has settled (puzzles solved, doors forced, names given), so the GM never
    has to remember it: the facts about this place, the people here and what this scene's
    conditions read, however old, then the latest set elsewhere. The hero's own facts are
    under Character."""
    state = c.state
    facts = {k: v for k, v in state["facts"].items() if not k.startswith("hero.")}
    if not facts:
        return []
    near = {state["scene"], *campaign.people_here(c.adventure, state)}
    read = packs.scene_facts(c.adventure, state["scene"])
    relevant = [k for k in facts if k in read or k.split(".")[0] in near]
    last_set = {}
    for event in c.events:
        for key in (event.get("changes") or {}).get("facts", {}):
            last_set[key] = event["seq"]
    others = sorted((k for k in facts if k not in relevant), key=lambda k: last_set.get(k, 0))
    room = max(0, _FACTS_SHOWN - len(relevant))
    latest = others[-room:] if room else []
    lines = ["## Facts (settled by the story: this place and the people here first, then the latest)",
             *[f"- {key}: {json.dumps(facts[key], ensure_ascii=False)}" for key in relevant + latest]]
    if len(others) > len(latest):
        lines.append(f"- and {len(others) - len(latest)} more, settled earlier elsewhere: solo recall <word> finds them")
    return lines + [""]


_FACTS_SHOWN = 40


def _hero_story(state):
    """The hero.* facts: what the player has made of their hero (a lost brother, an oath, a
    fear of deep water). The story should come back to them."""
    return [f"{key[5:]}: {value}" for key, value in state["facts"].items() if key.startswith("hero.")]


def _chronicle_nudge(c):
    """A GM that plays for hours without a chronicle entry leaves the next session with only
    the log. After CHRONICLE_EVERY of its messages, it is asked for one."""
    state = c.state
    since = state["chronicle"][-1]["seq"] if state["chronicle"] else 0
    count = sum(1 for e in c.events if e["type"] == "said" and e["by"] == "gm" and e["seq"] > since)
    if count >= campaign.CHRONICLE_EVERY:
        return (f"{count} of your messages since the last chronicle entry: put a \"chronicle\" in your next commit, a paragraph "
                "a GM who wasn't here could pick the story up from (what happened, who matters now and why, what is unresolved).")
    return None


def _moment_line(m, where=True):
    place = "" if not where or m["kind"] in ("arrive", "return", "begin") else f", {m['title']}"
    return f"- [{_elapsed(m['time'])}{place}] {m['text']}"


def _scene_title(c, scene_id):
    return c.adventure["scenes"].get(scene_id or "", {}).get("title", scene_id or "somewhere")


def _ago(seconds):
    """Game time in the words a GM would use: 40 minutes, 5 hours, 3 days."""
    minutes = max(0, int(seconds)) // 60
    if minutes < 1:
        return "moments"
    elif minutes < 60:
        return f"{minutes} minute{'s' * (minutes != 1)}"
    elif minutes < 48 * 60:
        return f"{minutes // 60} hour{'s' * (minutes // 60 != 1)}"
    else:
        return f"{minutes // 1440} days"


def resume_digest(c, book=False, scene=False):
    """What the GM needs to pick up exactly where the table stopped: its own last words,
    to repeat as they were, and what happened after them. In the Book the player has
    already read them, so the GM carries on instead of repeating itself. `scene`: the
    scene digest comes right after this (the Book's first prompt), so it isn't run."""
    state, events = c.state, c.events
    speech = [e for e in events if e["type"] == "said" and e["seq"] not in state["struck"]]  # what the player cut is gone
    last = next((e for e in reversed(speech) if e["by"] == "gm"), None)
    lines = [f"# {state['title']}: {state['pc']['name']} in {state['scene_title']} ({state['scene']})", ""]
    lines += _prefs_lines(state)
    lines += _cut_lines(c)
    lines += _problem_lines(c)
    lines += [f"- {line}" for line in _now(c)] + ([""] if _now(c) else [])
    if last is None:
        return "\n".join(lines + [
            "Nothing has been said at this table yet: this is the opening.",
            "",
            ("Open the adventure from the scene below" if scene else "Run `solo scene`, then open the adventure")
            + ": describe the first scene and end with a question to the player.",
            "", *_threads(c),
        ]).rstrip() + "\n"
    hidden = set(state["hidden"])
    since = [e for e in events if e["seq"] > last["seq"] and e["type"] != "said"]
    answer = [e for e in speech if e["seq"] > last["seq"] and e["by"] == "player"]
    earlier = [e for e in speech if e["seq"] < last["seq"]][-4:]
    if book:
        steps = ["The player is reading the Book, which already shows your last message (under \"Last said\") and every roll since. Don't repeat or recap it."]
    else:
        steps = ["Send the text under \"Last said\" to the player word for word, as your whole first message: no greeting, no recap, no new description."]
    if since:
        steps.append("After it, narrate only what is listed under \"Since then\", briefly and without naming hidden things.")
    steps.append("The player already answered (under \"Player since\"): carry on from their words." if answer
                 else "Answer with a short line that hands the scene back to the player." if book else "Wait for the player's answer.")
    lines += [f"Resume exactly where the table stopped. {'Read the scene below' if scene else 'Run `solo scene` for yourself'}, then:", ""]
    lines += [f"{number}. {step}" for number, step in enumerate(steps, 1)]
    lines += ["", "## Last said", "", last["text"], ""]
    if since:
        lines += ["## Since then", *[f"- #{e['seq']} {campaign.gm_line(e)}" + (" (hidden from the player)" if e["seq"] in hidden else "") for e in since], ""]
    if answer:
        lines += ["## Player since", *[f"{e['text']}\n" for e in answer]]
    if earlier:
        lines += ["## Earlier (for you, don't repeat)", *[f"{'GM' if e['by'] == 'gm' else 'Player'}: {e['text']}\n" for e in earlier]]
    lines += _threads(c)
    return "\n".join(lines).rstrip() + "\n"


def _cut_lines(c):
    """What the player cut with the X-card (the last few), for the GM to stay clear of: what it had said, what the
    player asked, and what it had committed that turn (a cut doesn't undo it)."""
    said = {e["seq"]: e["text"] for e in c.events if e["type"] == "said"}
    cuts = [e for e in c.events if e["type"] == "struck"][-3:]
    if not cuts:
        return []
    lines = ["## Cut by the player (an X-card: never come back to these, and don't repeat them)"]
    for e in cuts:
        first = " ".join(said.get(e["target"], "").split())
        lines.append(f"- You had said (#{e['target']}): \"{first[:240] + '...' if len(first) > 240 else first}\"" + (f". The player said: {e['note']}" if e.get("note") else ""))
        lines += [f"  - it had committed, and that stands unless you retract it in the story: {kept}" for kept in e.get("committed") or []]
    return lines + [""]


_RECENT_MOMENTS = 25
_CHRONICLE_SHOWN = 6
_PEOPLE_SHOWN = 12


def _threads(c):
    """The long memory of a campaign, for a GM starting a session cold, however long it has
    run: where the hero comes from, the chronicle, what has happened since its last entry (from
    the log, so it's there even when no entry was written), what is waiting to come back,
    promises, clues, the people the hero knows, what word has spread, and who is gone."""
    state, adventure, entries = c.state, c.adventure, c.chronology()
    lines = []
    if state["past"]:
        lines.append("## Before this adventure (the hero's earlier stories; the people in them may turn up again)")
        for record in state["past"]:
            lines.append(f"- {record.get('title', 'An adventure')}" + (f": {record['ended']}" if record.get("ended") else ""))
            lines += [f"  - {text}" for text in record.get("chronicle", [])]
            if record.get("loose_ends"):
                lines.append("  - left open: " + "; ".join(record["loose_ends"]))
            if record.get("people"):
                lines.append("  - people who will remember them: " + "; ".join(record["people"]))
        lines.append("")
    lines += ["## The hero, as the player made them (hero.* facts)", *[f"- {line}" for line in _hero_story(state)], ""] if _hero_story(state) else []
    at = {e["seq"]: e for e in entries}
    if state["chronicle"]:
        older = len(state["chronicle"]) - _CHRONICLE_SHOWN
        lines += ["## The story so far (your chronicle, latest last)", *([f"- ({older} earlier entries: solo history)"] if older > 0 else [])]
        lines += [f"- [{_elapsed(at[e['seq']]['time'])}, {at[e['seq']]['title']}] {e['text']}" if e["seq"] in at else f"- {e['text']}"
                  for e in state["chronicle"][-_CHRONICLE_SHOWN:]]
        lines.append("")
    since = state["chronicle"][-1]["seq"] if state["chronicle"] else 0
    recent = [m for m in campaign.moments(entries, after=since) if m["kind"] not in ("chronicle", "begin")]
    if recent and state["last_said"]:
        heading = "## Since your last chronicle entry" if since else "## What has happened so far"
        lines += [f"{heading} (from the log, latest last)",
                  *([f"- ({len(recent) - _RECENT_MOMENTS} earlier: solo history)"] if len(recent) > _RECENT_MOMENTS else []),
                  *[_moment_line(m) for m in recent[-_RECENT_MOMENTS:]], ""]
    waiting = [(cid, k) for cid, k in state["consequences"].items() if k["status"] == "open"]
    if waiting:
        lines += ["## Loose ends (what the hero did that will come back; GM only)", *[_consequence_line(c, cid, k) for cid, k in waiting], ""]
    promises = [f"- {pid} (to {p['npc']}): {p['terms']}" for pid, p in state["promises"].items() if p["status"] == "open"]
    if promises:
        lines += ["## Promises still open", *promises, ""]
    if state["clues"]:
        lines += ["## Clues the hero holds", f"- {', '.join(state['clues'])}", ""]
    seen = {}
    for m in campaign.moments(entries):
        for npc_id in m["npcs"]:
            seen[npc_id] = m["seq"]
    known = sorted((nid for nid, n in state["npcs"].items() if n["met"] and n["fate"] == "alive"
                    and not campaign.profile_of(adventure, state, nid).get("many")), key=lambda nid: -seen.get(nid, 0))
    if known:
        lines += ["## People the hero knows (the latest met first)", *[_known_line(c, nid) for nid in known[:_PEOPLE_SHOWN]],
                  *([f"- and {len(known) - _PEOPLE_SHOWN} more: solo npc <id>"] if len(known) > _PEOPLE_SHOWN else []), ""]
    factions = [_faction_line(state, fid) for fid, f in state["factions"].items()
                if f.get("memories") or f["standing"] != int(adventure["factions"].get(fid, {}).get("standing", 0))]
    if factions:
        lines += ["## Factions (where the hero stands, and what word has reached them)", *factions, ""]
    gone = [f"{n['name']} ({n['fate']})" for nid, n in state["npcs"].items()
            if n["met"] and n["fate"] != "alive" and not campaign.profile_of(adventure, state, nid).get("many")]
    if gone:
        lines += ["## No longer in the story", f"- {', '.join(gone)}", ""]
    fallen = state.get("heroes") or []
    if fallen:
        lines += ["## Heroes before this one", *[f"- {h['name']}: {h['fate']}" for h in fallen], ""]
    if any(e["type"] == "said" for e in c.events):
        lines += ["Anything older or not listed: `solo recall <words>` searches every word said at this table, and "
                  "`solo history` tells the whole story in order. Look it up before you invent it.", ""]
    return lines


def _consequence_line(c, consequence_id, consequence):
    """A loose end as the GM reads it: what, about whom, and when it comes back."""
    state = c.state
    npc = state["npcs"].get(consequence["npc"] or "")
    when = []
    if consequence["at"]:
        when.append("at " + " or ".join(_scene_title(c, s) for s in consequence["at"]))
    if consequence["when"]:
        when.append(f"when {consequence['when']}")
    if consequence["due_at"] is not None:
        when.append(f"from {_elapsed(consequence['due_at'])} of game time")
    if not when:
        when.append(f"the next time the hero meets {npc['name']}" if npc else "no trigger: bring it in when it fits")
    line = f"- {consequence_id}: {consequence['text']} ({'; '.join(when)})"
    if npc and (consequence["at"] or consequence["when"] or consequence["due_at"] is not None):
        line += f"; concerns {npc['name']}"
    if npc and npc["fate"] != "alive":
        line += f"; {npc['name']} is {npc['fate']}: drop it, or let someone else carry it"
    if campaign.ready(c.adventure, state, consequence):
        line += " [due now]"
    elif consequence["due"]:
        line += " [came due earlier, not yet paid off]"
    return line


def _known_line(c, npc_id):
    state = c.state
    npc, profile = state["npcs"][npc_id], campaign.profile_of(c.adventure, state, npc_id)
    line = f"- {npc_id}: {npc['name']}" + (f", {profile['role']}" if profile.get("role") else "") + f" ({_attitude_name(npc['attitude'])})"
    if npc.get("location"):
        line += f", at {_scene_title(c, npc['location'])}"
    if npc["memories"]:
        line += "; remembers: " + " / ".join(npc["memories"][-2:])
    return line


def _faction_line(state, faction_id):
    faction = state["factions"][faction_id]
    heard = faction.get("memories") or []
    return f"- {faction_id}: {faction['name']} ({_attitude_name(faction['standing'])})" + (f"; they've heard: {' / '.join(heard[-3:])}" if heard else "")


def npc_card(c, npc_id):
    state, adventure = c.state, c.adventure
    if npc_id not in state["npcs"]:
        raise SoloError(f"unknown npc {npc_id!r}; npcs: {', '.join(state['npcs']) or 'none'}")
    npc, profile = state["npcs"][npc_id], campaign.profile_of(adventure, state, npc_id)
    faction = state["factions"].get(npc.get("faction") or "", {})
    lines = [f"# {npc['name']} ({npc_id})", ""]
    if profile.get("role"):
        lines.append(profile["role"])
    if profile.get("many"):
        lines.append("A kind of foe the hero meets again and again: every fight brings new ones, and no one fate covers them all.")
    if faction:
        lines.append(f"Faction: {faction['name']} (standing {_attitude_name(faction['standing'])})"
                     + (f"; they've heard: {' / '.join(faction['memories'][-3:])}" if faction.get("memories") else ""))
    lines += [
        f"Now: {npc['fate']}, {_attitude_name(npc['attitude'])} toward the PC"
        + (f", at {npc['location']}" if npc.get("location") else ""),
        "",
    ]
    if npc.get("profile"):
        lines += [f"(You made up {', '.join(npc['profile'])} in play: keep to it.)", ""]
    for key in ("wants", "fears", "voice", "description"):
        if profile.get(key):
            lines.append(f"{key.capitalize()}: {profile[key]}")
    secrets = profile.get("secrets", [])
    if secrets:
        lines += ["", "## Secrets (GM only)"]
        for secret in secrets:
            when = secret.get("reveal")
            status = "" if not when else (" [can be revealed now]" if packs.evaluate(when, state) else f" [reveal when {when}]")
            lines.append(f"- {secret.get('id', 'secret')}: {secret.get('text', '')}{status}")
    promises = [f"- {pid} ({p['status']}): {p['terms']}" for pid, p in state["promises"].items() if p["npc"] == npc_id]
    if promises:
        lines += ["", "## Promises", *promises]
    waiting = [_consequence_line(c, cid, k) for cid, k in state["consequences"].items() if k["npc"] == npc_id and k["status"] == "open"]
    if waiting:
        lines += ["", "## Waiting on them (consequences, GM only)", *waiting]
    if npc["memories"]:
        lines += ["", "## Remembers", *[f"- {m}" for m in npc["memories"]]]
    for key in ("stats", "skills"):
        if profile.get(key):
            lines += ["", f"## {key.capitalize()}", ", ".join(f"{k} {v}" for k, v in profile[key].items())]
    shown = {"name", "role", "faction", "attitude", "wants", "fears", "voice", "description", "secrets", "stats", "skills", "kind", "many"}
    rest = {k: v for k, v in profile.items() if k not in shown}
    if rest:
        lines += ["", "## Other", *[f"- {k}: {v}" for k, v in rest.items()]]
    return "\n".join(lines)


def recall_text(c, query, limit=8):
    """What the campaign holds about something, for a GM about to bring it back: the words
    said at the table first of all, then notes, facts, memories and oracle answers."""
    found = campaign.recall(c.chronology(), c.state, query, limit=limit)
    if not found:
        return (f"Nothing at this table mentions {query!r}. If it matters now, the story hasn't settled it yet: "
                "decide it (or ask the oracle), and write it down so it stays the same.")
    lines = [f"# Recall: {query}", ""]
    for hit in found:
        where = f"[{_elapsed(hit['time'])}, {hit['title']}]" if hit["time"] is not None else f"[{hit['title']}]"
        lines.append(f"- {'#' + str(hit['seq']) + ' ' if hit['seq'] else ''}{where} {hit['label']}: {hit['text']}")
    return "\n".join(lines)


def history_text(c):
    """The whole campaign in order, for the GM (spoilers and GM notes included): chapters that
    close on each chronicle entry, the moments in between from the log."""
    state = c.state
    lines = [f"# {state['title']}: the story so far", "", f"{_hero_line(state['pc'])}; {_elapsed(state['time'])} of game time.", ""]
    for record in state["past"]:
        lines += [f"## Before: {record.get('title', 'an adventure')}", *([record["ended"]] if record.get("ended") else []),
                  *[f"- {text}" for text in record.get("chronicle", [])], ""]
    chapter, number = [], 1
    for m in campaign.moments(c.chronology()):
        if m["kind"] == "chronicle":
            lines += [f"## Chapter {number}", *chapter, "", f"Chronicle: {m['text']}", ""]
            chapter, number = [], number + 1
        else:
            chapter.append(_moment_line(m))
    if chapter:
        lines += [f"## Chapter {number}" + (" (since the last chronicle entry)" if number > 1 else ""), *chapter, ""]
    return "\n".join(lines).rstrip() + "\n"


def _prefs_lines(state):
    """The player's table settings, first in everything the GM reads."""
    prefs = state["prefs"]
    lines = [f"- Tone: {prefs['tone']}"] if prefs["tone"] else []
    lines += [f"- Line (never in the story): {line}" for line in prefs["lines"]]
    lines += [f"- Veil (happens off screen only): {veil}" for veil in prefs["veils"]]
    return ["## Table settings (the player's; always respect them)", *lines, ""] if lines else []


def _problem_lines(c):
    """What's wrong with the packs under the campaign (one edited since it began, say). The
    GM plays on around it, and tells the player once, plainly, so they can fix the pack."""
    problems = c.problems
    if problems:
        return ["## Pack problems (tell the player once: `solo validate` in a terminal shows them)",
                *[f"- {problem}" for problem in problems], ""]
    else:
        return []


def _light_lines(c):
    """Darkness and the light the hero carries, when either matters."""
    state = c.state
    lit = state["light"]
    dark = c.adventure["scenes"][state["scene"]].get("dark", False)
    if lit:
        left = lit["lit_at"] + lit["burns"] - state["time"]
        return ["## Light", f"The hero's {lit['label'].lower()} burns: {_duration_text(left)} left.", ""]
    elif dark:
        return ["## Light", "It's dark here and nothing is burning: rolls that need sight get a bane, or can't be made. "
                "The hero can light something they carry (solo light).", ""]
    else:
        return []


def _travel(c, spec):
    spent = spec["time"] or c.adventure["move_time"]
    return f" (takes {packs.spent_text(spent)})" if spent else ""


def _duration_text(seconds):
    hours, minutes = divmod(max(0, int(seconds)) // 60, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min"


def _scene_check_lines(c):
    """How the scene check went when the hero came in, while they are still here."""
    move = next((e for e in reversed(c.events) if e["type"] == "move"), None)
    check = (move or {}).get("scene_check") or {}
    if move is None or move["to"] != c.state["scene"] or check.get("result", "expected") == "expected":
        return []
    elif check["result"] == "altered":
        return ["## Scene check: altered", "The scene isn't quite what the hero expects: change one detail of the text below (who is here, what they're doing, the weather, a door) and keep the rest.", ""]
    else:
        return ["## Scene check: interrupted", f"Something gets in first: {oracle.describe_event(check['event'])}. Open the scene with it, then carry on with the text below.", ""]


def _npc_line(c, npc_id):
    state = c.state
    npc = state["npcs"].get(npc_id)
    if npc is None:
        return f"- {npc_id}: (unknown)"
    profile = campaign.profile_of(c.adventure, state, npc_id)
    line = f"- {npc_id}: {npc['name']}" + (f", {profile['role']}" if profile.get("role") else "")
    line += " (a kind of foe: every fight brings new ones)" if profile.get("many") else f" ({npc['fate']}, {_attitude_name(npc['attitude'])})"
    promises = [f"{pid} {p['status']}" for pid, p in state["promises"].items() if p["npc"] == npc_id]
    if promises:
        line += f"; promises: {', '.join(promises)}"
    waiting = [cid for cid, k in state["consequences"].items() if k["npc"] == npc_id and k["status"] == "open"]
    if waiting:
        line += f"; waiting on them: {', '.join(waiting)}"
    if npc["memories"]:
        # The last few, not the last one: what matters most between them is rarely the latest.
        line += "; remembers: " + " / ".join(npc["memories"][-3:])
    heard = state["factions"].get(npc.get("faction") or "", {}).get("memories")
    if heard:
        line += f"; their people have heard: {heard[-1]}"
    return line + f". More: solo npc {npc_id}"


def _clock_line(c, clock_id):
    clock, spec = c.state["clocks"][clock_id], c._clock_spec(clock_id)
    line = f"- {clock['label']} ({clock_id}): {clock['value']}/{clock['segments']}"
    if clock.get("threat"):
        line += f", a threat: at {clock['segments']} it comes to pass" + (", then starts over" if clock["threat"]["recurring"] else "")
        if c.adventure["scenes"].get(c.state["scene"], {}).get("safe") and not clock["stopped"]:
            line += "; the hero is somewhere safe, so time here doesn't bring it closer"
    if clock["hidden"]:
        line += ", hidden from the player"
    if clock["stopped"]:
        line += ", stopped for good"
    elif clock["full"] and spec.get("at_full"):
        line += f". FULL: run scene {spec['at_full']} (solo move {spec['at_full']} --force \"{clock_id} filled\")"
    elif spec.get("while") and not packs.evaluate(spec["while"], c.state):
        line += f", not running (runs while {spec['while']})"
    reached = [s for s in spec.get("stages", []) if s.get("at", 0) <= clock["value"] and (s.get("note") or s.get("text"))]
    if reached:
        line += f". Reached {reached[-1]['at']}: {(reached[-1].get('note') or reached[-1].get('text')).rstrip('.')}"
    upcoming = [s for s in spec.get("stages", []) if s.get("at", 0) > clock["value"]]
    if upcoming:
        line += f". Next stage at {upcoming[0]['at']}"
    return line


def _progress_lines(state):
    """The progress tracks still open, as the rules count them: full boxes, and the ticks toward the next."""
    spec, lines = state["labels"]["progress"], []
    for track_id, track in state["progress"].items():
        if not track["ended"]:
            boxes, part = divmod(track["ticks"], spec["ticks"])
            rank = f" ({track['rank']} {track['kind']})" if track["rank"] else ""
            lines.append(f"- {track_id}: {track['name']}{rank}: {boxes} of {spec['boxes']} boxes" + (f" and {part} tick{'s' * (part != 1)}" if part else ""))
    return ["## Progress tracks", *lines, ""] if lines else []


def _pc_line(state):
    pc = state["pc"]
    tracks = ", ".join(_track_text(name, t) for name, t in pc["tracks"].items())
    line = f"{pc['name']}: {tracks}; conditions: {', '.join(pc['conditions']) or 'none'}"
    if pc["dead"]:
        line += "; DEAD"
    elif pc["dying"]:
        line += f"; DYING ({_tally(pc['dying'])})"
    if pc["marks"]:
        line += f"; marked for advancement: {', '.join(pc['marks'])}"
    return line + f"; carrying: {', '.join(pc['items']) or 'nothing'}; time elapsed: {_elapsed(state['time'])}"


def _track_text(name, track):
    """hp 9/14; momentum, which runs below zero, as +2 (up to 10, back to 2 after a burn)."""
    if "min" in track:
        return f"{name} {track['value']:+d} (to {track['max']}, resets to {track['reset']})"
    else:
        return f"{name} {track['value']}/{track['max']}"


def _skills_line(state):
    """The names to roll with: the hero's trained skills with their values, then the rest.
    GMs who know other games reach for "search" or "insight"; these are the ones that exist."""
    if state["family"] == "action-roll":
        pc = state["pc"]
        return "Stats: " + ", ".join(f"{name} {value}" for name, value in pc["attributes"].items()) + (f"; assets: {', '.join(pc['abilities'])}" if pc["abilities"] else "")
    skills = state["pc"]["skills"]
    trained = [f"{key} {s['value']}" for key, s in skills.items() if s["trained"]]
    other = [f"{key} {s['value']}" for key, s in skills.items() if not s["trained"]]
    return f"Skills: {', '.join(trained) or 'none trained'}" + (f"; untrained: {', '.join(other)}" if other else "")


def _push_options(c, event):
    if event["outcome"]["pushable"]:
        cost = c.system["push"].get("cost", "condition")
        if cost == "condition":
            taken = c.state["pc"]["conditions"]
            options = {"cost": "take a condition", "choose_from": [x for x in c.system["conditions"] if x not in taken]}
            ability = c._ability("push")
            if ability:
                options["or"] = f"{ability.get('name')}: pay {', '.join(f'{v} {t}' for t, v in ability['push'].items())} instead (solo push --sole-survivor)"
            return options
        else:
            return {"cost": cost}
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


def _now(c):
    """What stands after an action, when it matters: the fight, dying, the end."""
    state, pc = c.state, c.state["pc"]
    now = []
    if state["combat"]:
        fight = state["combat"]
        now.append(f"round {fight['round']}; " + ", ".join(_foe_text(f) for f in fight["foes"].values()))
        waiting = c.to_act()
        now.append(f"to act, in order: {', '.join(waiting)}" if waiting else "everyone has acted: deal the next round (solo fight --round)")
        if fight["incoming"]:
            hit = fight["incoming"]
            if pc["dying"]:
                now.append(f"incoming: {hit['damage']} from {hit['name']} ({hit['label']}); the hero is dying and can't defend: solo defend take (a failed death roll)")
            else:
                how = ("evade, parry or take" if hit.get("can_parry", True) else "evade or take (no parrying this)") if hit.get("can_defend", True) else "take only"
                now.append(f"incoming: {hit['damage']} from {hit['name']} ({hit['label']}); the player chooses: {how}")
        scene = c.adventure["scenes"].get(state["scene"], {})
        if scene.get("each_round"):
            # What this place asks every round (holding your breath under water), so it isn't forgotten.
            now.append(f"each round here: {scene['each_round']}")
    if pc["dying"]:
        now.append(f"{pc['name']} is dying: {_tally(pc['dying'])} (solo death-roll)")
    if state["ended"]:
        now.append(f"ended: {state['ended']['text']}")
    return now


def _tally(dying):
    s, f = dying["successes"], dying["failures"]
    return f"{s} success{'es' * (s != 1)}, {f} failure{'s' * (f != 1)}"


def _foe_text(foe):
    return f"{foe['name']} " + ("down" if foe["down"] else f"HP {foe['hp']}/{foe['max']}, armor {foe['armor']}")


def _hero_line(pc):
    """Ragna, Dwarf, Fighter, Adult: HP 14/14, WP 11/11"""
    who = ", ".join([pc["name"], *map(str, pc.get("info", {}).values())])
    return who + ": " + ", ".join(f"{t.upper()} {v['value']:+d}" if "min" in v else f"{t.upper()} {v['value']}/{v['max']}" for t, v in pc["tracks"].items())


def _attitude_name(value):
    return next((name for name, number in ATTITUDES.items() if number == value), str(value))


def _elapsed(seconds):
    days, rest = divmod(int(seconds), 86400)
    return f"{days}d {rest // 3600:02d}:{rest % 3600 // 60:02d}"


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
    sub.add_argument("--system", help="system pack name or folder (default: the only one)")
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
    sub.add_argument("--agent", help="turn: an agent other than the default (claude, codex, pi)")
    sub.add_argument("--turns", type=int, help="budget: GM turns a session may run (for an agent that doesn't say what a turn costs)")
    sub.add_argument("--reset", action="store_true", help="budget: start counting this campaign's session again")

    sub = command("ui", cmd_ui, "player-owned interface scales (JSON): Book independently of Table and settings")
    sub.add_argument("--book-scale", type=float, help="Book scale: 1, 1.25, 1.5, 1.75 or 2")
    sub.add_argument("--table-scale", type=float, help="Table and settings scale: 1, 1.25, 1.5, 1.75 or 2")
    sub.add_argument("--scale", type=float, help="set both scales explicitly (compatibility)")
    sub.add_argument("--honor-hyprland", choices=("on", "off"), help="use resolved Hyprland appearance for the Table and Settings")
    sub.add_argument("--hyprland-appearance", action="store_true", help="read resolved compositor appearance without changing settings")

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
