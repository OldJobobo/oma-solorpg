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
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import Property, QCoreApplication, QEventLoop, QFileSystemWatcher, QMetaObject, QObject, QPointF, Q_ARG, QSize, Qt, QTimer, QUrl, Signal, Slot  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlEngine, qmlRegisterModule, qmlRegisterSingletonInstance, qmlRegisterType  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickView, QQuickWindow  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

LAUNCHED = []


def button(item, text):
    """The visible button under `item` whose text starts with `text`. A Repeater's items are in the tree of items, not
    of objects, so they are looked for there."""
    for child in item.childItems():
        if child.property("bordered") is not None and str(child.property("text") or "").startswith(text) and child.isVisible():
            return child
        found = button(child, text)
        if found is not None:
            return found
    return None


def labelled(item, text):
    """The visible item under `item` whose text is `text` (a heading, a line)."""
    for child in item.childItems():
        if child.property("text") == text and child.isVisible():
            return child
        found = labelled(child, text)
        if found is not None:
            return found
    return None


def empty_flows(item):
    """The visible Flows under `item` with nothing in them: no height, and still a gap of spacing round each."""
    found = []
    for child in item.childItems():
        if child.metaObject().className() == "QQuickFlow" and child.isVisible() and child.height() == 0:
            found.append(child)
        found += empty_flows(child)
    return found


def trouble(item):
    """What the Table says went wrong, from its commands and from its reads ("" when nothing did)."""
    return "\n".join(t for t in (item.property(name).toVariant()["text"] for name in ("error", "queryError")) if t)


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
    @Slot(str, result=str)
    def env(self, name):
        return os.environ.get(name, "")

    @Slot("QVariantList")
    def execDetached(self, command):
        LAUNCHED.append(list(command))


class Collector(QObject):
    streamFinished = Signal()
    textChanged = Signal()
    waitForEnd = prop(bool, "waitForEnd", True)
    text = prop(str, "text", "", notify=textChanged)


class Process(QObject):
    # While `hold` is set, a process that starts stays running until release(), as a slow one would.
    hold = False
    held = []
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
        if Process.hold:
            Process.held.append(self)
            return
        try:
            done = subprocess.run([str(c) for c in self.command], capture_output=True, text=True)
        except OSError:
            # A program that can't start, as Quickshell has it: no streams and no exit, only `running` going false.
            self._running = False
            self.runningChanged.emit()
            return
        # Quickshell's event loop turns while a command runs, and solo writes state.json some milliseconds before
        # it ends: the FileViews have read what it wrote by the time its exit comes, so a Repeater's delegate that
        # ran the command (a parry, gone with the blow it answered) may be gone too.
        settle()
        for stream, text in ((self.stdout, done.stdout), (self.stderr, done.stderr)):
            if stream is not None:
                stream.text = text
                stream.streamFinished.emit()
        # Quickshell's order: the streams end, then the exit (no longer running), then `running` changes.
        self._running = False
        self.exited.emit(done.returncode, 0)
        self.runningChanged.emit()


def settle():
    """What the files a command wrote have to say (the watchers' news, and the reads it sets off) is heard now."""
    end = time.monotonic() + 0.05
    while time.monotonic() < end:
        QCoreApplication.processEvents(QEventLoop.AllEvents, 10)


def release():
    """The processes Process.hold kept running end, in the order they started."""
    Process.hold = False
    held, Process.held = Process.held, []
    for process in held:
        process._run()


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
        # Through a function, not the bound method: a FileView at the root of a component of its own that declares
        # properties (book/CurrentCampaign.qml) gets a metaobject from QML, and a slot PySide adds to it never runs.
        self._watcher.fileChanged.connect(lambda path: self._changed(path))
        self._watcher.directoryChanged.connect(lambda path: self._changed(path))

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
        self._watch()  # as Quickshell's does: every reload sets the watch again
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
    color = prop(QColor, "color", QColor("transparent"), notify=colorChanged)


