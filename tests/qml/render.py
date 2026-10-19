"""Render the Book offscreen with PySide6, against real engine state, to PNG files.

    python3 tests/qml/render.py <out folder>

A development check (PySide6 isn't needed to play): it catches QML errors and shows how
the pages look without an Omarchy desktop.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import QMetaObject, QObject, Q_ARG, QTimer, QUrl, SIGNAL  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402

import scenario  # noqa: E402


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    data = Path(tempfile.mkdtemp())
    # Creating the render fixtures must never replace the player's current game.
    os.environ["XDG_STATE_HOME"] = str(data / "state")
    os.environ["SOLO_HOME"] = str(data / "games")
    scenario.play(data)
    scenario.play_ironsworn(data)
    fight = json.loads((data / "fight.json").read_text())
    dead = json.loads((data / "dead.json").read_text())
    ironsworn = json.loads((data / "ironsworn.json").read_text())

    app = QGuiApplication(sys.argv)
    view = QQuickView()
    view.engine().addImportPath(str(HERE / "stubs"))
    errors = []
    view.statusChanged.connect(lambda status: errors.extend(e.toString() for e in view.errors()))
    view.engine().warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
    view.setSource(QUrl.fromLocalFile(str(HERE / "Harness.qml")))
    if view.status() == QQuickView.Error:
        print("\n".join(e.toString() for e in view.errors()))
        return 1
    view.show()
    root = view.rootObject()
    book = root.findChild(QObject, "book")

    def wait(ms):
        timer = QTimer()
        timer.setSingleShot(True)
        timer.start(ms)
        while timer.isActive():
            app.processEvents()

    def shot(name, ms=400):
        wait(ms)
        view.grabWindow().save(str(out / f"{name}.png"))
        print("wrote", out / f"{name}.png")

    root.setProperty("game", fight)
    shot("fight", 700)
    book.setProperty("codexOpen", True)
    shot("codex")
    book.setProperty("codexOpen", False)

    roll = [b for b in fight["story"] if b["kind"] == "roll"][0]
    dice = root.findChild(QObject, "dice")
    QMetaObject.invokeMethod(dice, "show", Q_ARG("QVariant", roll))
    shot("dice-rolling", 250)
    shot("dice-landed", 2800)
    wait(5000)
    # A Dragon with a boon: two d20s, the one that counts lit gold, sparks and a glow.
    dragon = {"kind": "roll", "label": "Swords", "boons": 1, "purpose": "Broadsword at Cultist",
              "outcome": {"result": 1, "target": 14, "success": True, "dragon": True, "demon": False, "rolls": [12, 1]}}
    QMetaObject.invokeMethod(dice, "show", Q_ARG("QVariant", dragon))
    shot("dice-dragon", 2700)
    wait(5000)

    title = root.findChild(QObject, "titleCard")
    QMetaObject.invokeMethod(title, "show", Q_ARG("QVariant", "Chieftain's Hall"), Q_ARG("QVariant", "The Red Tusk Hall"))
    shot("title-decrypting", 250)
    shot("title", 1400)
    wait(7000)

    root.setProperty("turn", {"status": "writing", "doing": "rolling the dice", "player": "I shove the cultist into the fire pit.",
                              "text": "You drive your shoulder into the robed man and he stumbles back, arms wheeling, into the embers. "
                                      "The *smell* of burning wool fills the hall."})
    shot("writing", 1500)
    root.setProperty("turn", {"status": "idle"})

    # The X-card: one tap cuts the GM's last message; words typed there make it a line or a veil.
    cuts = []
    QObject.connect(book, SIGNAL("cut(QString,QString,QString)"), lambda note, line, veil: cuts.append((note, line, veil)))
    if not book.property("canCut"):
        errors.append("the cut link should show when the GM has spoken and isn't writing")
    book.setProperty("cutting", True)
    shot("cut", 500)
    book.findChild(QObject, "cutInput").setProperty("text", "no fire")
    QMetaObject.invokeMethod(book, "cutIt", Q_ARG("QVariant", "line"))
    if cuts != [("no fire", "no fire", "")] or book.property("cutting"):
        errors.append(f"the X-card gave {cuts}, and the panel {'stayed open' if book.property('cutting') else 'closed'}")
    root.setProperty("turn", {"status": "writing", "text": "..."})
    if book.property("canCut"):
        errors.append("nothing to cut while the GM is writing")
    root.setProperty("turn", {"status": "idle"})

    root.setProperty("game", dead)
    shot("dead", 700)
    shot("gravestone", 7000)  # the last death roll has settled, the stone has risen

    # Another campaign: the Book starts over with it, rather than holding its dice and scene
    # cards back until its story passes the last one's.
    book.setProperty("campaign", "/games/another")
    root.setProperty("game", fight)
    wait(300)
    if book.property("seen") != fight["story"][-1]["seq"]:
        errors.append(f"the Book kept the last campaign's place: seen {book.property('seen')}")
    book.setProperty("actionError", "Ragna isn't carrying a torch")
    shot("refused", 700)
    book.setProperty("actionError", "")

    # A dice pool (Year Zero): every die that scores is lit, a d10 shows its two digits.
    pool = {"kind": "roll", "label": "Heavy Machinery", "outcome": {
        "groups": [{"name": "base", "sides": 6, "rolls": [6, 3, 1, 5]}, {"name": "stress", "sides": 6, "rolls": [1, 6]},
                   {"name": "skill", "sides": 10, "rolls": [10]}],
        "successes": 3, "success": True, "triggers": ["panic"]}}
    QMetaObject.invokeMethod(dice, "show", Q_ARG("QVariant", pool))
    shot("dice-pool", 2600)
    wait(5000)

    # A game of moves (Ironsworn): momentum below and above zero, the vows and roads, and dice that
    # are an action die and two challenge dice.
    root.setProperty("game", ironsworn)
    shot("ironsworn", 700)
    book.setProperty("codexOpen", True)
    shot("ironsworn-codex")  # the people of a pack with no art: named, with what they want and fear blanked out
    book.setProperty("codexOpen", False)
    moves = [b for b in ironsworn["story"] if b["kind"] == "roll"]
    QMetaObject.invokeMethod(dice, "show", Q_ARG("QVariant", moves[-1]))  # a miss momentum could still save
    shot("dice-miss", 2800)
    wait(5000)
    strong = {"kind": "roll", "label": "Strike", "purpose": "+edge", "outcome": {
        "action": 5, "stat": 3, "adds": 1, "momentum": 4, "dulled": False, "score": 9, "challenge": [3, 4], "cancelled": [],
        "beaten": 2, "hit": "strong_hit", "success": True, "match": False}}
    QMetaObject.invokeMethod(dice, "show", Q_ARG("QVariant", strong))
    shot("dice-strong", 2800)
    wait(5000)
    burned = {"kind": "roll", "label": "Face Danger", "purpose": "+edge", "burned": True, "outcome": {
        "action": 1, "stat": 3, "adds": 0, "momentum": 6, "dulled": False, "score": 4, "challenge": [5, 8], "cancelled": [0],
        "beaten": 1, "hit": "weak_hit", "success": True, "match": False, "burned": 6}}
    QMetaObject.invokeMethod(dice, "show", Q_ARG("QVariant", burned))
    shot("dice-burned", 2800)
    wait(5000)
    progress = {"kind": "roll", "label": "Fulfill Your Vow", "purpose": "Silence the bell", "outcome": {
        "progress": 8, "score": 8, "challenge": [6, 6], "cancelled": [], "beaten": 2, "hit": "strong_hit", "success": True, "match": True}}
    QMetaObject.invokeMethod(dice, "show", Q_ARG("QVariant", progress))
    shot("dice-progress", 2800)
    if errors:
        print("QML warnings:\n" + "\n".join(errors))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
