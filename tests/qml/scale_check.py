"""Book app-zoom geometry and keyboard controls, independent of a live desktop."""

import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import QObject, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp())
    os.environ["XDG_STATE_HOME"] = str(work / "state")
    os.environ["SOLO_HOME"] = str(work / "games")
    import scenario
    scenario.play(work)
    game = json.loads((work / "fight.json").read_text())
    app = QGuiApplication(sys.argv)
    view = QQuickView()
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.engine().addImportPath(str(HERE / "stubs"))
    errors = []
    view.engine().warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
    view.setSource(QUrl.fromLocalFile(str(HERE / "Harness.qml")))
    assert view.status() != QQuickView.Error, "\n".join(e.toString() for e in view.errors())
    view.show()
    view.requestActivate()
    root = view.rootObject()
    root.setProperty("game", game)
    book = root.findChild(QObject, "book")
    viewport = root.findChild(QObject, "bookViewport")
    frame = root.findChild(QObject, "bookSidebarFrame")
    side = root.findChild(QObject, "bookSidebar")
    footer = root.findChild(QObject, "bookScaleFooter")
    layout = root.findChild(QObject, "bookPageLayout")
    story = root.findChild(QObject, "bookStory")
    composer = root.findChild(QObject, "composerSurface")
    input_ = root.findChild(QObject, "bookInput")
    increase = root.findChild(QObject, "bookScaleIncrease")
    decrease = root.findChild(QObject, "bookScaleDecrease")
    reset = root.findChild(QObject, "bookScaleReset")
    combat_toggle = root.findChild(QObject, "bookCombatToggle")
    input_.setProperty("text", "I keep this unwritten thought.")
    seen = book.property("seen")

    for width in (1280, 900, 640):
        view.resize(width, 860)
        for scale in (1, 1.25, 1.5, 1.75, 2):
            root.setProperty("bookScale", scale)
            QTest.qWait(100)
            canvas = viewport.property("canvas")
            assert abs(canvas.width() * scale - width) < 1
            assert abs(book.height() * scale - 860) < 1
            assert book.property("bookScale") == scale
            assert book.property("seen") == seen, "zoom replayed the story"
            assert input_.property("text") == "I keep this unwritten thought.", "zoom lost the draft message"
            assert footer.y() + footer.height() <= frame.height() + 1, (width, scale, "unreachable footer")
            assert side.y() + side.height() <= footer.y() + 1
            assert frame.y() + frame.height() <= layout.height() + 1
            assert story.y() + story.height() <= layout.height() + 1
            assert composer.y() + composer.height() <= story.height() + 1
            assert root.findChild(QObject, "bookStoryView").height() > 0, (width, scale, "no room for story")
            # Validate actual scene-graph scaling, not just a selected setting label.
            a = increase.mapToScene(QPointF(0, 0))
            b = increase.mapToScene(QPointF(increase.width(), 0))
            assert abs(b.x() - a.x() - increase.width() * scale) < 1
            if layout.property("stacked"):
                assert story.y() >= frame.y() + frame.height()
                assert combat_toggle.isVisible()
            view.grabWindow().save(str(out / f"book-scale-{width}-{scale}.png"))

    # Quiet footer actions remain keyboard-operable at the largest zoom.
    decrease.forceActiveFocus()
    QTest.keyClick(view, Qt.Key_Space)
    assert root.property("bookScale") == 1.75
    reset.forceActiveFocus()
    QTest.keyClick(view, Qt.Key_Return)
    assert root.property("bookScale") == 1
    assert not decrease.property("enabled")
    for scale in (1.25, 1.5, 1.75, 2):
        increase.forceActiveFocus()
        QTest.keyClick(view, Qt.Key_Space)
        assert root.property("bookScale") == scale
    assert not increase.property("enabled")
    reset.forceActiveFocus()
    QTest.keyClick(view, Qt.Key_Enter)
    assert root.property("bookScale") == 1
    root.setProperty("bookScale", 2)
    # Hero scrolling cannot move the fixed scale footer away.
    QTest.qWait(100)
    before = footer.mapToScene(QPointF(0, 0))
    side.setProperty("contentY", max(0, side.property("contentHeight") - side.height()))
    QTest.qWait(30)
    assert footer.mapToScene(QPointF(0, 0)) == before
    combat_toggle.forceActiveFocus()
    QTest.keyClick(view, Qt.Key_Space)
    QTest.qWait(50)
    assert root.findChild(QObject, "bookCombatView").isVisible()
    assert composer.y() + composer.height() <= story.height() + 1, (composer.y(), composer.height(), story.height(), [(child.objectName(), child.y(), child.height()) for child in story.childItems() if child.isVisible()])
    assert not errors, "\n".join(errors)
    print("Book scale checks passed: five steps, three widths, physical scaling, fixed footer, story/draft preservation, keyboard and compact fight access.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