class FloatingWindow(QQuickWindow):
    """A window of its own, as Quickshell's is. Hiding a window hides nothing in it as far as QML can tell, so the
    Book has to stop its own animations when it is shut; an Item in its place hid them, and hid that they ran."""
    minimumSize = prop(QSize, "minimumSize", QSize())
    implicitWidth = prop(float, "implicitWidth", 0)
    implicitHeight = prop(float, "implicitHeight", 0)

    def showEvent(self, event):
        self.resize(int(self.implicitWidth) or 1100, int(self.implicitHeight) or 860)
        super().showEvent(event)


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
    os.environ["XDG_RUNTIME_DIR"] = str(work / "run")
    # Begin runs `solo new --play`, which links solo and the skills into the home folder.
    os.environ["HOME"] = str(work / "home")
    os.environ["XDG_CACHE_HOME"] = str(work / "cache")
    # Something to play the sounds with, so the plugin plays them.
    (work / "bin").mkdir()
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
    for name in ("book", "bin", "solo", "packs", "examples", "skills", "templates"):
        (plugin / name).symlink_to(REPO / name)
    (plugin / "Panel.qml").write_text(LAYER_SHELL.sub("", (REPO / "Panel.qml").read_text()).replace(EDGES, f"width: 360; height: {HEIGHT}"))
    shutil.copy(REPO / "BarWidget.qml", plugin / "BarWidget.qml")
    (work / "state" / "solo").mkdir(parents=True, exist_ok=True)
    (work / "state" / "solo" / "current").write_text(str(root) + "\n")

    app = QGuiApplication(sys.argv)
    shell = Shell()  # held here for the run: QML keeps no reference of its own to a singleton instance
    qmlRegisterSingletonInstance(QObject, "Quickshell", 1, 0, "Quickshell", shell)
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
    errors += a_cut_while_another_is_picked(item, work, wait)
    errors += a_turn_that_never_starts(item, panel, out, work, wait)
    errors += no_agent_yet(item, work, wait)
    errors += desk_moments(item, panel, out, work, wait)
    errors += deleted_while_dying(item, bar, work, wait)
    errors += a_game_of_moves(item, panel, out, work, wait)
    errors += magic_and_dragons(item, panel, out, work, wait)
    errors += errors_by_source(item, work, wait)
    errors += commands_wait_their_turn(item, panel, work, wait)
    errors += a_parry_and_what_waits(item, panel, work, wait)
    errors += the_first_game(load, work, wait)
    errors += quiet_text_reads(engine, item, panel, out, wait)
    errors += by_keyboard(item, panel, wait)
    errors += adventures_not_ready(item, panel, out, wait)
    errors += a_campaign_gone(item, panel, out, work, wait)
    print("bar tooltip:", bar.rootObject().tooltip())
    print("launched:")
    for command in LAUNCHED:
        print("  ", " ".join(str(c) for c in command[1:]))
    if errors:
        print("QML errors:\n  " + "\n  ".join(errors))
        return 2
    return 0


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
    name = next(f for f in panel.contentItem().findChildren(QQuickItem) if str(f.property("placeholderText") or "").startswith("Name"))
    # Begin opens the Book, here where omarchy-shell isn't there for `solo new --play` to bring it up (as with no
    # agent set up, or one that runs in a terminal), so its word on the GM is read.
    item.setProperty("bookOpen", False)
    panel.requestActivate()  # the shell gives the Table the keyboard when a field is clicked
    wait(100)
    name.forceActiveFocus()
    QTest.keyClick(panel, Qt.Key_Return)  # Enter in the hero's name begins
    wait(3000)
    if trouble(item):
        return [f"Begin failed: {trouble(item)}"]
    if not item.property("bookOpen"):
        problems.append("Begin didn't open the Book when `solo new --play` didn't")
    game = Path((work / "state" / "solo" / "current").read_text().strip())
    state = json.loads((game / "state.json").read_text())
    if (state["pc"]["name"], state["prefs"]["tone"]) != ("-Brokk", "-grim, and quiet"):
        problems.append(f"Begin passed {state['pc']['name']!r} and {state['prefs']['tone']!r}")
    # The name field still follows the hero's name after Begin emptied both (the next adventure's name shows in it).
    item.setProperty("heroName", "Brokk the Second")
    field = next((f for f in panel.contentItem().findChildren(QQuickItem) if str(f.property("placeholderText") or "").startswith("Name")), None)
    if field is None or field.property("text") != "Brokk the Second":
        problems.append(f"after Begin the name field no longer follows the hero's name: {field and field.property('text')!r}")
    item.setProperty("heroName", "")
    item.open(json.dumps({"view": "table"}))
    wait(1500)
    item.findChild(QObject, "question").setProperty("text", "-is anyone watching?")
    item.askOracle()
    wait(1500)
    log = json.loads((game / "state.json").read_text())["log"]
    if not any('"-is anyone watching?"' in entry["text"] for entry in log):
        problems.append(f"the oracle didn't get the question: {trouble(item) or log[-1]['text']}")
    panel.grabWindow().save(str(out / "table-alive.png"))
    return problems


