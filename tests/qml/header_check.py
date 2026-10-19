"""The Table's controls keep their space; its title wraps below them.

Called by panel_check.py against the real Panel.qml, with shell actions stubbed out.
All titles here are invented, including markup-shaped input that must stay plain text.
"""

import json

from PySide6.QtCore import QMetaObject, QObject, QPointF, QRectF, Qt
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtTest import QTest


def check(item, panel, out, engine, wait):
    problems = []
    style = engine.singletonInstance("qs.Commons", "Style")
    assert isinstance(style, QObject)
    names = ("tableWindow", "tableHeader", "tableHeaderControls", "tableHeaderTitle",
             "tableCampaignsButton", "tableBackButton", "workspacePinButton", "tableCloseButton", "workspacePin")
    objects = {name: item.findChild(QObject, name) for name in names}
    assert all(obj is not None for obj in objects.values())
    window, header, controls, title, campaigns, back, pin_button, close, pin = objects.values()
    title_context, item_context = qmlContext(title), qmlContext(item)
    assert title_context is not None and item_context is not None
    plain_title = QQmlExpression(title_context, title, "textFormat === Text.PlainText")

    game = item.property("game")
    assert game.isObject()
    saved = (item.property("view"), window.width(), panel.width(), style.property("fontScale"))
    titles = ("A lantern", "Bring the lost lantern home across the winter marsh", "Lantern" * 18,
              "<b>A lantern</b> & <img src='file:///missing'>")

    def rect(child, parent):
        origin = child.mapToItem(parent, QPointF())
        return QRectF(origin.x(), origin.y(), child.width(), child.height())

    def call(obj, method):
        assert QMetaObject.invokeMethod(obj, method)
        wait(40)

    def set_pin(value):
        if pin.property("pinned") != value:
            call(pin, "togglePin")
        assert pin.property("pinned") == value

    def verify(context, navigation):
        bar = rect(controls, header)
        label = rect(title, header)
        if label.top() < bar.bottom() + 7:
            problems.append(f"{context}: title competes with the toolbar")
        if abs(label.width() - bar.width()) > 1 or bar.width() > window.width():
            problems.append(f"{context}: title does not own the bounded full width")
        if title.property("truncated") or title.property("contentWidth") > label.width() + 1:
            problems.append(f"{context}: title is clipped instead of wrapping")
        if not plain_title.evaluate()[0]:
            problems.append(f"{context}: campaign title may be interpreted as markup")
        buttons = ([navigation] if navigation is not None else []) + [pin_button, close]
        boxes = [rect(button, controls) for button in buttons]
        for button, box in zip(buttons, boxes):
            if box.left() < -1 or box.right() > controls.width() + 1:
                problems.append(f"{context}: {button.objectName()} overflows the toolbar")
            if box.width() + 1 < button.implicitWidth() or box.height() < 28:
                problems.append(f"{context}: {button.objectName()} has a squeezed label or target")
            if not button.property("focusable"):
                problems.append(f"{context}: {button.objectName()} cannot take keyboard focus")
        if any(a.intersects(b) for index, a in enumerate(boxes) for b in boxes[index + 1:]):
            problems.append(f"{context}: toolbar buttons overlap")
        if any(abs(button.width() - button.height()) > 1 for button in (pin_button, close)):
            problems.append(f"{context}: icon targets are not square")
        if abs(pin_button.width() - close.width()) > 1:
            problems.append(f"{context}: pin and close have unequal targets")

    try:
        for scale in (1, 1.5):
            style.setProperty("fontScale", scale)
            for width in (300, 340, 420):
                window.setWidth(width)
                panel.resize(width, panel.height())
                item.setProperty("view", "table")
                for index, name in enumerate(titles):
                    rename = QQmlExpression(item_context, item,
                                            "game = Object.assign({}, game, {title: %s})" % json.dumps(name))
                    rename.evaluate()
                    assert not rename.hasError(), rename.error().toString()
                    for pinned in (False, True):
                        set_pin(pinned)
                        wait(60)
                        context = f"{width}px at {scale}x, title {index}, pinned={pinned}"
                        verify(context, campaigns)
                        if title.property("size") != round(16 * scale):
                            problems.append(f"{context}: heading font shrank")
                        if index and title.property("lineCount") <= 1:
                            problems.append(f"{context}: long title did not wrap")
                        if width == 340 and index == 1:
                            suffix = "-pinned" if pinned else ""
                            panel.grabWindow().save(str(out / f"header-{scale}x{suffix}.png"))
                set_pin(False)
                for view, expected, navigation in (("home", "oma-solorpg", None), ("new", "New adventure", back)):
                    item.setProperty("view", view)
                    wait(60)
                    context = f"{width}px at {scale}x, {view}"
                    verify(context, navigation)
                    if title.property("text") != expected or campaigns.isVisible() or back.isVisible() != (view == "new"):
                        problems.append(f"{context}: navigation or title is wrong")

        # Keyboard activation uses the same signals as the real shell's focusable Button.
        style.setProperty("fontScale", saved[3])
        window.setWidth(saved[1])
        panel.resize(saved[2], panel.height())
        item.setProperty("game", game)
        item.setProperty("view", "table")
        set_pin(False)
        panel.requestActivate()
        wait(100)
        pin_button.forceActiveFocus()
        wait(60)
        QTest.keyClick(panel, Qt.Key.Key_Return)
        wait(60)
        if not pin.property("pinned"):
            problems.append("Enter did not activate the focused Pin button")
        QTest.keyClick(panel, Qt.Key.Key_Space)
        wait(60)
        if pin.property("pinned"):
            problems.append("Space did not unpin the focused Pin button")
        campaigns.forceActiveFocus()
        QTest.keyClick(panel, Qt.Key.Key_Return)
        wait(60)
        if item.property("view") != "home":
            problems.append("Campaigns did not return to Home")
        item.setProperty("view", "new")
        wait(60)
        back.forceActiveFocus()
        QTest.keyClick(panel, Qt.Key.Key_Return)
        wait(60)
        if item.property("view") != "home":
            problems.append("Back did not return to Home")
        close.forceActiveFocus()
        QTest.keyClick(panel, Qt.Key.Key_Return)
        wait(60)
        if item.property("opened"):
            problems.append("Close did not hide the Table")
        call(pin, "show")
        pin_button.forceActiveFocus()
        QTest.keyClick(panel, Qt.Key.Key_Escape)
        wait(60)
        if item.property("opened"):
            problems.append("Escape did not close the Table from a header button")
    finally:
        set_pin(False)
        style.setProperty("fontScale", saved[3])
        window.setWidth(saved[1])
        panel.resize(saved[2], panel.height())
        item.setProperty("game", game)
        item.setProperty("view", saved[0])
        call(pin, "show")
    print("Table header: 60 layout cases (3 widths, 2 font scales, long/plain-text titles, both pin states, Home/New) and keyboard controls.")
    return problems
