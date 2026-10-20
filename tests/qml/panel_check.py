"""Load the real Panel.qml and BarWidget.qml offscreen, against a real campaign.

    python3 tests/qml/panel_check.py <out folder>

Quickshell and omarchy-shell aren't here, so stand-ins take their place: Process runs
the plugin's actual bin/solo, FileView reads the actual files, and execDetached records
what the plugin would launch (GM turns, desktop effects) instead of launching it. Only
the layer-shell lines (anchors to screen edges, exclusive zone) are dropped from a copy
of Panel.qml. It prints QML errors and what was launched, and saves screenshots.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import Property, QFileSystemWatcher, QMetaObject, QObject, Q_ARG, QSize, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlEngine, qmlRegisterModule, qmlRegisterSingletonInstance, qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickView  # noqa: E402

LAUNCHED = []


def prop(kind, name, default, notify=None):
    """A read-write Qt property stored on the instance."""
    def get(self):
        return getattr(self, "_" + name, default)

    def put(self, value):
        setattr(self, "_" + name, value)
        signal = getattr(self, name + "Changed", None)
        if signal is not None:
            signal.emit()
    return Property(kind, get, put, notify=notify)


class Shell(QObject):
    screensChanged = Signal()
    screens = prop("QVariantList", "screens", [], notify=screensChanged)

    @Slot(str, result=str)
    def env(self, name):
        return os.environ.get(name, "")

    @Slot("QVariantList")
    def execDetached(self, command):
        LAUNCHED.append(list(command))


class Screen(QObject):
    nameChanged = Signal()
    name = prop(str, "name", "DP-1", notify=nameChanged)


class Hyprland(QObject):
    rawEvent = Signal(QObject)
    workspaces = prop("QVariantMap", "workspaces", {"values": []})

    @Slot(QObject, result=QObject)
    def monitorFor(self, screen):
        return None

    @Slot()
    def refreshMonitors(self):
        pass


class Collector(QObject):
    streamFinished = Signal()
    textChanged = Signal()
    waitForEnd = prop(bool, "waitForEnd", True)
    text = prop(str, "text", "", notify=textChanged)


class Process(QObject):
    exited = Signal(int, int, arguments=["exitCode", "exitStatus"])
    runningChanged = Signal()
    commandChanged = Signal()
    command = prop("QVariantList", "command", [], notify=commandChanged)
    environment = prop("QVariantMap", "environment", {})
    stdout = prop(QObject, "stdout", None)
    stderr = prop(QObject, "stderr", None)

    def _get_running(self):
        return getattr(self, "_running", False)

    def _set_running(self, value):
        if value and not self._get_running():
            self._running = True
            self.runningChanged.emit()
            QTimer.singleShot(0, self._run)

    running = Property(bool, _get_running, _set_running, notify=runningChanged)

    @Slot()
    def startDetached(self):
        LAUNCHED.append(list(self.command))

    def _run(self):
        done = subprocess.run([str(c) for c in self.command], capture_output=True, text=True)
        for stream, text in ((self.stdout, done.stdout), (self.stderr, done.stderr)):
            if stream is not None:
                stream.text = text
                stream.streamFinished.emit()
        self._running = False
        self.runningChanged.emit()
        self.exited.emit(done.returncode, 0)


class FileView(QObject):
    fileChanged = Signal()
    loaded = Signal()
    loadFailed = Signal()
    pathChanged = Signal()
    watchChanges = prop(bool, "watchChanges", False)
    printErrors = prop(bool, "printErrors", True)
    blockLoading = prop(bool, "blockLoading", False)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._changed)
        self._watcher.directoryChanged.connect(self._changed)

    def _get_path(self):
        return getattr(self, "_path", "")

    def _set_path(self, value):
        # A new path drops the old watch, as Quickshell's does: the old file going isn't news.
        watched = self._watcher.files() + self._watcher.directories()
        if watched:
            self._watcher.removePaths(watched)
        self._path = value
        self.pathChanged.emit()
        if value:
            self._watch()
            if self.blockLoading:
                self.reload()
            else:
                QTimer.singleShot(0, self.reload)

    path = Property(str, _get_path, _set_path, notify=pathChanged)

    def _watch(self):
        # The folder, for a file replaced by a rename; the file, for one written in place.
        for path in (Path(self._path).parent, Path(self._path)):
            if path.exists() and str(path) not in self._watcher.files() + self._watcher.directories():
                self._watcher.addPath(str(path))

    def _changed(self, _):
        self._watch()
        if self.watchChanges:
            self.fileChanged.emit()

    @Slot()
    def reload(self):
        try:
            self._text = Path(self._path).read_text(encoding="utf-8")
        except OSError:
            self.loadFailed.emit()
        else:
            self.loaded.emit()

    @Slot(result=str)
    def text(self):
        return self._text


class PanelWindow(QQuickItem):
    colorChanged = Signal()
    screenChanged = Signal()
    color = prop(QColor, "color", QColor("transparent"), notify=colorChanged)
    screen = prop(QObject, "screen", None, notify=screenChanged)


class FloatingWindow(QQuickItem):
    titleChanged = Signal()
    colorChanged = Signal()
    title = prop(str, "title", "", notify=titleChanged)
    color = prop(QColor, "color", QColor("transparent"), notify=colorChanged)
    minimumSize = prop(QSize, "minimumSize", QSize())


LAYER_SHELL = re.compile(r"^\s*(exclusionMode:.*|WlrLayershell\..*)$", re.M)
# The sidebar is sized by its screen edges in the shell; here, by the test window (taller to see all of the Table: PANEL_HEIGHT).
EDGES = "anchors { top: true; right: true; bottom: true }"
HEIGHT = int(os.environ.get("PANEL_HEIGHT", 1400))


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp())
    os.environ["XDG_STATE_HOME"] = str(work / "state")
    os.environ["SOLO_HOME"] = str(work / "games")
    os.environ["SOLO_SEED"] = "5"  # UI rolls must not randomly leave a Dragon's choice waiting.
    os.environ["XDG_RUNTIME_DIR"] = str(work / "run")
    # Begin runs `solo new --play`, which links solo and the skills into the home folder.
    os.environ["HOME"] = str(work / "home")
    os.environ["XDG_CACHE_HOME"] = str(work / "cache")
    os.environ["XDG_CONFIG_HOME"] = str(work / "config")  # Never use the player's local recordings.
    # Something to play the sounds with, so the plugin plays them.
    (work / "bin").mkdir()
    # Child CLI commands use this interpreter, not a host version-manager shim.
    (work / "bin" / "python3").symlink_to(Path(sys.executable).resolve())
    (work / "bin" / "pw-play").write_text("#!/bin/sh\nexit 0\n")
    (work / "bin" / "pw-play").chmod(0o755)
    os.environ["PATH"] = f"{work / 'bin'}:{os.environ['PATH']}"
    import scenario
    # The test rules where a player's pack built from their book goes, so New adventure offers heroes.
    scenario.install_rules(work / "games")
    root = scenario.play(work)
    # The campaign (its hero died) is the current one, so Home lists it and the Hall remembers the hero.
    plugin = work / "plugin"
    plugin.mkdir()
    for name in ("book", "bin", "solo", "packs", "examples", "skills", "templates", "Theme.qml", "WorkspacePin.qml", "SettingsView.qml", "HyprlandAppearance.qml"):
        (plugin / name).symlink_to(REPO / name)
    (plugin / "Panel.qml").write_text(LAYER_SHELL.sub("", (REPO / "Panel.qml").read_text()).replace(EDGES, f"width: 360; height: {HEIGHT}"))
    shutil.copy(REPO / "BarWidget.qml", plugin / "BarWidget.qml")
    (work / "state" / "solo").mkdir(parents=True, exist_ok=True)
    (work / "state" / "solo" / "current").write_text(str(root) + "\n")

    app = QGuiApplication(sys.argv)
    shell = Shell()  # held here for the run: QML keeps no reference of its own to a singleton instance
    hyprland = Hyprland()
    qmlRegisterSingletonInstance(QObject, "Quickshell", 1, 0, "Quickshell", shell)
    qmlRegisterSingletonInstance(QObject, "Quickshell.Hyprland", 1, 0, "Hyprland", hyprland)
    qmlRegisterType(PanelWindow, "Quickshell", 1, 0, "PanelWindow")
    qmlRegisterType(FloatingWindow, "Quickshell", 1, 0, "FloatingWindow")
    qmlRegisterType(Process, "Quickshell.Io", 1, 0, "Process")
    qmlRegisterType(Collector, "Quickshell.Io", 1, 0, "StdioCollector")
    qmlRegisterType(FileView, "Quickshell.Io", 1, 0, "FileView")
    qmlRegisterModule("Quickshell.Wayland", 1, 0)

    errors = []
    engine = QQmlEngine()  # one engine: the Quickshell stand-in is a single instance
    engine.addImportPath(str(HERE / "stubs"))
    engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))

    def load(name, width, height):
        view = QQuickView(engine, None)
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        view.resize(width, height)
        view.setSource(QUrl.fromLocalFile(str(plugin / name)))
        if view.status() == QQuickView.Error:
            errors.extend(e.toString() for e in view.errors())
            return None
        view.show()
        return view

    def wait(ms):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.start(ms)
        while timer.isActive():
            app.processEvents()

    panel = load("Panel.qml", 360, HEIGHT)
    bar = load("BarWidget.qml", 60, 30)
    if panel is None or bar is None:
        print("\n".join(errors))
        return 1
    item = panel.rootObject()
    wait(800)
    item.open(json.dumps({"view": "table"}))
    wait(1500)
    panel.grabWindow().save(str(out / "table.png"))
    errors += themed_surfaces(item, engine, wait)
    errors += workspace_pinning(item, panel, out, engine, wait)
    import header_check
    errors += header_check.check(item, panel, out, engine, wait)
    import scaling_panel_check
    errors += scaling_panel_check.check(item, panel, out, work, engine, wait, Process)
    import hyprland_appearance_check
    errors += hyprland_appearance_check.check(item, panel, out, work, wait, Process)
    item.show("home")
    wait(2500)
    panel.grabWindow().save(str(out / "home.png"))
    item.setProperty("deleting", str(root))  # the card asking "delete for good?"
    wait(300)
    panel.grabWindow().save(str(out / "home-delete.png"))
    item.setProperty("deleting", "")
    item.open(json.dumps({"book": True}))
    wait(1500)
    errors += begin_and_ask(item, panel, out, work, wait)
    errors += an_x_card(item, panel, out, work, wait)
    errors += recorded_audio(item, work, wait)
    errors += desk_moments(item, panel, out, work, wait)
    errors += deleted_while_dying(item, bar, work, wait)
    errors += a_game_of_moves(item, panel, out, work, wait)
    errors += magic_and_dragons(item, panel, out, work, wait)
    print("bar tooltip:", bar.rootObject().tooltip())
    print("launched:")
    for command in LAUNCHED:
        print("  ", " ".join(str(c) for c in command[1:]))
    if errors:
        print("QML errors:\n  " + "\n  ".join(errors))
        return 2
    return 0


def themed_surfaces(item, engine, wait):
    """The Table must pass complete native border specs through, not just a color."""
    surface = item.findChild(QObject, "tableSurface")
    borders = engine.singletonInstance("qs.Commons", "Border")
    def spec():
        value = surface.property("borderSpec")
        return value.toVariant() if hasattr(value, "toVariant") else value
    assert spec()["gradient"]["enabled"]
    assert spec()["gradient"]["angle"] == 35
    assert len(spec()["gradient"]["colors"]) == 2
    assert spec()["widths"] == {"top": 2, "right": 2, "bottom": 2, "left": 2}
    borders.setProperty("popupWidths", {"top": 0, "right": 3, "bottom": 2, "left": 1})
    wait(20)
    assert spec()["widths"] == {"top": 0, "right": 3, "bottom": 2, "left": 1}
    borders.setProperty("popupWidths", {"top": 2, "right": 2, "bottom": 2, "left": 2})
    return []
def workspace_pinning(item, panel, out, engine, wait):
    """The real header button, shell toggle state, and independent Book/GM state."""
    import workspace_check
    problems = []
    pin = item.findChild(QObject, "workspacePin")
    window = item.findChild(QObject, "tableWindow")
    button = item.findChild(QObject, "workspacePinButton")
    assert pin is not None and window is not None and button is not None
    screen = Screen(window)  # held by the window for the rest of the check
    second_screen = Screen(window)
    second_screen.setProperty("name", "DP-2")
    pin.setProperty("hyprland", workspace_check.snapshot(engine))
    window.setProperty("screen", screen)
    pin.setProperty("screens", [screen, second_screen])
    item.open('{"view":"table"}')
    wait(100)
    if not item.property("opened") or button.property("text") != chr(0xF0931):
        problems.append("the Table did not start unpinned")
    QMetaObject.invokeMethod(button, "clicked")
    wait(100)
    if not button.property("selected") or pin.property("workspaceId") != 3 or button.property("text") != chr(0xF0403):
        problems.append("the header's Pin button did not pin the Table")
    panel.grabWindow().save(str(out / "table-pinned.png"))
    def variant(value):
        return value.toVariant() if hasattr(value, "toVariant") else value

    turn = variant(item.property("turn"))
    item.setProperty("turn", {"status": "writing", "text": "A GM turn in progress"})
    away = workspace_check.snapshot(engine, active=4)
    pin.setProperty("hyprland", away)
    wait(100)
    if item.property("opened") or window.property("visible") or not pin.property("requested"):
        problems.append("the hidden Table still reported open to the shell, or lost its requested-open state")
    if variant(item.property("turn")).get("status") != "writing":
        problems.append("changing workspace interrupted the GM")
    item.setProperty("turn", turn)
    item.open('{"book":true}')
    wait(200)
    if not item.property("bookOpen") or item.property("opened") or away.property("calls").toVariant():
        problems.append("opening the Book summoned the pinned Table's workspace")
    item.open('{"view":"table"}')  # what the shell's toggle does when opened is false
    if away.property("calls").toVariant() != [3]:
        problems.append("the shell could not summon a pinned Table from another workspace")
    pin.setProperty("hyprland", workspace_check.snapshot(engine))
    wait(100)
    if not item.property("opened"):
        problems.append("the Table did not return on its workspace")
    item.close()
    if item.property("opened") or not pin.property("pinned"):
        problems.append("closing the Table did not keep its pin")
    item.open('{"view":"table"}')
    pin.setProperty("hyprland", workspace_check.snapshot(engine, active=4, moved=True))
    wait(100)
    if not item.property("opened") or window.property("screen").property("name") != "DP-2":
        problems.append("the Table did not follow its pinned workspace to another screen")
    QMetaObject.invokeMethod(button, "clicked")
    wait(100)
    if window.property("screen").property("name") != "DP-2":
        problems.append("unpinning jumped back to the old screen")
    pin.setProperty("hyprland", workspace_check.snapshot(engine, active=4))
    wait(100)
    if not item.property("opened") or pin.property("pinned"):
        problems.append("unpinning did not restore the original global behavior")
    item.setProperty("bookOpen", False)
    return problems


def begin_and_ask(item, panel, out, work, wait):
    """New adventure and the oracle from the panel, with what the player typed starting
    with a dash: it has to reach the engine as words, never as options."""
    problems = []
    item.setProperty("pickedAdventure", "red-tusk")  # the first of the bundled adventures is the Ironsworn one
    item.show("new")
    wait(2500)
    panel.grabWindow().save(str(out / "new.png"))
    item.setProperty("heroName", "-Brokk")
    item.setProperty("tone", "-grim, and quiet")
    item.begin()
    wait(3000)
    if item.property("error"):
        return [f"Begin failed: {item.property('error')}"]
    game = Path((work / "state" / "solo" / "current").read_text().strip())
    state = json.loads((game / "state.json").read_text())
    if (state["pc"]["name"], state["prefs"]["tone"]) != ("-Brokk", "-grim, and quiet"):
        problems.append(f"Begin passed {state['pc']['name']!r} and {state['prefs']['tone']!r}")
    item.open(json.dumps({"view": "table"}))
    wait(1500)
    item.findChild(QObject, "question").setProperty("text", "-is anyone watching?")
    item.askOracle()
    wait(1500)
    log = json.loads((game / "state.json").read_text())["log"]
    if not any('"-is anyone watching?"' in entry["text"] for entry in log):
        problems.append(f"the oracle didn't get the question: {item.property('error') or log[-1]['text']}")
    panel.grabWindow().save(str(out / "table-alive.png"))
    return problems


def an_x_card(item, panel, out, work, wait):
    """The Book's cut: with the GM's last message on the page, the panel's words become a note and a line, `solo strike`
    runs, and the GM is asked to carry on without it."""
    from solo import campaign
    game = Path((work / "state" / "solo" / "current").read_text().strip())
    with campaign.session(game) as c:
        c.say("A spider the size of a dog drops onto the road. What do you do?")
    problems = []
    item.setProperty("agentInfo", {"agent": "claude", "book": True})  # a default agent that can write in the Book
    book = item.findChild(QObject, "book")
    for _ in range(20):  # the Book reads state.json when the file changes: give it a moment
        wait(300)
        if book is not None and book.property("canCut"):
            break
    if book is None or not book.property("canCut"):
        return [f"the Book doesn't offer the cut with the GM's message on the page (found: {book is not None}"
                + (f", agent {book.property('agent').toVariant()}, busy {book.property('busy')}, dead {book.property('dead')})" if book is not None else ")")]
    book.setProperty("cutting", True)
    item.findChild(QObject, "cutInput").setProperty("text", "no spiders")
    LAUNCHED.clear()
    QMetaObject.invokeMethod(book, "cutIt", Q_ARG("QVariant", "line"))
    wait(2500)
    state = json.loads((game / "state.json").read_text())
    if len(state["struck"]) != 1 or state["prefs"]["lines"] != ["no spiders"]:
        problems.append(f"the cut didn't reach the engine: {item.property('error') or state['struck']}, {state['prefs']}")
    said = [" ".join(str(a) for a in command) for command in LAUNCHED]
    if not any("gm turn" in line for line in said):
        problems.append(f"the GM wasn't asked to carry on after the cut (launched: {said})")
    return problems


def recorded_audio(item, work, wait):
    """Real animation landings play once; page volume and mute reach the player."""
    from helpers import Dice
    from solo import campaign
    game = Path((work / "state" / "solo" / "current").read_text().strip())
    old_sounds = item.property("sounds").toVariant()
    old_effects = item.property("effects").toVariant()
    old_book = item.property("bookOpen")
    parts = {name: f"/recorded sounds/{name}.wav" for name in ("dice-roll", "dice-roll-short", "dice-land")}
    item.setProperty("sounds", {**old_sounds, "split_dice": True, "sounds": {**old_sounds["sounds"], **parts}})
    item.setProperty("effects", {**old_effects, "sound": True})
    problems = []

    def played(name):
        return sum(bool(command) and command[-1] == parts[name] for command in LAUNCHED)

    def throw():
        LAUNCHED.clear()
        with campaign.session(game) as c:
            event = c.check("awareness", rng=Dice(10, 3, 3, 3, 3))
        wait(250)
        return event["seq"]

    item.setProperty("bookOpen", False)
    wait(100)
    throw()
    if played("dice-roll-short") != 1 or played("dice-land"):
        problems.append("recorded dice: Table must start only its short rolling clip")
    wait(1250)
    if played("dice-land") != 1:
        problems.append("recorded dice: Table landing must play once")
    wait(900)
    if played("dice-land") != 1:
        problems.append("recorded dice: hidden Book duplicated a Table landing")

    item.setProperty("bookOpen", True)
    wait(100)
    seq = throw()
    if played("dice-roll") != 1 or played("dice-land"):
        problems.append("recorded dice: Book must start only its full rolling clip")
    wait(1050)
    QMetaObject.invokeMethod(item, "diceLanded", Q_ARG("QVariant", seq), Q_ARG("QVariant", True), Q_ARG("QVariant", str(game) + "-old"))
    if played("dice-land"):
        problems.append("recorded dice: sibling animation or stale campaign landed early")
    wait(1350)
    if played("dice-land") != 1:
        problems.append("recorded dice: Book impact must follow its actual landing")
    QMetaObject.invokeMethod(item, "diceLanded", Q_ARG("QVariant", seq), Q_ARG("QVariant", True), Q_ARG("QVariant", str(game)))
    if played("dice-land") != 1:
        problems.append("recorded dice: repeated signal duplicated an impact")
    combined = {old_sounds["sounds"]["dice"], old_sounds["sounds"]["dice-short"]}
    if any(command and command[-1] in combined for command in LAUNCHED):
        problems.append("recorded dice: combined synthesis played over the recordings")

    LAUNCHED.clear()
    QMetaObject.invokeMethod(item, "sound", Q_ARG("QVariant", "page"), Q_ARG("QVariant", 0))
    if len(LAUNCHED) != 1 or "--volume=0.75" not in LAUNCHED[0]:
        problems.append("page turn: quieter player command was not used")
    item.setProperty("effects", {**old_effects, "sound": False})
    throw()
    wait(2400)
    if any(played(name) for name in parts):
        problems.append("recorded dice: mute must suppress rolling and landing")

    item.setProperty("effects", {**old_effects, "sound": True})
    throw()
    item.setProperty("campaign", "")
    wait(2400)
    if played("dice-land"):
        problems.append("recorded dice: campaign switch did not cancel the pending impact")
    item.setProperty("campaign", str(game))
    wait(400)
    if played("dice-land"):
        problems.append("recorded dice: campaign reload replayed an old landing")
    item.setProperty("sounds", old_sounds)
    item.setProperty("effects", old_effects)
    item.setProperty("bookOpen", old_book)
    return problems


def desk_moments(item, panel, out, work, wait):
    """With the Book open, a Dragon, a blow that leaves the hero dying, a Demon on a death
    roll and death: each has to set off its flash, hold or sound, timed to the dice."""
    from helpers import Dice
    from solo import campaign
    game = Path((work / "state" / "solo" / "current").read_text().strip())
    item.open(json.dumps({"book": True}))
    wait(1500)
    problems = []

    def expect(what, act, wanted, shot=None):
        LAUNCHED.clear()
        with campaign.session(game) as c:
            act(c)
        if shot:  # the Table's roll, still tumbling, then landed
            wait(250)
            panel.grabWindow().save(str(out / f"{shot}-tumbling.png"))
        wait(1500)
        if shot:
            panel.grabWindow().save(str(out / f"{shot}.png"))
        said = [" ".join(str(a) for a in command) for command in LAUNCHED]
        for want in wanted:
            if not any(want in line for line in said):
                problems.append(f"{what}: nothing launched with {want!r} (launched: {said})")

    expect("a Dragon", lambda c: c.check("awareness", rng=Dice(1, 3, 3, 3, 3)),
           ["pw-play " + str(work / "cache"), "/dice-", "desk --after 1.94 flash dragon", "sleep \"$0\"; exec \"$@\" 1.94 pw-play", "/dragon-"], shot="table-dragon")
    expect("a blow to dying", lambda c: c.wound("hero", "40", "a rockfall", armor=False, rng=Dice()),
           ["desk flash hit", "/hit-", "desk dying on 0", "/heartbeat-"], shot="table-dying")
    expect("a Demon on a death roll", lambda c: c.death_roll(rng=Dice(20, 3, 3, 3)),
           ["desk --after 1.94 flash demon", "desk --after 1.94 dying on 2", "/demon-"])
    expect("death", lambda c: c.death_roll(rng=Dice(20, 3, 3, 3)), ["desk --after 1.94 death", "/bell-"])
    return problems



def a_game_of_moves(item, panel, out, work, wait):
    """Ironsworn from the Table, with no book: begin The Bell Under the Hill with a pre-made hero, start
    a vow, roll a move with a stat and a progress roll from the buttons, and burn momentum on a miss that
    could still be saved. The Table offers moves and tracks where a game of skills offers skills."""
    from helpers import Dice
    from solo import campaign
    problems = []
    item.setProperty("pickedAdventure", "bell-under-the-hill")
    item.setProperty("pickedHero", "hrafna")
    item.show("new")
    wait(2500)
    panel.grabWindow().save(str(out / "new-ironsworn.png"))
    item.begin()
    wait(3000)
    if item.property("error"):
        return [f"Begin (Ironsworn) failed: {item.property('error')}"]
    game = Path((work / "state" / "solo" / "current").read_text().strip())
    item.open(json.dumps({"view": "table"}))
    wait(1500)
    panel.grabWindow().save(str(out / "table-ironsworn.png"))

    def state():
        return json.loads((game / "state.json").read_text())

    item.findChild(QObject, "trackName").setProperty("text", "-Silence the bell")
    item.startTrack()
    wait(1500)
    tracks = {t["name"] for t in state()["progress"].values()}
    if "-Silence the bell" not in tracks:
        problems.append(f"the Table didn't start the vow: {item.property('error') or tracks}")
    item.rollMove("face_danger", "edge", "")
    wait(1500)
    if state()["last_check"]["type"] != "act" or state()["last_check"]["stat"] != "edge":
        problems.append(f"the Table's move wasn't rolled: {item.property('error') or state()['last_check']}")
    item.setProperty("adds", 1)
    item.pickMove("gather_information")  # one stat: it rolls at once, with the add
    wait(1500)
    if state()["last_check"]["outcome"]["adds"] != 1:
        problems.append("the adds didn't reach the move")
    item.pickMove("face_danger")  # five stats: it waits for one
    wait(300)
    if item.property("pickedMove") != "face_danger":
        problems.append("a move with a choice to make didn't wait for it")
    panel.grabWindow().save(str(out / "table-ironsworn-choosing.png"))
    item.setProperty("pickedMove", "")
    with campaign.session(game) as c:
        c.commit({"pc": {"momentum": "+7"}})
        c.act("face_danger", stat="edge", rng=Dice(1, 5, 8))  # a miss that momentum could still save
    wait(1500)
    if not state()["burn"]:
        problems.append("the state offers no burn for a miss momentum could save")
    panel.grabWindow().save(str(out / "table-ironsworn-burn.png"))
    item.act(["burn"], "roll", None)
    wait(1500)
    if state()["last_check"]["type"] != "burn" or state()["pc"]["tracks"]["momentum"]["value"] != 2:
        problems.append("the Table's burn didn't burn momentum")
    item.rollTrack(next(t for t in item.openTracks().toVariant() if t["kind"] == "vow"))
    wait(1500)
    if state()["last_check"].get("track") is None:
        problems.append(f"the Table's progress roll wasn't made: {item.property('error') or state()['last_check']}")
    panel.grabWindow().save(str(out / "table-ironsworn-vow.png"))
    return problems


def magic_and_dragons(item, panel, out, work, wait):
    """A hero who casts and has heroic abilities, in a fight where a Dragon is the player's choice: the Table's buttons cast a
    spell at a power level and prepare another, switch an ability on for a roll, answer a Dragon, and mend a broken weapon.
    The made-up rules of tests/fixtures/dragons; the buttons only run `solo`, so what is checked is what the engine then holds."""
    from helpers import DRAGONS, RED_TUSK, Dice
    from solo import campaign
    problems = []
    sheet = work / "arcane.toml"
    sheet.write_text('name = "Sibyl"\nitems = ["long_axe", "staff", "torch", "rope", "6 silver"]\n'
                     'abilities = ["Heavy swing", "Quickdraw", "Mender", "Far gaze"]\n'
                     'spells = ["Spark", "Ember", "Mend", "Ward", "Gale", "Lash"]\nprepared = ["Ember", "Mend", "Ward"]\n'
                     '[info]\nkin = "Elf"\nprofession = "Mage"\nage = "Adult"\n'
                     '[attributes]\nstr = 15\ncon = 12\nagl = 11\nint = 5\nwil = 13\ncha = 10\n'
                     '[skills]\nelementalism = 12\nanimism = 10\naxes = 12\nevade = 12\n[tracks]\nhp = 12\nwp = 13\n')
    game = work / "games" / "campaigns" / "arcane"
    campaign.create(game, DRAGONS, RED_TUSK, sheet)
    campaign.set_current(game)
    with campaign.session(game) as c:
        c.fight(["orc_leader", "cultist"], rng=Dice(1, 2, 3))
    item.open(json.dumps({"view": "table"}))
    wait(1500)

    def state():
        return json.loads((game / "state.json").read_text())

    def wp():
        return state()["pc"]["tracks"]["wp"]["value"]

    sheet_view = state()
    if [s["name"] for s in sheet_view["magic"]["spells"]] != ["Ember", "Gale", "Mend", "Ward", "Lash", "Spark"]:
        problems.append(f"the spells aren't the hero's, spells before tricks: {sheet_view['magic']}")
    if sorted(a["use"] for a in sheet_view["abilities"] if a["use"]) != ["alone", "attack", "rest", "round"]:
        problems.append(f"the abilities aren't sorted into where they are asked for: {sheet_view['abilities']}")
    panel.grabWindow().save(str(out / "table-magic.png"))

    item.setProperty("power", 2)
    item.cast(next(s for s in item.ready().toVariant() if s["name"] == "Ember"), False)
    wait(1500)
    cast = [e for e in state()["log"] if e["type"] == "spell"]
    if item.property("error") or not cast or wp() != 7:
        problems.append(f"the Table's cast didn't cost two levels of Ember: {item.property('error') or wp()}")
    if item.property("power") != 1:
        problems.append("the power level didn't go back to 1 after the cast")

    item.toggleRider("Quickdraw")
    item.act(["fight", "--round"] + list(item.useArgs("round", "").toVariant()), "fight", None)
    wait(1500)
    if item.property("error") or wp() != 5 or item.property("riders").toVariant() != ["Quickdraw"]:
        problems.append(f"Quickdraw wasn't paid with the new round: {item.property('error') or wp()}")
    item.spent("round", "")
    if item.property("riders").toVariant() != []:
        problems.append("a switched-on ability stayed on after the roll it was for")

    item.prepare(next(s for s in item.grimoire().toVariant() if s["name"] == "Lash"))  # three are ready, the most there can be
    wait(300)
    if item.property("preparing") != "Lash":
        problems.append("a spell to prepare at the limit didn't ask which to put aside")
    panel.grabWindow().save(str(out / "table-magic-preparing.png"))
    item.putAside(next(s for s in item.ready().toVariant() if s["name"] == "Ward"))
    wait(1500)
    if "Lash" not in state()["pc"]["prepared"] or "Ward" in state()["pc"]["prepared"]:
        problems.append(f"the Table's prepare didn't swap the spells: {item.property('error') or state()['pc']['prepared']}")

    with campaign.session(game) as c:
        c.attack("cultist", weapon="long_axe", rng=Dice(1))  # a natural 1: a Dragon, which waits for the player
    wait(1500)
    if not state()["choice"]:
        problems.append("a Dragon on the attack didn't wait for a choice")
    options = [o["label"] for o in item.dragonOptions().toVariant()]
    if "Double damage" not in options or not any(o.startswith("Attack ") for o in options):
        problems.append(f"the Dragon's choices aren't offered, a free attack for the other foe included: {options}")
    panel.grabWindow().save(str(out / "table-dragon-choice.png"))
    item.act(["dragon", "double"], "dragon", None)
    wait(1500)
    if state()["choice"] or item.property("error"):
        problems.append(f"the Dragon's choice wasn't answered: {item.property('error') or state()['choice']}")

    with campaign.session(game) as c:
        c.append("durability", weapon="long_axe", label="Long axe", how="parry", damaged=True, broke=True, cause=None)
    wait(1500)
    axe = next(w for w in state()["kit"]["weapons"] if w["id"] == "long_axe")
    if axe["condition"] != "broken" or [w["id"] for w in item.worn().toVariant()] != ["long_axe"]:
        problems.append(f"a broken weapon isn't shown as broken: {axe}")
    panel.grabWindow().save(str(out / "table-broken-axe.png"))
    item.act(["repair", "long_axe", "--artisan"], "gear", None)
    wait(1500)
    if state()["pc"].get("damaged") or item.property("error"):
        problems.append(f"the Table's mend didn't mend it: {item.property('error') or state()['pc'].get('damaged')}")

    item.act(["ability", "--cost", "2", "--", "Far gaze"], "ability", None)
    wait(1500)
    if item.property("error") or wp() != 3:
        problems.append(f"an ability that costs what the hero chooses wasn't paid: {item.property('error') or wp()}")
    with campaign.session(game) as c:
        c.end_fight()
    wait(1000)
    item.toggleRider("Mender")
    item.act(["rest", "stretch"] + list(item.useArgs("rest", "stretch").toVariant()), "rest", None)
    wait(1500)
    if item.property("error") or wp() != 1 and not any(e["type"] == "ability" for e in state()["log"]):
        problems.append(f"Mender wasn't paid with the rest: {item.property('error') or wp()}")
    panel.grabWindow().save(str(out / "table-magic-rested.png"))
    return problems


def deleted_while_dying(item, bar, work, wait):
    """A campaign deleted while its hero lies dying: the d20 stops pulsing and the red lets
    go. Deleting takes `current` away before the folder, so the old state.json is never
    seen going; the game has to go with its campaign."""
    from helpers import Dice
    from solo import campaign
    solo = [str(REPO / "bin" / "solo")]
    game = work / "games" / "campaigns" / "doomed"
    subprocess.run(solo + ["new", "red-tusk", "--dir", str(game)], check=True, capture_output=True)
    wait(1500)
    with campaign.session(game) as c:
        c.wound("hero", "40", "a rockfall", armor=False, rng=Dice())
    wait(1500)
    problems = [] if bar.rootObject().property("dying") else ["the bar didn't see the hero dying before the delete"]
    LAUNCHED.clear()
    subprocess.run(solo + ["delete", str(game), "--yes"], check=True, capture_output=True)  # what the panel's Delete runs
    wait(1500)
    if bar.rootObject().property("dying") or bar.rootObject().property("pc") is not None:
        problems.append("the bar still shows the deleted campaign's dying hero")
    said = [" ".join(str(a) for a in command) for command in LAUNCHED]
    if not any("desk dying off" in line for line in said):
        problems.append(f"deleting a dying hero's campaign didn't let the red go (launched: {said})")
    if item.property("game") is not None:
        problems.append("the panel still holds the deleted campaign's game")
    return problems

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