def an_x_card(item, panel, out, work, wait):
    """The Book's cut: with the GM's last message on the page, the panel's words become a note and a line, `solo strike`
    runs, and the GM is asked to carry on without it. The words start with a dash, and still reach the engine as words."""
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
                + (f", agent {book.property('agent')}, busy {book.property('busy')}, dead {book.property('dead')})" if book is not None else ")")]
    book.setProperty("cutting", True)
    item.findChild(QObject, "cutInput").setProperty("text", "-spiders")
    LAUNCHED.clear()
    QMetaObject.invokeMethod(book, "cutIt", Q_ARG("QVariant", "line"))
    wait(2500)
    state = json.loads((game / "state.json").read_text())
    if len(state["struck"]) != 1 or state["prefs"]["lines"] != ["-spiders"]:
        problems.append(f"the cut didn't reach the engine: {trouble(item) or state['struck']}, {state['prefs']}")
    said = [" ".join(str(a) for a in command) for command in LAUNCHED]
    if not any("gm turn" in line for line in said):
        problems.append(f"the GM wasn't asked to carry on after the cut (launched: {said})")
    if book.property("cutting") or item.findChild(QObject, "cutInput").property("text"):
        problems.append("the cut went through, and the panel stayed open with the words")

    # A cut that doesn't go through (solo can't run for a moment) keeps the panel open with the words, and says why.
    item.setProperty("turn", {"status": "idle"})
    with campaign.session(game) as c:
        c.say("The spider's mother is bigger.")
    for _ in range(20):
        wait(300)
        if book.property("canCut"):
            break
    book.setProperty("cutting", True)
    item.findChild(QObject, "cutInput").setProperty("text", "-mothers")
    solo = work / "plugin" / "bin"
    solo.unlink()
    solo.symlink_to(work / "nowhere")
    try:
        QMetaObject.invokeMethod(book, "cutIt", Q_ARG("QVariant", "veil"))
        wait(500)
    finally:
        solo.unlink()
        solo.symlink_to(REPO / "bin")
    if not book.property("cutting") or item.findChild(QObject, "cutInput").property("text") != "-mothers":
        problems.append("a cut that didn't go through closed the panel, or lost the player's words")
    if "couldn't run" not in book.property("actionError"):
        problems.append(f"a cut that didn't go through didn't say why in the Book: {book.property('actionError')!r}")
    QMetaObject.invokeMethod(book, "cutIt", Q_ARG("QVariant", "veil"))  # and again, with solo back
    wait(2500)
    state = json.loads((game / "state.json").read_text())
    if len(state["struck"]) != 2 or state["prefs"]["veils"] != ["-mothers"] or book.property("cutting"):
        problems.append(f"the cut tried again didn't go through: {trouble(item) or state['struck']}, {state['prefs']}")
    item.setProperty("turn", {"status": "idle"})
    return problems


def a_cut_while_another_is_picked(item, work, wait):
    """The X-card's cut, waiting behind a command that picks another campaign (a card on Home clicked just before):
    it cuts the message it was asked to, where it was asked, and the campaign picked meanwhile isn't asked to carry
    on from a cut it never had."""
    from solo import campaign
    problems = []
    game = Path((work / "state" / "solo" / "current").read_text().strip())
    other = work / "games" / "campaigns" / "elsewhere"
    subprocess.run([str(REPO / "bin" / "solo"), "new", "red-tusk", "--dir", str(other)], check=True, capture_output=True)
    campaign.set_current(game)
    with campaign.session(game) as c:
        c.say("The rope bridge creaks under you.")
    item.setProperty("turn", {"status": "idle"})
    book = item.findChild(QObject, "book")
    for _ in range(20):
        wait(300)
        if book.property("canCut") and item.property("campaign") == str(game):
            break
    struck = len(json.loads((game / "state.json").read_text())["struck"])
    book.setProperty("cutting", True)
    LAUNCHED.clear()
    Process.hold = True
    try:
        item.useCampaign(str(other))
        wait(100)
        QMetaObject.invokeMethod(book, "cutIt", Q_ARG("QVariant", ""))
        wait(100)
    finally:
        release()
    for _ in range(20):
        wait(300)
        if not item.property("busy"):
            break
    if len(json.loads((game / "state.json").read_text())["struck"]) != struck + 1 or item.property("campaign") != str(other):
        problems.append(f"the cut waiting behind another campaign picked didn't cut where it was asked: {trouble(item)}")
    turns = [" ".join(str(a) for a in command[1:]) for command in LAUNCHED if "turn" in command]
    if turns:
        problems.append(f"the campaign picked while a cut waited was asked to carry on from it: {turns}")
    campaign.set_current(game)
    item.useCampaign(str(game))
    wait(1500)
    item.setProperty("turn", {"status": "idle"})
    return problems


def a_turn_that_never_starts(item, panel, out, work, wait):
    """Words sent to the GM whose turn never starts (turn.json doesn't change: here nothing runs it): a while on the
    Book stops waiting, says so and frees the composer, and "try again" sends the words again. A turn slow to start
    (one that ends an agent an earlier turn left running can take five seconds) isn't taken for one that never will,
    and a turn that does start is left alone."""
    problems = []
    game = Path((work / "state" / "solo" / "current").read_text().strip())
    book = item.findChild(QObject, "book")
    patience = item.findChild(QObject, "watchdog").property("interval")
    item.setProperty("turn", {"status": "idle"})
    item.speak("I knock on the door.")
    if not book.property("busy"):
        problems.append("the Book doesn't wait for the GM after a send")
    wait(7000)
    if not book.property("busy"):
        problems.append(f"7 s after a send, while a slow turn could still be starting, the Book gave up: {item.property('turn').toVariant()}")
    wait(patience - 7000 + 2000)
    turn = item.property("turn").toVariant()
    if book.property("busy") or turn.get("status") != "error" or "didn't start" not in turn.get("error", ""):
        problems.append(f"the Book is still waiting, or doesn't say why, {patience / 1000 + 2:.0f} s after a send nobody heard: {turn}")
    LAUNCHED.clear()
    QMetaObject.invokeMethod(book, "retry")
    if item.property("turn").toVariant().get("player") != "I knock on the door." or not any("gm" in c and "turn" in c for c in LAUNCHED):
        problems.append(f"try again didn't send the words again: {item.property('turn').toVariant()}, {LAUNCHED}")
    (game / ".solo" / "turn.json").write_text('{"status": "thinking", "player": "I knock on the door.", "doing": "rolling the dice"}')
    wait(patience + 2000)
    turn = item.property("turn").toVariant()
    if turn.get("status") != "thinking" or turn.get("doing") != "rolling the dice":
        problems.append(f"a turn that started was taken for one that didn't: {turn}")
    # The status the watchdog asked for comes back after turn.json did (the turn began while `solo gm status` ran):
    # it is the older of the two, and the turn under way stays.
    item.speak("I knock again.")
    (game / ".solo" / "turn.json").write_text('{"status": "thinking", "player": "I knock again.", "doing": "writing it down"}')
    wait(500)
    item.unheard({"status": "done"})
    turn = item.property("turn").toVariant()
    if turn.get("status") != "thinking" or turn.get("doing") != "writing it down":
        problems.append(f"a status asked for before the turn began overrode its turn.json: {turn}")
    (game / ".solo" / "turn.json").write_text('{"status": "idle"}')
    wait(500)
    return problems


