"""Theme changes, contrast and Book control interaction, without a desktop.

    QT_QUICK_BACKEND=software python3 tests/qml/theme_check.py <screenshots folder>

The native border parser/renderer is Omarchy's responsibility. Our stand-ins expose
specs so these checks catch flattening/dropping those specs at the plugin boundary.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import SIGNAL, QObject, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402


def variant(value):
    return value.toVariant() if hasattr(value, "toVariant") else value


def over(ink, paper):
    a = ink.alphaF()
    return QColor.fromRgbF(*(x * a + y * (1 - a) for x, y in zip(ink.getRgbF()[:3], paper.getRgbF()[:3])))


def contrast(ink, paper):
    def luminance(color):
        def linear(n):
            return n / 12.92 if n <= .04045 else ((n + .055) / 1.055) ** 2.4
        return sum(w * linear(v) for w, v in zip((.2126, .7152, .0722), color.getRgbF()[:3]))
    a, b = sorted((luminance(over(ink, paper)), luminance(paper)))
    return (b + .05) / (a + .05)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    # Campaign.create selects its new campaign through XDG_STATE_HOME. Isolate
    # it even when invoked directly from a desktop exporting the real state path.
    state = Path(tempfile.mkdtemp())
    os.environ["XDG_STATE_HOME"] = str(state / "state")
    os.environ["SOLO_HOME"] = str(state / "games")
    app = QGuiApplication(sys.argv)
    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.engine().addImportPath(str(HERE / "stubs"))
    errors = []
    view.engine().warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
    view.setSource(QUrl.fromLocalFile(str(HERE / "Harness.qml")))
    assert view.status() != QQuickView.Error, "\n".join(e.toString() for e in view.errors())
    view.show()
    app.processEvents()
    root = view.rootObject()
    book = root.findChild(QObject, "book")
    theme = root.findChild(QObject, "soloTheme")
    colors = view.engine().singletonInstance("qs.Commons", "Color")
    style = view.engine().singletonInstance("qs.Commons", "Style")
    borders = view.engine().singletonInstance("qs.Commons", "Border")
    popups = colors.property("popups")
    input_ = root.findChild(QObject, "bookInput")
    composer = root.findChild(QObject, "composerSurface")
    placeholder = root.findChild(QObject, "bookPlaceholder")
    codex = root.findChild(QObject, "codexLink")

    import scenario
    with tempfile.TemporaryDirectory() as folder:
        scenario.play_ironsworn(folder)
        game = json.loads((Path(folder) / "ironsworn.json").read_text())
    root.setProperty("game", game)
    QTest.qWait(100)

    palettes = [
        ("miasma", "#1c1c1c", "#c2c2b0", "#8a8a7e", "#78824b", "#685742"),
        ("light", "#f4f0e6", "#302c26", "#bdb9b0", "#d9cfac", "#edbcb0"),
        ("low-contrast", "#555555", "#dddddd", "#666666", "#666666", "#555555"),
    ]
    for name, bg, fg, muted, accent, urgent in palettes:
        colors.setProperty("background", QColor(bg))
        colors.setProperty("foreground", QColor(fg))
        colors.setProperty("muted", QColor(muted))
        colors.setProperty("accent", QColor(accent))
        colors.setProperty("urgent", QColor(urgent))
        popups.setProperty("background", QColor(bg))
        popups.setProperty("text", QColor(fg))
        for key, ink in (("normalInk", fg), ("hoverInk", accent), ("focusInk", accent),
                         ("selectedInk", accent), ("pressedInk", urgent)):
            style.setProperty(key, QColor(ink))
        QTest.qWait(50)
        paper = theme.property("surfacePaper")
        for role in ("dim", "urgentText", "accentText"):
            ratio = contrast(theme.property(role), paper)
            assert ratio >= 4.5, (name, role, ratio)
        # Semantic/effect colors are never rewritten by the text contrast guard.
        assert theme.property("urgent") == QColor(urgent)
        assert theme.property("accent") == QColor(accent)
        assert theme.property("gold") == QColor("#d9a441")
        selected_paper = over(theme.property("selection"), over(QColor(theme.controlFill("focus")), paper))
        assert contrast(theme.property("selectedText"), selected_paper) >= 4.5, name
        assert input_.property("selectionColor") == theme.property("selection")
        assert input_.property("selectedTextColor") == theme.property("selectedText")
        for state in ("normal", "hover-cursor", "focus"):
            composer.setProperty("controlState", state)
            QTest.qWait(20)
            painted = over(composer.property("surface").property("color"), paper)
            assert contrast(placeholder.property("color"), painted) >= 4.5, (name, state)
        for state in ("normal", "hover-cursor", "focus", "pressed", "selected", "disabled"):
            codex.setProperty("down", state == "pressed")
            # Check the native factory receives the state, with gradient metadata intact.
            composer.setProperty("controlState", state)
            QTest.qWait(10)
            native = composer.property("surface")
            assert native.property("controlState") == state
            painted = over(native.property("color"), paper)
            assert contrast(QColor(theme.controlText(state)), painted) >= 4.5, (name, state)
            spec = variant(native.property("borderSpec"))
            assert spec["widths"]["top"] == (0 if state in ("selected", "disabled") else 1)
            if state != "disabled":
                assert spec["gradient"]["enabled"]
        codex.setProperty("down", False)
        composer.setProperty("controlState", "normal")
        view.grabWindow().save(str(out / f"book-{name}.png"))

    # The shared border contract retains asymmetric edges too.
    borders.setProperty("popupWidths", {"top": 0, "right": 3, "bottom": 2, "left": 1})
    assert variant(borders.property("popupWidths"))["right"] == 3

    # Focus + keyboard activation are real Qt button behavior, not MouseArea-only.
    codex.forceActiveFocus()
    QTest.qWait(20)
    assert codex.property("controlState") == "focus"
    QTest.keyClick(view, Qt.Key_Space)
    assert book.property("codexOpen")
    QTest.keyClick(view, Qt.Key_Space)
    assert not book.property("codexOpen")

    sent, stopped = [], []
    QObject.connect(book, SIGNAL("send(QString)"), sent.append)
    QObject.connect(book, SIGNAL("stop()"), lambda: stopped.append(True))
    input_.forceActiveFocus()
    QTest.qWait(20)
    assert composer.property("controlState") == "focus"
    input_.setProperty("text", "I listen")
    QTest.keyClick(view, Qt.Key_Return, Qt.ShiftModifier)
    assert "\n" in input_.property("text") and not sent
    QTest.keyClick(view, Qt.Key_Return)
    assert sent == ["I listen"] and input_.property("text") == ""
    book.setProperty("turn", {"status": "writing", "text": "..."})
    send = root.findChild(QObject, "sendButton")
    assert send.property("enabled") and send.property("text") == "stop"
    send.forceActiveFocus()
    QTest.keyClick(view, Qt.Key_Space)
    assert stopped == [True]
    book.setProperty("turn", {"status": "idle"})
    assert not send.property("enabled")

    # One line of prose sits centred in the composer, even when "send" is the taller of the two,
    # and the cut panel's actions start where its text does.
    composer_item = root.findChild(QQuickItem, "composerSurface")
    input_item = root.findChild(QQuickItem, "bookInput")
    for prose in (9, 16, 27):
        theme.setProperty("prose", prose)
        QTest.qWait(50)
        box = composer_item.mapToScene(QPointF(0, composer_item.height() / 2)).y()
        line = input_item.mapToScene(QPointF(0, input_item.implicitHeight() / 2)).y()
        assert abs(box - line) <= 1, (prose, box, line)
    theme.setProperty("prose", 16)
    book.setProperty("cutting", True)
    QTest.qWait(50)
    first = root.findChild(QQuickItem, "cutNow")
    note = root.findChild(QQuickItem, "cutInput")
    label = first.mapToScene(QPointF(first.property("leftPadding"), 0)).x()
    assert abs(label - note.mapToScene(QPointF(0, 0)).x()) <= 1, (label, note.mapToScene(QPointF(0, 0)).x())
    book.setProperty("cutting", False)

    # Safety actions wrap instead of overflowing at narrow widths/enlarged text.
    book.setProperty("cutting", True)
    cut = root.findChild(QObject, "cutInput")
    cut.setProperty("text", "no spiders")
    for width in (640, 900, 1280):
        for size in (12, 18):
            theme.setProperty("body", size)
            theme.setProperty("small", size)
            theme.setProperty("prose", size * 1.5)
            view.resize(width, 860)
            QTest.qWait(80)
            actions = root.findChild(QObject, "cutActions")
            navigation = root.findChild(QObject, "bookNavigation")
            for group in (actions, navigation):
                for child in group.childItems():
                    if child.isVisible():
                        assert child.x() + child.width() <= group.width() + 1, (width, size, group.objectName(), group.width(), child.property("text"), child.x(), child.width())
            header = root.findChild(QObject, "bookHeader")
            if header.property("columns") == 1:
                title = header.childItems()[0]
                assert navigation.y() >= title.y() + title.height()
            view.grabWindow().save(str(out / f"cut-{width}-{size}.png"))
    assert not errors, "\n".join(errors)
    print("Theme checks passed: dark/light/low-contrast palettes, live bindings, native specs, selection, keyboard, wrapping.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
