"""Render Book meters against synthetic values, without a campaign or desktop.

Checks solid/empty resource tracks, signed/capped Momentum, quarter-box progress,
normal text spacing and flat raster edges at every Book zoom. Run a second time
with QT_SCALE_FACTOR=1.5 for fractional-DPI coverage. Needs only PySide6.
"""
import math
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent

from PySide6.QtCore import QPointF, QUrl  # noqa: E402
from PySide6.QtGui import QFont, QFontMetricsF, QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlEngine, QQmlExpression  # noqa: E402
from PySide6.QtQuick import QQuickItem, QQuickView  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402


def items(item: QQuickItem):
    yield item
    for child in item.childItems():
        yield from items(child)


def renderers(root: QQuickItem):
    for item in items(root):
        if item.metaObject().indexOfProperty("renderType") < 0:
            continue
        # Only bar glyphs use their component's local override. Labels, values
        # and the control text keep Qt's original/default renderer.
        expected = "parent.glyphRenderType" if item.objectName() in ("meterCellLayout", "meterCellGlyphs") else "Text.QtRendering"
        expression = QQmlExpression(QQmlEngine.contextForObject(item), item, "renderType === " + expected)
        value, undefined = expression.evaluate()
        assert not expression.hasError(), expression.error().toString()
        assert value and not undefined, (item.objectName(), expected)


def flat_runs(blocks: QQuickItem):
    glyphs = blocks.findChild(QQuickItem, "meterCellGlyphs")
    layout = blocks.findChild(QQuickItem, "meterCellLayout")
    assert glyphs is not None and layout is not None
    assert "█" not in glyphs.property("text") and not layout.property("visible")
    flat_empty = blocks.property("emptyColor").alphaF() > 0
    if flat_empty:
        assert "░" not in glyphs.property("text")
    else:
        assert glyphs.property("text").count("░") == blocks.property("text").count("░")
    advance = QFontMetricsF(blocks.property("font")).horizontalAdvance("█")
    result = []
    for glyph, name, enabled in (("█", "solidBlockRun", True), ("░", "emptyBlockRun", flat_empty)):
        expected = [match.span() for match in re.finditer(glyph + "+", blocks.property("text"))] if enabled else []
        runs = sorted((item for item in blocks.childItems() if item.objectName() == name), key=lambda item: item.x())
        assert len(runs) == len(expected), (name, expected, len(runs))
        for run, (start, end) in zip(runs, expected):
            assert abs(run.x() - start * advance) < 1e-5
            assert abs(run.width() - (end - start) * advance) < 1e-5
            assert run.height() > 0 and run.property("radius") == 0
            assert not run.property("antialiasing")
        result.extend(runs)
    return result


def flat_pixels(image, run: QQuickItem, dpr):
    top_left = run.mapToScene(QPointF(0, 0)) * dpr
    bottom_right = run.mapToScene(QPointF(run.width(), run.height())) * dpr
    # Software rendering may snap a cached rect before applying app zoom.
    # Exclude one logical pixel at either side, not just one output pixel.
    padding = max(1, math.ceil((bottom_right.x() - top_left.x()) / run.width()))
    left, right = math.ceil(top_left.x()) + padding, math.floor(bottom_right.x()) - padding
    top, bottom = math.floor(top_left.y()) - 2, math.ceil(bottom_right.y()) + 2
    assert left <= right and 0 <= top < bottom < image.height()
    center_x = (left + right) // 2
    foreground = image.pixel(center_x, round((top_left.y() + bottom_right.y()) / 2))
    assert foreground != image.pixel(center_x, top), "track disappeared into the background"
    expected = None
    for x in range(left, right + 1):
        rows = tuple(y for y in range(top, bottom + 1) if image.pixel(x, y) == foreground)
        assert rows and rows == tuple(range(rows[0], rows[-1] + 1)), "gap in a run"
        if expected is None:
            expected = rows
        assert rows == expected, "uneven top/bottom edges"


def baseline_labels(row, blocks, label_name, value_name, spaces):
    label = row.findChild(QQuickItem, label_name) if label_name else None
    value = row.findChild(QQuickItem, value_name)
    assert value is not None
    baseline = blocks.mapToScene(QPointF(0, blocks.property("baselineOffset"))).y()
    for item in (label, value) if label is not None else (value,):
        assert item.property("font").letterSpacing() == 0
        assert abs(item.mapToScene(QPointF(0, item.property("baselineOffset"))).y() - baseline) < 1e-5
    width = QFontMetricsF(value.property("font")).horizontalAdvance(spaces)
    assert abs(row.property("spacing") - width) < 1e-5
    return value