def no_agent_yet(item, work, wait):
    """With no default agent set (`solo gm agent` names none) the Book says how to set one up, in the engine's words
    when it gives a reason, and "open the GM" says what it did instead of nothing. A default agent the Book could run
    but that isn't installed keeps the composer, with the engine's reason over it."""
    problems = []
    book = item.findChild(QObject, "book")
    hint = book.findChild(QObject, "gmHint")
    why = book.findChild(QObject, "gmWhy")
    missing = "Your default agent (claude) isn't on PATH: install it, or choose another with: omarchy default agent <name>"
    item.setProperty("agentInfo", {"agent": "claude", "book": True, "why": missing})
    wait(100)
    if why is None or not why.property("visible") or why.property("text") != missing:
        problems.append(f"the Book doesn't say why its agent can't start: {why and (why.property('visible'), why.property('text'))}")
    item.setProperty("agentInfo", {"agent": "claude", "book": True})
    wait(100)
    if why is not None and why.property("visible"):
        problems.append("the Book gives a reason its agent can't start when the engine gives none")
    item.setProperty("agentInfo", {"agent": "", "book": False})
    wait(100)
    if "omarchy default agent" not in hint.property("text"):
        problems.append(f"with no agent the Book doesn't say how to set one up: {hint.property('text')!r}")
    item.setProperty("agentInfo", {"agent": "", "book": False, "why": "Omarchy has no default agent yet."})
    wait(100)
    if hint.property("text") != "Omarchy has no default agent yet.":
        problems.append(f"the Book doesn't give the engine's reason for having no GM: {hint.property('text')!r}")
    # solo's link went (a first run, an agent installed since): `solo play` links it again, and says so to a terminal.
    (work / "home" / ".local" / "bin" / "solo").unlink(missing_ok=True)
    QMetaObject.invokeMethod(book, "openTerminal")
    wait(2500)
    if not book.property("actionNote") or book.property("actionError"):
        problems.append(f"open the GM said nothing of what it did: {book.property('actionNote')!r} {book.property('actionError')!r}")
    if "\n" in book.property("actionNote") or "linked" in book.property("actionNote"):
        problems.append(f"open the GM says more than what it did: {book.property('actionNote')!r}")
    item.setProperty("agentInfo", {"agent": "claude", "book": True})
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
    if labelled(panel.contentItem(), "Awareness") is None:  # the skill once, not "Awareness +awareness"
        problems.append("the roll's heading doesn't read just Awareness")
    expect("a blow to dying", lambda c: c.wound("hero", "40", "a rockfall", armor=False, rng=Dice()),
           ["desk flash hit", "/hit-", "desk dying on 0", "/heartbeat-"], shot="table-dying")
    # Dying, the Table offers the death roll (and the solo rules' Rally and Save yourself), not what the hero can't do.
    if button(panel.contentItem(), "Death roll") is None:
        problems.append("a dying hero isn't offered the death roll")
    offered = [text for text in ("Light a torch", "Put it out", "Ask", "Meaning", "Roll advancement", "Tend my wounds",
                                 "Round rest", "Stretch rest", "Shift rest", "Mend", "Artisan", "push", "STR")
               if button(panel.contentItem(), text) is not None]
    if offered:
        problems.append(f"a dying hero is still offered {offered}")
    # Dying, the Book's page beats and breathes; shut, it runs nothing (the plugin stays loaded with the Book shut).
    from render import running
    book = item.findChild(QObject, "book")
    book.window().grabWindow().save(str(out / "book-dying.png"))
    if not running(book):
        problems.append("nothing runs on the open Book of a dying hero: the check of the shut Book would prove nothing")
    item.setProperty("bookOpen", False)
    wait(300)
    if running(book):
        problems.append(f"the shut Book still runs {running(book)}")
    item.setProperty("bookOpen", True)
    wait(500)
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
    if trouble(item):
        return [f"Begin (Ironsworn) failed: {trouble(item)}"]
    game = Path((work / "state" / "solo" / "current").read_text().strip())
    item.open(json.dumps({"view": "table"}))
    wait(1500)
    panel.grabWindow().save(str(out / "table-ironsworn.png"))
    if empty_flows(panel.contentItem()):
        problems.append(f"the Ironsworn Table shows {len(empty_flows(panel.contentItem()))} empty rows of buttons")

    def state():
        return json.loads((game / "state.json").read_text())

    item.findChild(QObject, "trackName").setProperty("text", "-Silence the bell")
    item.startTrack()
    wait(1500)
    tracks = {t["name"] for t in state()["progress"].values()}
    if "-Silence the bell" not in tracks:
        problems.append(f"the Table didn't start the vow: {trouble(item) or tracks}")
    item.rollMove("face_danger", "edge", "")
    wait(1500)
    if state()["last_check"]["type"] != "act" or state()["last_check"]["stat"] != "edge":
        problems.append(f"the Table's move wasn't rolled: {trouble(item) or state()['last_check']}")
    if labelled(panel.contentItem(), "Face Danger +edge") is None:
        problems.append("a move's heading doesn't say the stat it added")
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
    item.act(["burn"], "roll", None, None)
    wait(1500)
    if state()["last_check"]["type"] != "burn" or state()["pc"]["tracks"]["momentum"]["value"] != 2:
        problems.append("the Table's burn didn't burn momentum")
    item.rollTrack(next(t for t in item.openTracks().toVariant() if t["kind"] == "vow"))
    wait(1500)
    if state()["last_check"].get("track") is None:
        problems.append(f"the Table's progress roll wasn't made: {trouble(item) or state()['last_check']}")
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
    if labelled(panel.contentItem(), "The Old Road · Day 1, 00:00") is None:  # the time as the Book says it
        problems.append("the Table doesn't say the time as the Book does (Day 1, 00:00)")
    # In a fight the weapons come right under the last roll, above the spells and abilities.
    axe, magic = button(panel.contentItem(), "Long axe"), labelled(panel.contentItem(), "Magic")
    if axe is None or magic is None or axe.mapToScene(QPointF(0, 0)).y() > magic.mapToScene(QPointF(0, 0)).y():
        problems.append("in a fight the weapons are below the spells")

    item.setProperty("power", 2)
    item.cast(next(s for s in item.ready().toVariant() if s["name"] == "Ember"), False)
    wait(1500)
    with campaign.session(game) as c:
        # The cast's own dice came up a Demon (1 in 20), and its mishap drained willpower on top of the cost: given
        # back, so what is checked here and below is what the Table paid.
        drained = sum(e["changes"]["pc"]["tracks_was"]["wp"] - e["changes"]["pc"]["tracks"]["wp"]
                      for e in c.events if e["type"] == "spell_effect" and "wp" in e["changes"].get("pc", {}).get("tracks", {}))
        if drained:
            c.commit({"pc": {"wp": f"+{drained}"}})
    wait(1000)
    cast = [e for e in state()["log"] if e["type"] == "spell"]
    if trouble(item) or not cast or wp() != 7:
        problems.append(f"the Table's cast didn't cost two levels of Ember: {trouble(item) or wp()}")
    with campaign.session(game) as c:
        if c.state["choice"]:  # the cast's own dice came up a Dragon (1 in 20): its choice would hold up the fight below
            c.dragon(next((o for o in c.state["choice"]["options"] if o != "free"), c.state["choice"]["options"][0]))
    if item.property("power") != 1:
        problems.append("the power level didn't go back to 1 after the cast")

    item.toggleRider("Quickdraw")
    item.act(["fight", "--round"] + list(item.useArgs("round", "").toVariant()), "fight", None, None)
    wait(1500)
    if trouble(item) or wp() != 5 or item.property("riders").toVariant() != ["Quickdraw"]:
        problems.append(f"Quickdraw wasn't paid with the new round: {trouble(item) or wp()}")
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
        problems.append(f"the Table's prepare didn't swap the spells: {trouble(item) or state()['pc']['prepared']}")

    with campaign.session(game) as c:
        c.attack("cultist", weapon="long_axe", rng=Dice(1, 3, 3, 3, 3))  # a natural 1: a Dragon, which waits for the player (dice to spare if it can't)
    wait(1500)
    if not state()["choice"]:
        problems.append("a Dragon on the attack didn't wait for a choice")
    options = [o["label"] for o in item.dragonOptions().toVariant()]
    if "Double damage" not in options or not any(o.startswith("Attack ") for o in options):
        problems.append(f"the Dragon's choices aren't offered, a free attack for the other foe included: {options}")
    panel.grabWindow().save(str(out / "table-dragon-choice.png"))
    item.act(["dragon", "double"], "dragon", None, None)
    wait(1500)
    if state()["choice"] or trouble(item):
        problems.append(f"the Dragon's choice wasn't answered: {trouble(item) or state()['choice']}")

    with campaign.session(game) as c:
        c.append("durability", weapon="long_axe", label="Long axe", how="parry", damaged=True, broke=True, cause=None)
    wait(1500)
    axe = next(w for w in state()["kit"]["weapons"] if w["id"] == "long_axe")
    if axe["condition"] != "broken" or [w["id"] for w in item.worn().toVariant()] != ["long_axe"]:
        problems.append(f"a broken weapon isn't shown as broken: {axe}")
    panel.grabWindow().save(str(out / "table-broken-axe.png"))
    item.act(["repair", "long_axe", "--artisan"], "gear", None, None)
    wait(1500)
    if state()["pc"].get("damaged") or trouble(item):
        problems.append(f"the Table's mend didn't mend it: {trouble(item) or state()['pc'].get('damaged')}")

    item.act(["ability", "--cost", "2", "--", "Far gaze"], "ability", None, None)
    wait(1500)
    if trouble(item) or wp() != 3:
        problems.append(f"an ability that costs what the hero chooses wasn't paid: {trouble(item) or wp()}")
    with campaign.session(game) as c:
        c.end_fight()
    wait(1000)
    item.toggleRider("Mender")
    item.act(["rest", "stretch"] + list(item.useArgs("rest", "stretch").toVariant()), "rest", None, None)
    wait(1500)
    if trouble(item) or wp() != 1 and not any(e["type"] == "ability" for e in state()["log"]):
        problems.append(f"Mender wasn't paid with the rest: {trouble(item) or wp()}")
    panel.grabWindow().save(str(out / "table-magic-rested.png"))
    return problems


