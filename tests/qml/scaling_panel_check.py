"""Real Panel regressions: flipping settings, independent scales and safe saving."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QPointF, Qt
from PySide6.QtQml import QQmlComponent
from PySide6.QtTest import QTest

REPO = Path(__file__).resolve().parents[2]


def items(parent):
    yield parent
    for child in parent.childItems():
        yield from items(child)


def check(item, panel, out, work, engine, wait, process_type):
    problems = []

    def expect(condition, message):
        if not condition:
            problems.append("interface scale: " + message)

    def find(parent, name):
        return next(obj for obj in items(parent) if obj.objectName() == name)

    window = find(item, "tableWindow")
    old = {target: item.property(target + "Scale") for target in ("book", "table")}
    old_width, height = window.width(), panel.height()
    base_width = window.implicitWidth() / old["table"]
    book = find(item, "book")
    input_ = find(book, "bookInput")
    old_text = input_.property("text")
    input_.setProperty("text", "This draft survives changing scale.")
    gear = find(item, "tableSettingsButton")
    scroll = find(item, "tableScroll")
    scroll.setProperty("contentY", min(100, max(0, scroll.property("contentHeight") - scroll.height())))
    position = scroll.property("contentY")
    gear.forceActiveFocus()
    QTest.keyClick(panel, Qt.Key_Space)
    wait(600)
    expect(item.property("settingsOpen"), "gear did not flip to settings")
    expect(find(item, "settingsCloseButton").hasActiveFocus(), "settings did not receive focus")
    QTest.keyClick(panel, Qt.Key_Escape)
    wait(450)
    expect(not item.property("settingsOpen") and item.property("opened"), "Esc closed the Table instead of settings")
    expect(gear.hasActiveFocus(), "return did not restore gear focus")
    expect(scroll.property("contentY") == position, "flipping reset Table scroll")
    QMetaObject.invokeMethod(gear, "clicked")
    wait(450)
    QMetaObject.invokeMethod(find(item, "settingsCloseButton"), "clicked")
    wait(450)
    expect(not item.property("settingsOpen"), "close did not return to the Table")
    old_reduced = item.property("reducedMotion")
    item.setProperty("reducedMotion", True)
    QMetaObject.invokeMethod(gear, "clicked")
    wait(300)
    # Moving existing global preferences must preserve their save/readback path.
    # CI has no real Book-capable agent installed; exercise both capability modes
    # explicitly rather than depending on whichever agent the host discovers.
    settings = find(item, "tableSettings")
    for _ in range(40):
        if not settings.property("busy"):
            break
        wait(50)
    expect(not settings.property("busy"), "settings queries did not finish")
    saved_agent = item.property("agentInfo")
    item.setProperty("agentInfo", {"agent": "fixture", "book": False})
    wait(50)
    expect(not find(item, "settingsPace_quick").property("enabled"), "terminal GM pace was editable")
    item.setProperty("agentInfo", {"agent": "fixture", "book": True})
    wait(100)
    QMetaObject.invokeMethod(find(item, "settingsPace_quick"), "clicked")
    wait(250)
    expect(item.property("pace") == "quick", "GM pace did not save")
    QMetaObject.invokeMethod(find(item, "settingsPace_normal"), "clicked")
    wait(250)
    expect(item.property("pace") == "normal", "GM pace did not restore")
    item.setProperty("agentInfo", saved_agent)
    for enabled in (False, True):
        QMetaObject.invokeMethod(find(item, "settingsEffect_sound"), "toggled")
        wait(250)
        expect(item.property("effects").toVariant()["sound"] == enabled, "atmosphere switch did not save")
        saved = subprocess.run([str(REPO / "bin" / "solo"), "desk", "settings"], check=True, capture_output=True, text=True)
        expect(json.loads(saved.stdout)["sound"] == enabled, "atmosphere switch was not persisted")
    selectors = {target: find(item, "settings" + target.title() + "Scale") for target in ("book", "table")}
    book_selector = find(book, "bookScaleSelector")
    game_path = Path(item.property("campaign")) / "state.json"
    campaign_before = game_path.read_bytes()
    scale_file = work / "state" / "solo" / "ui.json"

    def verify():
        for target in ("book", "table"):
            scale = item.property(target + "Scale")
            expect(selectors[target].property("value") == scale, target + " selector is out of sync")
            expect(find(item, target + "Viewport").property("canvas").scale() == scale, target + " canvas has the wrong scale")
        expect(book_selector.property("value") == item.property("bookScale"), "footer is out of sync")
        expect(abs(window.implicitWidth() - base_width * item.property("tableScale")) < 1, "Book changed the Table reservation")
        expect(input_.property("text") == "This draft survives changing scale.", "scale lost a Book draft")

    scale_file.write_text('{"scale": 1.25}')
    wait(200)
    expect(item.property("bookScale") == 1.25 and item.property("tableScale") == 1.25, "legacy preference changed size")
    for target in ("book", "table"):
        other = "table" if target == "book" else "book"
        unchanged = item.property(other + "Scale")
        for scale in (1, 1.25, 1.5, 1.75, 2):
            QMetaObject.invokeMethod(find(selectors[target], "appScale_" + str(scale)), "clicked")
            wait(250)
            width = 360 * item.property("tableScale")
            window.setProperty("width", width)
            panel.resize(round(width), height)
            wait(30)
            expect(item.property(target + "Scale") == scale, target + " did not apply " + str(scale))
            expect(item.property(other + "Scale") == unchanged, target + " resized the other surface")
            verify()
            panel.grabWindow().save(str(out / f"settings-{target}-scale-{scale}.png"))
    # Real pointer events verify native hit targets at 2x, not just signal calls.
    for scale in (1.75, 2):
        button = find(selectors["table"], "appScale_" + str(scale))
        point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mouseClick(panel, Qt.LeftButton, Qt.NoModifier, point)
        wait(250)
        expect(item.property("tableScale") == scale, "scaled pointer hit missed its control")
    expect(json.loads(scale_file.read_text()) == {"book_scale": 2, "table_scale": 2, "honor_hyprland": False}, "scales were not persisted")
    component = QQmlComponent(engine, panel.source())
    fresh = component.create()
    expect(fresh is not None, "restart could not load")
    if fresh is not None:
        expect(fresh.property("bookScale") == 2 and fresh.property("tableScale") == 2, "restart lost a scale")
        wait(400)
        fresh.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        wait(50)
    table_before = window.implicitWidth()
    QMetaObject.invokeMethod(find(book, "bookScaleDecrease"), "clicked")
    wait(250)
    expect(item.property("bookScale") == 1.75 and item.property("tableScale") == 2, "footer changed the Table")
    expect(window.implicitWidth() == table_before, "footer resized the dock")
    QMetaObject.invokeMethod(find(book, "bookScaleReset"), "clicked")
    wait(250)
    expect(item.property("bookScale") == 1 and item.property("tableScale") == 2, "reset changed the Table")
    verify()
    item.run(["library"], "home", None)
    item.setUiScale("book", 1.25)
    item.setUiScale("table", 1.5)  # Disabled while the first appearance save runs.
    wait(300)
    expect(item.property("bookScale") == 1.25 and item.property("tableScale") == 2, "campaign commands interfered with scaling")
    item.setProperty("error", "Keep this mechanics error")
    item.setProperty("errorAt", "gear")
    original_run = process_type._run

    def fail_scale(process):
        if "ui" not in list(process.command):
            return original_run(process)
        process.stderr.text = "solo: cannot save scale here"
        process.stderr.streamFinished.emit()
        process._running = False
        process.runningChanged.emit()
        process.exited.emit(1, 0)

    for target in ("table", "book"):
        with patch.object(process_type, "_run", fail_scale):
            item.setUiScale(target, 1.5)
            wait(100)
        expect(item.property("bookScale") == 1.25 and item.property("tableScale") == 2, "failed save changed size")
        expect("cannot save" in item.property("scaleError"), "failed save hid its error")
        expect(bool(book.property("scaleError")) == (target == "book"), "Table error leaked into the Book")
    expect(item.property("error") == "Keep this mechanics error", "saving cleared a mechanics error")
    subprocess.run([str(REPO / "bin" / "solo"), "ui", "--table-scale=1.5"], check=True, capture_output=True)
    wait(250)
    expect(item.property("tableScale") == 1.5 and item.property("bookScale") == 1.25, "CLI Table zoom changed the Book")
    verify()
    expect(game_path.read_bytes() == campaign_before, "scaling changed campaign state")
    for target in ("book", "table"):
        item.setUiScale(target, old[target])
        wait(250)
    expect(item.property("scaleError") == "", "successful retry kept a stale error")
    item.setProperty("settingsOpen", False)
    item.setProperty("reducedMotion", old_reduced)
    item.setProperty("error", "")
    input_.setProperty("text", old_text)
    window.setProperty("width", old_width)
    panel.resize(360, height)
    wait(400)
    print("Panel scaling: flip/focus/Esc, independent scopes at five steps, persistence/restart, footer isolation and scoped failures.")
    return problems