def resources(root):
    meters = [item for item in items(root) if item.objectName() == "resourceMeter"]
    assert meters
    result = []
    for meter in meters:
        blocks = meter.findChild(QQuickItem, "resourceMeterBlocks")
        assert blocks is not None
        assert blocks.property("font").letterSpacing() == -1
        assert blocks.property("emptyColor").alphaF() > 0
        reading = baseline_labels(meter, blocks, "resourceMeterLabel", "resourceMeterValue", "\u00a0")
        assert reading.property("text") == f"{meter.property('value')}/{meter.property('maximum')}"
        source = blocks.property("text")
        assert source.count("█") == meter.property("filled")
        assert source.count("░") == meter.property("cells") - meter.property("filled")
        normal = QFont(blocks.property("font"))
        normal.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
        assert 0 < blocks.width() < QFontMetricsF(normal).horizontalAdvance(source)
        result.extend(flat_runs(blocks))
    return meters, result


def progress(root, ticks):
    meters = [item for item in items(root) if item.objectName() == "progressMeter"]
    assert len(meters) == 2, "both vow and road must be checked"
    expected = "".join("░▂▄▆█"[max(0, min(4, ticks - box * 4))] for box in range(10))
    result = []
    for meter in meters:
        blocks = meter.findChild(QQuickItem, "progressMeterBlocks")
        assert blocks is not None and blocks.property("text") == expected
        assert blocks.property("font").letterSpacing() == 0
        assert blocks.property("glyphRenderType") == 0
        assert blocks.property("emptyColor").alphaF() == 0
        glyphs = blocks.findChild(QQuickItem, "meterCellGlyphs")
        assert glyphs is not None and glyphs.property("text") == expected.replace("█", "\u00a0")
        reading = baseline_labels(meter, blocks, None, "progressMeterValue", "  ")
        assert reading.property("text") == f"{ticks // 4} of 10"
        result.extend(flat_runs(blocks))
    return result


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication(sys.argv)
    view = QQuickView()
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    errors = []
    view.engine().warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
    view.setSource(QUrl.fromLocalFile(str(HERE / "MeterHarness.qml")))
    assert view.status() != QQuickView.Status.Error, "\n".join(e.toString() for e in view.errors())
    view.show()
    app.processEvents()
    root = view.rootObject()
    assert root is not None
    momentum = root.findChild(QQuickItem, "momentumMeter")
    assert momentum is not None
    bar = momentum.findChild(QQuickItem, "momentumMeterBlocks")
    assert bar is not None and bar.property("emptyColor").alphaF() == 0

    for family in ("monospace", "DejaVu Sans Mono"):
        root.setProperty("fontFamily", family)
        for size in (11, 14, 18):
            root.setProperty("fontSize", size)
            for zoom in (1, 1.25, 1.5, 1.75, 2):
                root.setProperty("zoom", zoom)
                root.setProperty("progressTicks", 18)
                for resource, value, ceiling in ((0, 0, 10), (1, -6, 10), (3, -2, 10),
                                                  (5, 1, 10), (5, 4, 10), (5, 10, 10), (4, 8, 6)):
                    root.setProperty("resource", resource)
                    root.setProperty("momentum", {"value": value, "max": ceiling})
                    QTest.qWait(20)
                    expected = "".join("█" if value < 0 and n >= value else "░" for n in range(-6, 0)) + "│"
                    expected += "".join("·" if n > ceiling else "█" if value >= n else "░" for n in range(1, 11))
                    assert bar.property("text") == expected
                    assert bar.property("font").letterSpacing() == 0
                    reading = baseline_labels(momentum, bar, "momentumMeterLabel", "momentumMeterValue", "\u00a0")
                    assert reading.property("text") == ("+" if value > 0 else "") + str(value)
                    _, runs = resources(root)
                    runs += flat_runs(bar) + progress(root, 18)
                    image = view.grabWindow()
                    for run in runs:
                        flat_pixels(image, run, view.devicePixelRatio())
                    renderers(root)
                    if family == "monospace" and resource == 3 and value == -2:
                        assert image.save(str(out / f"meters-{size}-{zoom}.png"))
                for ticks in (0, 1, 2, 3, 4, 5, 6, 7, 16, 17, 18, 19, 39, 40):
                    root.setProperty("progressTicks", ticks)
                    QTest.qWait(20)
                    image = view.grabWindow()
                    for run in progress(root, ticks):
                        flat_pixels(image, run, view.devicePixelRatio())

    meter = resources(root)[0][0]
    for value, maximum, filled in ((0, 14, 0), (1, 14, 1), (3, 5, 8), (14, 14, 14),
                                  (30, 14, 14), (-2, 14, 0), (0, 0, 0)):
        meter.setProperty("value", value)
        meter.setProperty("maximum", maximum)
        QTest.qWait(20)
        assert meter.property("filled") == filled
        assert meter.property("low") == (value * 4 <= maximum)
        resources(root)
    assert not errors, "\n".join(errors)
    view.setSource(QUrl())
    QTest.qWait(20)
    print(f"Meter checks passed: two fonts, three sizes, five zooms, DPR {view.devicePixelRatio()}, "
          "signed/capped Momentum, quarter-box progress, flat raster edges and unchanged text spacing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