def errors_by_source(item, work, wait):
    """A command and a read that fail each say why where they belong, and neither covers the other: a read that fails
    after a refused command leaves the command's reason, and a command that goes through leaves the read's. A solo
    that can't start at all is said too, and the read waiting behind one that couldn't start still runs."""
    problems = []
    item.act(["death-roll"], "dying", None, None)  # the hero isn't dying
    wait(1500)
    refused = item.property("error").toVariant()
    if refused["place"] != "dying" or "isn't dying" not in refused["text"]:
        problems.append(f"a refused death roll didn't say why at the death roll: {refused}")
    item.ask("preview", ["character", "--system", str(work / "no-such-system")], "")
    wait(1500)
    if item.property("error").toVariant() != refused:
        problems.append(f"a read that failed covered what the command said: {item.property('error').toVariant()}")
    unread = item.property("queryError").toVariant()
    if unread["place"] != "preview" or not unread["text"]:
        problems.append(f"the read that failed didn't say why at the preview: {unread}")
    item.act(["light", "torch"], "light", None, None)
    wait(1500)
    if trouble(item) != unread["text"] or item.property("queryError").toVariant() != unread:
        problems.append(f"a command that went through changed what the read said: {trouble(item)!r}")
    # For a moment the plugin's bin/solo isn't there.
    solo = work / "plugin" / "bin"
    solo.unlink()
    solo.symlink_to(work / "nowhere")
    try:
        item.act(["light", "--out"], "light", None, None)
        item.setProperty("pace", "unread")
        item.ask("library", ["library"], "")
        item.ask("pace", ["gm", "pace"], "")  # waits behind the library
        wait(1000)
    finally:
        solo.unlink()
        solo.symlink_to(REPO / "bin")
    unstarted = item.property("error").toVariant()
    if unstarted["place"] != "light" or "couldn't run" not in unstarted["text"]:
        problems.append(f"a command that couldn't start didn't say so: {unstarted}")
    waited = item.property("queryError").toVariant()
    if waited["place"] != "pace" or "couldn't run" not in waited["text"]:
        problems.append(f"the read waiting behind one that couldn't start never ran: {waited}")
    item.ask("pace", ["gm", "pace"], "")
    wait(1500)
    if item.property("pace") == "unread" or item.property("queryError").toVariant()["place"] == "pace":
        problems.append(f"the reads stopped after one couldn't start: pace {item.property('pace')!r}, {trouble(item)!r}")
    return problems


