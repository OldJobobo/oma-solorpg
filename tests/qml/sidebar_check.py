"""Long vow titles wrap in the Book's margin instead of stealing the story's width.

    QT_QPA_PLATFORM=offscreen python3 tests/qml/sidebar_check.py <out folder>

Uses the same plain-QtQuick harness as render.py; no shell or desktop effects run.
"""

import copy
import json
import math
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from PySide6.QtCore import QObject, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402

import scenario  # noqa: E402


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as data:
        scenario.play_ironsworn(data)
        game = json.loads((Path(data) / "ironsworn.json").read_text())

    app = QGuiApplication(sys.argv)
    view = QQuickView()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.engine().addImportPath(str(HERE / "stubs"))
    problems = []
    view.engine().warnings.connect(lambda warnings: problems.extend(w.toString() for w in warnings))
    view.setSource(QUrl.fromLocalFile(str(HERE / "Harness.qml")))
    if view.status() == QQuickView.Status.Error:
        print("\n".join(e.toString() for e in view.errors()))
        return 1
    view.show()
    root = view.rootObject()
    assert root is not None
    theme = root.findChild(QObject, "soloTheme")
    side = root.findChild(QObject, "bookSidebar")
    story = root.findChild(QObject, "bookStory")
    vitals = root.findChild(QObject, "bookVitals")
    assert theme is not None and side is not None and story is not None and vitals is not None

    def items(item):
        yield item
        for child in item.childItems():
            yield from items(child)

    def wait():
        timer = QTimer()
        timer.setSingleShot(True)
        timer.start(100)
        while timer.isActive():
            app.processEvents()

    titles = ("A promise", "Find the lost lantern and bring it safely home " * 6, "Lantern" * 140)
    sizes = {key: theme.property(key) for key in ("small", "body", "prose", "heading")}
    for scale in (1, 1.5):
        for key, size in sizes.items():
            theme.setProperty(key, size * scale)
        for width in (850, 1100, 1600):
            view.resize(width, 860)
            baseline = None
            for index, title in enumerate(titles):
                state = copy.deepcopy(game)
                state["progress"]["silence_the_bell"]["name"] = title
                root.setProperty("game", state)
                wait()
                geometry = (side.property("width"), story.property("width"))
                label = next(t for t in items(root) if t.objectName() == "progressTitle"
                             and t.property("text").startswith(title))
                context = f"{width}px at {scale}x, title {index}"
                print(f"{context}: sidebar {geometry[0]:.1f}, story {geometry[1]:.1f}, lines {label.property('lineCount')}")
                if baseline is None:
                    baseline = geometry
                elif not all(math.isclose(a, b, abs_tol=1) for a, b in zip(geometry, baseline)):
                    problems.append(f"{context}: long title changed widths from {baseline} to {geometry}")
                if label.property("width") > side.property("width") + 1:
                    problems.append(f"{context}: title overflows the sidebar")
                if index and label.property("lineCount") <= 1:
                    problems.append(f"{context}: long title did not wrap")
                if geometry[1] <= 0:
                    problems.append(f"{context}: no room left for the story")
                if vitals.property("width") > geometry[0] + 1:
                    problems.append(f"{context}: the margin clips the hero's meters")
                if scale == 1 and width == 1100:
                    view.grabWindow().save(str(out / f"vow-{index}.png"))
            if not side.property("contentHeight") > side.property("height"):
                problems.append(f"{width}px at {scale}x: long sidebar cannot scroll vertically")
    if problems:
        print("Sidebar errors:\n  " + "\n  ".join(problems))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
