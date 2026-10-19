"""Select/copy real Book passages, with an offscreen (not desktop) clipboard.

    QT_QUICK_BACKEND=software python3 tests/qml/selection_check.py <output folder>
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import (  # noqa: E402
    Q_ARG,
    Q_RETURN_ARG,
    QMetaObject,
    QObject,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QUrl,
)
from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QSignalSpy, QTest  # noqa: E402


def call(item, method, *args):
    return QMetaObject.invokeMethod(item, method, *(Q_ARG("QVariant", arg) for arg in args))


def position(passage, index):
    editor = passage.findChild(QObject, "selectableEditor")
    rect = QMetaObject.invokeMethod(editor, "positionToRectangle", Q_RETURN_ARG(QRectF), Q_ARG(int, index))
    return editor.mapToScene(QPointF(rect.x() + 1, rect.y() + rect.height() / 2)).toPoint()


def visual_items(item):
    yield item
    for child in item.childItems():
        yield from visual_items(child)


def type_text(window, text):
    for char in text:
        QTest.keyClick(window, Qt.Key(ord(char.upper())), Qt.ShiftModifier if char.isupper() else Qt.NoModifier)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp())
    os.environ["XDG_STATE_HOME"] = str(work / "state")
    os.environ["SOLO_HOME"] = str(work / "games")
    app = QGuiApplication(sys.argv)
    errors = []
    views = []

    def load(name):
        view = QQuickView()
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        view.engine().addImportPath(str(HERE / "stubs"))
        view.engine().warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
        view.setSource(QUrl.fromLocalFile(str(HERE / name)))
        assert view.status() != QQuickView.Error, "\n".join(e.toString() for e in view.errors())
        views.append(view)
        view.show()
        app.processEvents()
        QTest.qWait(100)
        return view, view.rootObject()

    view, root = load("SelectionHarness.qml")
    entry = root.findChild(QObject, "selectionGMEntry")
    gm = entry.findChild(QObject, "storyPassage")
    plain = root.findChild(QObject, "selectionPlainPassage")
    dropcap = root.findChild(QObject, "selectionDropcapPassage")
    controller = root.findChild(QObject, "selectionController")
    flick = root.findChild(QObject, "selectionFlickable")
    input_ = root.findChild(QObject, "selectionInput")
    clipboard = app.clipboard()
    assert gm and plain and dropcap

    # Existing themes need no new fields; optional native selection roles win.
    editor = gm.findChild(QObject, "selectableEditor")
    fallback = editor.property("selectionColor")
    assert editor.property("selectedTextColor") == QColor("#c0caf5")
    root.setProperty("customSelectionColors", True)
    QTest.qWait(30)
    assert editor.property("selectionColor") == QColor("#e0af68")
    assert editor.property("selectedTextColor") == QColor("#1a1b26")
    root.setProperty("customSelectionColors", False)
    assert editor.property("selectionColor") == fallback

    # Dragging selects text, never the parent scroll area. A double click selects a word.
    y = flick.property("contentY")
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, position(gm, 4))
    QTest.qWait(30)
    assert controller.property("dragging") and flick.property("interactive"), (position(gm, 4), gm.width(), gm.height(), gm.property("selecting"), controller.property("owner"))
    QTest.mouseMove(view, position(gm, 9), 40)
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, position(gm, 9))
    QTest.qWait(30)
    assert "river" in gm.property("selectedText"), repr(gm.property("selectedText"))
    assert flick.property("interactive") and not controller.property("dragging")
    assert abs(flick.property("contentY") - y) < 1

    # Repeated/reverse vertical drags must retain the grab, not flick the page or
    # rewrite the rich document when the previous selection is cleared.
    source_changes = QSignalSpy(gm.renderedSourceChanged)
    for start, end in ((4, 80), (80, 4), (4, 9)):
        begin, finish = position(gm, start), position(gm, end)
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, begin)
        assert controller.property("dragging")
        for step in range(1, 9):
            QTest.mouseMove(view, begin + (finish - begin) * (step / 8), 15)
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, finish)
        assert (gm.property("selectionStart"), gm.property("selectionEnd")) == (min(start, end), max(start, end))
        assert abs(flick.property("contentY") - y) < 1 and not controller.property("dragging")
    assert source_changes.count() == 0
    QTest.mouseClick(view, Qt.LeftButton, Qt.ShiftModifier, position(gm, 80))
    assert (gm.property("selectionStart"), gm.property("selectionEnd")) == (4, 80)
    call(gm, "select", 4, 9)
    QTest.keyClick(view, Qt.Key_C, Qt.ControlModifier)
    assert "river" in clipboard.text()
    call(gm, "deselect")
    QTest.mouseDClick(view, Qt.LeftButton, Qt.NoModifier, position(gm, 6))
    QTest.qWait(30)
    assert gm.property("selectedText").strip() == "river", repr(gm.property("selectedText"))

    # Whole rich passages copy as readable text, without Markdown/HTML markers.
    QTest.keyClick(view, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(view, Qt.Key_C, Qt.ControlModifier | Qt.ShiftModifier)
    assert clipboard.text() == "The river is quiet, and the lamps are waiting.\nA second paragraph says listen first.", repr(clipboard.text())
    expected = clipboard.text()
    for modifiers in (Qt.MetaModifier, Qt.ControlModifier | Qt.MetaModifier):
        clipboard.setText("not copied")
        QTest.keyClick(view, Qt.Key_C, modifiers)
        assert clipboard.text() == expected
    clipboard.setText("not copied")
    QTest.keyClick(view, Qt.Key_Insert, Qt.ControlModifier)
    assert clipboard.text() == expected
    view.grabWindow().save(str(out / "selected-passage.png"))

    # The right-click menu keeps the existing selection and copies it unchanged.
    call(gm, "select", 4, 9)
    QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, position(gm, 6))
    QTest.qWait(50)
    menu = gm.findChild(QObject, "passageCopyMenu")
    assert menu.property("opened") and gm.property("selectedText") == "river"
    action = menu.findChild(QObject, "copyPassageAction")
    assert action.property("text") == "Copy"
    def click_action(item):
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point)
        QTest.qWait(30)
    click_action(action)
    assert clipboard.text() == "river" and not menu.property("opened")
    QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, position(gm, 6))
    QTest.qWait(30)
    clipboard.setText("not copied")
    QTest.keyClick(view, Qt.Key_C, Qt.MetaModifier)
    assert clipboard.text() == "river" and not menu.property("opened")
    call(gm, "deselect")
    QTest.qWait(30)
    QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, position(gm, 6))
    QTest.qWait(30)
    assert controller.property("engaged"), "An open passage menu also pauses following"
    original_prose = root.property("prose")
    menu_source = gm.property("renderedSource")
    root.setProperty("prose", original_prose + "\n\nMore words arrive while the menu is open.")
    QTest.qWait(30)
    assert gm.property("renderedSource") == menu_source and gm.property("selectedText") == ""
    click_action(action)
    assert clipboard.text() == expected and gm.property("selectedText") == ""
    QTest.qWait(100)
    assert "More words arrive" in gm.property("renderedSource"), "Closing the menu must show buffered text"
    root.setProperty("prose", original_prose)
    QTest.qWait(30)
    QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, position(gm, 6))
    QTest.qWait(30)
    input_.forceActiveFocus()
    QTest.qWait(30)
    assert not menu.property("opened") and not controller.property("engaged")
    assert input_.property("activeFocus"), "Closing a passage menu must not steal composer focus"
    QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, position(gm, 6))
    QTest.qWait(30)
    click_action(menu.findChild(QObject, "selectPassageAction"))
    assert gm.property("selectedText") != "" and not menu.property("opened")

    # Source updates are buffered during a selection, then shown on Escape.
    call(gm, "select", 4, 9)
    root.setProperty("prose", "The storm is coming. More narration arrives while the player copies.")
    QTest.qWait(40)
    assert gm.property("selectedText") == "river"
    call(gm, "copy")
    assert clipboard.text() == "river"
    QTest.keyClick(view, Qt.Key_Escape)
    QTest.qWait(30)
    assert gm.property("selectedText") == ""
    assert "storm" in gm.findChild(QObject, "selectableEditor").property("text")

    # Plain passages remain literal and read-only, including HTML-looking text.
    call(plain, "selectAll")
    call(plain, "copy")
    assert clipboard.text() == "Player: I say <b>hello</b> & wait."
    before = plain.findChild(QObject, "selectableEditor").property("text")
    type_text(view, "cannot edit this")
    QTest.keyClick(view, Qt.Key_Delete)
    QTest.keyClick(view, Qt.Key_V, Qt.ControlModifier)
    assert plain.findChild(QObject, "selectableEditor").property("text") == before
    QTest.keyClick(view, Qt.Key_Home, Qt.ControlModifier)
    QTest.keyClick(view, Qt.Key_Right, Qt.ShiftModifier)
    QTest.keyClick(view, Qt.Key_C, Qt.ControlModifier)
    assert clipboard.text() == "P"
    assert gm.property("selectedText") == "" and controller.property("owner") == plain

    # Illuminated initials are not copied with table boundaries or extra newlines.
    call(dropcap, "selectAll")
    call(dropcap, "copy")
    assert clipboard.text() == "Marrow Ford lies quiet.", repr(clipboard.text())
    input_.forceActiveFocus()
    QTest.qWait(30)
    assert dropcap.property("selectedText") == "" and not controller.property("engaged")
    QTest.keyClick(view, Qt.Key_End, Qt.ControlModifier)
    type_text(view, "!")
    assert input_.property("text").endswith("editable!")

    # Touch swipes still scroll; only real mouse drags retain a selection grab.
    device = QTest.createTouchDevice()
    touch = QTest.touchEvent(view, device)
    start = position(gm, 50)
    touch.press(0, start, view).commit()
    QTest.qWait(30)
    for step in range(1, 7):
        touch.move(0, start - QPoint(0, step * 12), view).commit()
        QTest.qWait(20)
    touch.release(0, start - QPoint(0, 72), view).commit()
    QTest.qWait(100)
    assert flick.property("contentY") > 10 and not controller.property("dragging")

    # Test the actual Book: live narration, guarded scrolling and Codex text.
    book_view, harness = load("Harness.qml")
    book = harness.findChild(QObject, "book")
    book_controller = harness.findChild(QObject, "bookTextSelection")
    story_view = harness.findChild(QObject, "bookStoryView")
    live = harness.findChild(QObject, "livePassage")
    harness.setProperty("turn", {"status": "writing", "text": "A lamp is lit.\n\nThe first name is spoken."})
    QTest.qWait(1000)
    call(live, "selectAll")
    call(live, "copy")
    copied = clipboard.text()
    assert copied == "A lamp is lit.\nThe first name is spoken." and "▌" not in copied, repr(copied)
    assert book_controller.property("engaged")
    old_y = story_view.property("contentY")
    harness.setProperty("turn", {"status": "writing", "text": "A lamp is lit.\n\nThe first name is spoken. The wind drops."})
    QTest.qWait(400)
    assert "wind drops" in live.property("text")
    call(live, "copy")
    assert clipboard.text() == copied
    assert story_view.property("contentY") == old_y
    QTest.keyClick(book_view, Qt.Key_Escape)
    QTest.qWait(40)
    assert not book_controller.property("engaged")
    call(live, "copyPassage")
    assert clipboard.text().endswith("The wind drops.")

    # Reading never captures the composer or its normal editing/copy shortcuts.
    sent = QSignalSpy(book.send)
    call(live, "selectAll")
    composer = book.findChild(QObject, "bookInput")
    composer.forceActiveFocus()
    assert not book_controller.property("engaged")
    type_text(book_view, "a draft")
    QTest.keyClick(book_view, Qt.Key_A, Qt.ControlModifier)
    QTest.keyClick(book_view, Qt.Key_C, Qt.ControlModifier)
    assert clipboard.text() == "a draft" and sent.count() == 0

    import scenario
    scenario.play_ironsworn(work)
    game = json.loads((work / "ironsworn.json").read_text())
    harness.setProperty("turn", {"status": "idle"})
    harness.setProperty("game", game)
    book.setProperty("codexOpen", True)
    QTest.qWait(100)
    codex_passages = [p for p in visual_items(book) if p.objectName() == "codexPassage" and p.property("visible") and "Tam" in p.property("text")]
    assert codex_passages, game.get("codex")
    QTest.mouseDClick(book_view, Qt.LeftButton, Qt.NoModifier, position(codex_passages[0], 1))
    QTest.qWait(30)
    QTest.keyClick(book_view, Qt.Key_C, Qt.MetaModifier)
    assert clipboard.text() == "Tam", repr(clipboard.text())
    QTest.mouseClick(book_view, Qt.RightButton, Qt.NoModifier, position(codex_passages[0], 1))
    QTest.qWait(30)
    codex_menu = codex_passages[0].findChild(QObject, "passageCopyMenu")
    assert codex_menu.property("opened")
    book_view.grabWindow().save(str(out / "selected-codex.png"))
    book.setProperty("campaign", "/another/example")
    assert not book_controller.property("engaged") and book_controller.property("owner") is None
    assert not codex_menu.property("opened"), "Campaign changes must dismiss old copy actions"

    # Destroying a selected passage releases the controller (virtualized delegates).
    call(plain, "selectAll")
    plain.deleteLater()
    QTest.qWait(30)
    assert controller.property("owner") is None and not controller.property("engaged")
    # A pending follow callback belongs to its list and dies with the Book.
    call(story_view, "follow")
    for window in views:
        window.setSource(QUrl())
    QTest.qWait(30)
    assert not errors, "\n".join(errors)
    print("Book selection checks passed: repeated/reverse vertical drags, Shift-click/word/keyboard selection, Super+C/Ctrl+C/Ctrl+Shift+C/Ctrl+Insert, actual menu clicks, touch scrolling, plain clipboard, read-only text, live updates, scrolling, Codex and lifecycle.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