def commands_wait_their_turn(item, panel, work, wait):
    """While a command runs the Table is busy and its buttons that run one wait, so a double click on STR rolls once;
    what is asked for meanwhile (from the Book, or Enter in a field) runs after it, in the order asked, none lost."""
    problems = []
    game = Path((work / "state" / "solo" / "current").read_text().strip())

    def state():
        return json.loads((game / "state.json").read_text())

    def rolls():
        return [e for e in state()["log"] if e["type"] == "check"]

    strength = button(panel.contentItem(), "STR")
    if strength is None or not strength.property("enabled"):
        return ["the Table shows no STR to roll"]
    before = len(rolls())
    middle = strength.mapToScene(QPointF(strength.width() / 2, strength.height() / 2)).toPoint()
    Process.hold = True
    try:
        QTest.mouseClick(panel, Qt.LeftButton, Qt.NoModifier, middle)
        wait(100)
        if not item.property("busy") or strength.property("enabled"):
            problems.append(f"the Table isn't busy while the roll runs (busy {item.property('busy')}, STR enabled {strength.property('enabled')})")
        QTest.mouseClick(panel, Qt.LeftButton, Qt.NoModifier, middle)  # the second click of a double click
        item.act(["ask", "--likely", "even", "--", "first?"], "oracle", None, None)
        item.act(["ask", "--likely", "even", "--", "second?"], "oracle", None, None)
        wait(300)
    finally:
        release()
    for _ in range(20):
        wait(300)
        if not item.property("busy"):
            break
    if len(rolls()) != before + 1:
        problems.append(f"a double click on STR rolled {len(rolls()) - before} times")
    asked = [e["text"] for e in state()["log"] if e["type"] == "oracle"]
    order = [q for q in ("first?", "second?") for text in asked if f'"{q}"' in text]
    if order != ["first?", "second?"]:
        problems.append(f"what was asked while the roll ran didn't run after it, in order: {asked[-2:]} ({trouble(item)})")
    if item.property("busy") or not strength.property("enabled"):
        problems.append("the Table stayed busy after the commands ended")
    return problems


