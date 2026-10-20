"""Book serif picker against the real panel, fontconfig and saved preferences."""

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtQml import QQmlComponent
from PySide6.QtTest import QTest


def items(parent):
    yield parent
    for child in parent.childItems():
        yield from items(child)


def check(item, panel, out, work, engine, wait, process_type):
    problems = []

    def expect(condition, message):
        if not condition:
            problems.append("Book serif font: " + message)

    def find(name):
        return next(obj for obj in items(item) if obj.objectName() == name)

    old_reduced = item.property("reducedMotion")
    item.setProperty("reducedMotion", True)
    item.openSettings()
    wait(450)
    picker = find("bookSerifFontPicker")
    discovered = item.property("serifFonts").toVariant()
    expect(bool(discovered), "installed serif reading faces were not discovered")
    if not discovered:
        item.setProperty("settingsOpen", False)
        item.setProperty("reducedMotion", old_reduced)
        return problems
    family = discovered[0]
    theme = item.findChild(QObject, "soloTheme")
    mono = theme.property("mono")
    scales = (item.property("bookScale"), item.property("tableScale"))
    campaign = Path(item.property("campaign")) / "state.json"
    before = campaign.read_bytes()
    prefs = work / "state/solo/ui.json"
    scroll = find("settingsScroll")
    scroll.setProperty("contentY", 0)
    picker.forceActiveFocus()
    QTest.keyClick(panel, Qt.Key_Space)
    wait(100)
    popup = picker.findChild(QObject, "serifFontPopup")
    expect(popup.property("visible"), "keyboard did not open the dropdown")
    content = popup.property("contentItem")
    previews = [obj for obj in items(content) if obj.objectName().startswith("serifFontPreview_")]
    expect(len(previews) >= 2, "dropdown has no rendered font previews")
    for preview in previews:
        text = preview.property("text")
        expect(preview.property("font").family() == ("serif" if text == "System default" else text),
               "a font row did not preview its own typeface")
    image = panel.grabWindow()
    image.copy(0, 0, image.width(), min(560, image.height())).save(str(out / "settings-serif-fonts.png"))
    QTest.keyClick(panel, Qt.Key_Escape)
    wait(50)
    expect(not popup.property("visible") and item.property("settingsOpen"), "Escape dismissed Settings instead of only the dropdown")
    picker.forceActiveFocus()
    QTest.keyClick(panel, Qt.Key_Space)
    wait(50)
    QTest.keyClick(panel, Qt.Key_Down)
    QTest.keyClick(panel, Qt.Key_Return)
    wait(300)
    expect(item.property("bookSerifFont") == family, "keyboard selection did not save")
    expect(theme.property("serif") == family, "Book theme did not update immediately")
    expect(theme.property("mono") == mono, "override changed monospace UI text")
    expect(scales == (item.property("bookScale"), item.property("tableScale")), "font selection changed a scale")
    expect(json.loads(prefs.read_text())["book_serif_font"] == family, "font was not persisted")
    component = QQmlComponent(engine, panel.source())
    fresh = component.create()
    expect(fresh is not None, "restart could not load")
    if fresh is not None:
        expect(fresh.property("bookSerifFont") == family, "restart lost the override")
        wait(400)
        fresh.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        wait(50)
    original_run = process_type._run

    def fail_font(process):
        if not any(str(arg).startswith("--book-serif-font=") for arg in process.command):
            return original_run(process)
        process.stderr.text = "solo: font save failed"
        process.stderr.streamFinished.emit()
        process._running = False
        process.runningChanged.emit()
        process.exited.emit(1, 0)

    item.setProperty("error", "Keep this mechanics error")
    with patch.object(process_type, "_run", fail_font):
        picker.activated.emit(0)
        wait(100)
    expect(item.property("bookSerifFont") == family and picker.property("currentIndex") == 1, "failed save replaced the saved choice")
    expect("font save failed" in item.property("scaleError"), "failed save hid its error")
    expect(item.property("error") == "Keep this mechanics error", "font saving cleared a game error")
    item.setProperty("bookSerifFont", "Missing Reading Font")
    expect(theme.property("serif") == "serif", "missing font did not fall back to system serif")
    item.setBookSerifFont("")
    wait(250)
    expect(theme.property("serif") == "serif" and picker.property("currentIndex") == 0, "System default did not restore the default serif")
    expect(item.property("scaleError") == "", "successful retry kept a save error")

    def fail_scan(process):
        if "--serif-fonts" not in process.command:
            return original_run(process)
        process.stderr.text = "solo: fontconfig unavailable"
        process.stderr.streamFinished.emit()
        process._running = False
        process.runningChanged.emit()
        process.exited.emit(1, 0)

    with patch.object(process_type, "_run", fail_scan):
        item.openSettings()
        wait(100)
    expect("fontconfig unavailable" in item.property("serifFontsError"), "discovery failure hid its error")
    expect(picker.property("enabled"), "discovery failure disabled System default")
    item.openSettings()
    wait(450)
    expect(item.property("serifFontsError") == "", "reopening Settings did not retry discovery")
    expect(campaign.read_bytes() == before, "font preference changed campaign state")
    item.setProperty("settingsOpen", False)
    item.setProperty("reducedMotion", old_reduced)
    item.setProperty("error", "")
    print("Book fonts: self-rendered previews, keyboard/Esc, save/restart, default/missing fonts and scoped failures.")
    return problems
