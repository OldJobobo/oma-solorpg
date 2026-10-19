"""Render reproducible, invented Book selection examples; no desktop or model calls.

    python3 tests/qml/selection_visuals.py <output folder>

Needs the same PySide6 as qml-check and ffmpeg for the animated GIFs. Captions and
pointer rings are demo annotations, not additional Book controls.
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_QPA_PLATFORMTHEME"] = ""
os.environ["QT_SCALE_FACTOR"] = "1"
os.environ.setdefault("QT_QUICK_BACKEND", "software")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import QObject, QPointF, QRect, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402
from PySide6.QtTest import QSignalSpy, QTest  # noqa: E402
from selection_check import call, position, visual_items  # noqa: E402


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is needed to produce the animated examples")
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        os.environ["XDG_STATE_HOME"] = str(work / "state")
        os.environ["SOLO_HOME"] = str(work / "games")
        import scenario
        scenario.play_ironsworn(work)
        game = json.loads((work / "ironsworn.json").read_text())
        # Only the permitted fixture's sheet supplies rule values; all visible prose
        # below is invented for this demonstration, never a player's campaign.
        game.update(title="The Lantern Road", scene_title="Riverside Landing", progress={}, route=[])
        prose = "Merrin sets **a brass key** beside the lantern.\n\nThe east path is dry. Which way do you take?"
        expected = prose.replace("**", "").replace("\n\n", "\n")
        game["story"] = [{"seq": 1, "kind": "player", "text": "I wait by the lantern."},
                         {"seq": 2, "kind": "gm", "text": prose}]
        app = QGuiApplication(sys.argv)
        errors = []
        view = QQuickView()
        view.setResizeMode(QQuickView.SizeRootObjectToView)
        view.engine().warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
        view.setSource(QUrl.fromLocalFile(str(HERE / "Harness.qml")))
        assert view.status() != QQuickView.Error, "\n".join(e.toString() for e in view.errors())
        view.resize(1040, 720)
        view.show()
        root = view.rootObject()
        book = root.findChild(QObject, "book")
        sent = QSignalSpy(book.send)
        root.setProperty("game", game)
        QTest.qWait(500)
        column = root.findChild(QObject, "bookStory")
        corner = column.mapToScene(QPointF(0, 0))
        # Crop the actual passage/composer area, not the empty upper page.
        crop = QRect(int(corner.x()) - 8, view.height() - 240, int(column.width()) + 16, 240)
        frames = work / "frames"
        frames.mkdir()
        number = 0

        def frame(caption, count=1, pointer=None):
            nonlocal number
            last = None
            for _ in range(count):
                QTest.qWait(80)
                image = view.grabWindow().copy(crop)
                canvas = QImage(image.width(), image.height() + 64, QImage.Format_ARGB32)
                canvas.fill(QColor("#11131c"))
                painter = QPainter(canvas)
                painter.drawImage(0, 64, image)
                font = QFont("DejaVu Sans Mono")
                font.setPixelSize(17)
                painter.setFont(font)
                painter.setPen(QColor("#c0caf5"))
                painter.drawText(14, 26, caption)
                font.setPixelSize(11)
                painter.setFont(font)
                painter.setPen(QColor("#8791b3"))
                painter.drawText(14, 47, "OFFSCREEN INTERACTION DEMO · INVENTED TEXT · POINTER/CAPTIONS ANNOTATED")
                if pointer is not None:
                    painter.setRenderHint(QPainter.Antialiasing)
                    painter.setPen(QColor("#7aa2f7"))
                    painter.setBrush(QColor(122, 162, 247, 70))
                    painter.drawEllipse(QPointF(pointer.x() - crop.x(), pointer.y() - crop.y() + 64), 7, 7)
                painter.end()
                last = frames / f"{number:04}.png"
                assert canvas.save(str(last))
                number += 1
            return last

        def encode(name):
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", "12",
                            "-i", str(frames / "%04d.png"), "-filter_complex",
                            "[0:v]split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=3",
                            "-loop", "0", str(out / name)], check=True)
            for image in frames.iterdir():
                image.unlink()

        passage = next(item for item in visual_items(book) if item.objectName() == "storyPassage" and "Merrin" in item.property("text"))
        frame("1  Drag across the passage", 8)
        start, end = 0, passage.property("length")
        QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, position(passage, start))
        for step in range(1, 17):
            point = position(passage, round(end * step / 16))
            QTest.mouseMove(view, point, 15)
            frame("1  Drag across the passage", pointer=point)
        QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, position(passage, end))
        frame("1  One passage selected", 10)
        point = position(passage, 20)
        QTest.mouseClick(view, Qt.RightButton, Qt.NoModifier, point)
        frame("2  Right-click → Copy", 18, point)
        menu = passage.findChild(QObject, "passageCopyMenu")
        action = menu.findChild(QObject, "copyPassageAction")
        point = action.mapToScene(QPointF(action.width() / 2, action.height() / 2)).toPoint()
        QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, point)
        assert app.clipboard().text() == expected, repr(app.clipboard().text())
        composer = book.findChild(QObject, "bookInput")
        composer.forceActiveFocus()
        QTest.keyClick(view, Qt.Key_V, Qt.ControlModifier)
        assert composer.property("text") == expected
        result = frame("3  Paste — plain text, no markup", 24)
        shutil.copyfile(result, out / "copy-result.png")
        encode("drag-copy-paste.gif")

        number = 0
        crop = QRect(crop.x(), view.height() - 180, crop.width(), 180)
        composer.setProperty("text", "")
        empty = copy.deepcopy(game)
        empty["story"] = []
        root.setProperty("game", empty)
        initial = "A lantern glows beside the river.\n\nMerrin lowers her voice."
        root.setProperty("turn", {"status": "writing", "doing": "writing", "text": initial})
        QTest.qWait(1300)
        live = book.findChild(QObject, "livePassage")
        call(live, "selectAll")
        call(live, "select", 2, 9)
        assert live.property("selectedText") == "lantern"
        source = live.property("renderedSource")
        story = root.findChild(QObject, "bookStoryView")
        old_y = story.property("contentY")
        frame("1  Select a word while text streams", 16)
        latest = initial + " Behind her, a second lantern begins to shine."
        root.setProperty("turn", {"status": "writing", "doing": "writing", "text": latest})
        frame("2  Incoming text does not disturb selection", 26)
        assert live.property("renderedSource") == source
        assert live.property("selectedText") == "lantern"
        assert abs(story.property("contentY") - old_y) < 1
        QTest.keyClick(view, Qt.Key_Escape)
        frame("3  Escape reveals the latest text", 26)
        assert "second lantern" in live.property("renderedSource")
        encode("selection-holds-stream.gif")

        root.setProperty("turn", {"status": "idle"})
        root.setProperty("game", game)
        book.setProperty("codexOpen", True)
        QTest.qWait(200)
        name = next(item for item in visual_items(book) if item.objectName() == "codexPassage" and item.property("text") == "Tam")
        call(name, "selectAll")
        QTest.keyClick(view, Qt.Key_C, Qt.MetaModifier)
        assert app.clipboard().text() == "Tam"
        codex = book.findChild(QObject, "bookCodex")
        corner = codex.mapToScene(QPointF(0, 0))
        QTest.qWait(100)
        assert view.grabWindow().copy(QRect(int(corner.x()), int(corner.y()), int(codex.width()), 300)).save(str(out / "codex-selection.png"))
        assert sent.count() == 0, "The visual demo must never submit a GM request"
        view.setSource(QUrl())
        QTest.qWait(20)
        assert not errors, "\n".join(errors)
    print("Wrote invented, asserted Book examples:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