def a_parry_and_what_waits(item, panel, work, wait):
    """A parry clicked on the Table, and a question asked while it runs. By the time the parry ends its button is gone
    with the blow it answered (state.json was read again first), and what comes after it still runs: the question
    waiting behind it is asked, and the Table is free again."""
    from helpers import Dice
    from solo import campaign
    problems = []
    game = Path((work / "state" / "solo" / "current").read_text().strip())

    def state():
        return json.loads((game / "state.json").read_text())

    with campaign.session(game) as c:
        c.fight(["cultist"], rng=Dice(1, 2))
        c.enemy("cultist", rng=Dice(2))  # the dagger hits, and waits for the hero's answer
    wait(1500)
    parry = button(panel.contentItem(), "Parry: ")
    if parry is None or not parry.property("enabled"):
        return ["the Table offers no parry against the blow coming"]
    Process.hold = True
    try:
        QTest.mouseClick(panel, Qt.LeftButton, Qt.NoModifier, parry.mapToScene(QPointF(parry.width() / 2, parry.height() / 2)).toPoint())
        wait(100)
        item.act(["ask", "--likely", "even", "--", "do more come?"], "oracle", None, None)
        wait(100)
    finally:
        release()
    for _ in range(20):
        wait(300)
        if not item.property("busy"):
            break
    log = state()["log"]
    if ((state()["last_check"] or {}).get("defend") or {}).get("how") != "parry" or (state()["combat"] or {}).get("incoming"):
        problems.append(f"the Table's parry didn't answer the blow: {trouble(item) or log[-1]}")
    if not any(e["type"] == "oracle" and '"do more come?"' in e["text"] for e in log):
        problems.append(f"the question asked while the parry ran never ran ({trouble(item)})")
    if item.property("busy") or item.property("queue").toVariant():
        problems.append(f"the Table stayed busy after the parry: {item.property('queue').toVariant()}")
    with campaign.session(game) as c:
        if c.state["combat"]:
            c.end_fight()
    wait(1000)
    return problems


def contrast(a, b):
    """WCAG's contrast between a QColor and the background `b` it is drawn on (a translucent one as it shows there)."""
    alpha = a.alphaF()
    a = QColor.fromRgbF(*(x * alpha + y * (1 - alpha) for x, y in zip((a.redF(), a.greenF(), a.blueF()), (b.redF(), b.greenF(), b.blueF()))))

    def luminance(c):
        def channel(v):
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * channel(c.redF()) + 0.7152 * channel(c.greenF()) + 0.0722 * channel(c.blueF())
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def quiet_text_reads(engine, item, panel, out, wait):
    """Dim text (the Table's captions, the Book's asides) keeps WCAG AA's 4.5:1 and stays quieter than the body, and
    faint (rules, borders, blanks) 3:1 and quieter than dim, on a dark theme (Tokyo Night) and a light one (Catppuccin
    Latte), where darkening the text had made dim louder than the body. Both hold on the Book's panels too (the
    composer, the X-card, the codex, the fight), whose surface is a shade toward the text."""
    from PySide6.QtQml import QQmlComponent
    holder = QQmlComponent(engine)
    holder.setData(b"import QtQuick\nimport qs.Commons as Commons\nQtObject { property QtObject colors: Commons.Color }", QUrl())
    popups = holder.create().property("colors").property("popups")
    theme = item.findChild(QObject, "book").property("theme")
    problems = []
    dark = (popups.property("text"), popups.property("background"))
    for name, text, background in (("Tokyo Night", *dark), ("Catppuccin Latte", QColor("#4c4f69"), QColor("#eff1f5"))):
        popups.setProperty("text", text)
        popups.setProperty("background", background)
        wait(100)
        body, dim, faint = (contrast(c, background) for c in (text, item.property("dim"), theme.property("faint")))
        if not (4.5 <= dim < body and 3 <= faint < dim):
            problems.append(f"on {name} the body reads {body:.2f}:1, dim {dim:.2f}:1 and faint {faint:.2f}:1")
        surface = theme.property("surface")
        dim, faint = (contrast(c, surface) for c in (item.property("dim"), theme.property("faint")))
        if not (4.5 <= dim and 3 <= faint):
            problems.append(f"on {name}'s panels dim reads {dim:.2f}:1 and faint {faint:.2f}:1")
        if name != "Tokyo Night":
            panel.grabWindow().save(str(out / "table-light.png"))
    popups.setProperty("text", dark[0])
    popups.setProperty("background", dark[1])
    return problems


def by_keyboard(item, panel, wait):
    """The Table's own clickables (folds, cards, the move groups' headings) are reached with Tab and worked with Enter
    or Space, and a screen reader knows them by name, as a button."""
    from PySide6.QtGui import QAccessible
    problems = []
    fold = labelled(panel.contentItem(), "▸ Desktop effects")
    if fold is None:
        return ["no Desktop effects to fold open"]
    face = QAccessible.queryAccessibleInterface(fold)
    if face is None or face.role() != QAccessible.Button or face.text(QAccessible.Name) != "Desktop effects":
        problems.append(f"a screen reader doesn't know the fold as a button called Desktop effects: {face and (face.role(), face.text(QAccessible.Name))}")
    panel.requestActivate()
    wait(100)
    fold.forceActiveFocus()
    QTest.keyClick(panel, Qt.Key_Space)
    wait(100)
    if button(panel.contentItem(), "Borders") is None:
        problems.append("Space on a fold didn't open it")
    QTest.keyClick(panel, Qt.Key_Return)
    wait(100)
    if button(panel.contentItem(), "Borders") is not None:
        problems.append("Enter on an open fold didn't close it")
    item.show("new")
    wait(2500)
    card = cards(panel.contentItem(), "The Red Tusk Hall")
    face = QAccessible.queryAccessibleInterface(card) if card is not None else None
    if face is None or face.role() != QAccessible.Button or face.text(QAccessible.Name) != "The Red Tusk Hall":
        problems.append(f"a screen reader doesn't know the adventure's card by its title: {face and (face.role(), face.text(QAccessible.Name))}")
    if card is not None:
        card.forceActiveFocus()
        QTest.keyClick(panel, Qt.Key_Space)
        wait(300)
        if item.property("pickedAdventure") != "red-tusk":
            problems.append(f"Space on an adventure's card didn't pick it: {item.property('pickedAdventure')!r}")
    return problems


def cards(item, name):
    """The visible card under `item` called `name`."""
    for child in item.childItems():
        if child.property("name") == name and child.property("clickable") is not None and child.isVisible():
            return child
        found = cards(child, name)
        if found is not None:
            return found
    return None


def adventures_not_ready(item, panel, out, wait):
    """New adventure names an adventure's system, and says under it why the adventure can't be played yet, when
    `solo library` says so (system_name, ready, why); an entry without them shows the system as before."""
    item.show("new")
    wait(2500)
    library = item.property("library").toVariant()
    why = "Dragonbane's rules aren't built from your books yet: make dragonbane BOOKS=<your PDFs>."
    sunken = {"id": "sunken-keep", "title": "The Sunken Keep", "system": "dragonbane-2", "system_name": "Dragonbane, from your books",
              "ready": False, "why": why, "summary": "A keep the lake took back.", "path": "/nowhere", "characters": []}
    item.setProperty("library", {**library, "adventures": [sunken] + library["adventures"]})
    wait(300)
    panel.grabWindow().save(str(out / "new-not-ready.png"))
    problems = []
    for text in ("Dragonbane, from your books", why):
        if labelled(panel.contentItem(), text) is None:
            problems.append(f"New adventure doesn't show {text!r} for an adventure that isn't ready")
    known = library["adventures"][0]
    name = next((s["name"] for s in library["systems"] if s["id"] == known["system"]), None)
    if known.get("system_name") is None and name and labelled(panel.contentItem(), name) is None:
        problems.append(f"an adventure without a system_name no longer shows its system's name ({name!r})")
    return problems


def a_campaign_gone(item, panel, out, work, wait):
    """`current` names a campaign whose folder is gone (moved, or deleted by hand): the Table goes Home and says so,
    instead of "Loading the table" for good, whether it was open on the table or opens afterwards."""
    pointer = work / "state" / "solo" / "current"
    kept = pointer.read_text()
    gone = work / "games" / "campaigns" / "gone"
    problems = []
    item.open(json.dumps({"view": "table"}))
    wait(1000)
    try:
        pointer.write_text(f"{gone}\n")
        wait(1500)
        said = item.findChild(QObject, "lost")
        if item.property("view") != "home" or said is None or not said.property("visible") or str(gone) not in said.property("text"):
            problems.append(f"the Table open on a campaign that went is on {item.property('view')!r}, saying {said and said.property('text')!r}")
        panel.grabWindow().save(str(out / "home-lost.png"))
        item.close()
        item.open("{}")
        wait(1000)
        if item.property("view") != "home":
            problems.append(f"opened on a campaign that is gone, the Table shows {item.property('view')!r}")
    finally:
        pointer.write_text(kept)
        wait(1500)
    return problems


def the_first_game(load, work, wait):
    """The d20 sees the very first game without a restart of the shell: `current`, and the folder it is in, are made
    by that game, after the bar began watching for them."""
    fresh = work / "first-state"
    os.environ["XDG_STATE_HOME"] = str(fresh)
    try:
        bar = load("BarWidget.qml", 60, 30)
        wait(500)
        game = (work / "state" / "solo" / "current").read_text().strip()
        (fresh / "solo").mkdir(parents=True)
        (fresh / "solo" / "current").write_text(game + "\n")
        wait(4000)
        seen = bar.rootObject().property("campaign")
    finally:
        os.environ["XDG_STATE_HOME"] = str(work / "state")
    return [] if seen == game else [f"the d20 didn't see the first game: it follows {seen!r}"]


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
