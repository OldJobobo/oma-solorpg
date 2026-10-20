"""Layer-shell appearance follows resolved Hyprland options, not source files."""

import json
from PySide6.QtCore import QMetaObject
from scaling_panel_check import items as visual_items


def check(item, panel, out, work, wait, process_type):
    """Both faces follow resolved values; UI zoom does not enlarge desktop gaps."""
    from unittest.mock import patch
    Process = process_type
    HEIGHT = panel.height()
    problems = []
    def check(condition, message):
        if not condition:
            problems.append("Hyprland appearance: " + message)
    def find(name):
        return next(obj for obj in visual_items(item) if obj.objectName() == name)
    original_run = Process._run
    resolved = {"available": True, "gaps": {"top": 10, "right": 12, "bottom": 14, "left": 16},
                "rounding": 8, "border_width": 3,
                "border": {"colors": ["#ff123456", "#ffabcdef"], "angle": 45, "enabled": True},
                "shadow": {"enabled": True, "range": 12, "color": "#99000000", "offset": [-2, 3]}}
    reads = []
    def read_options(process):
        if "--hyprland-appearance" not in list(process.command):
            return original_run(process)
        reads.append(1)
        process.stdout.text = json.dumps(resolved)
        process.stdout.streamFinished.emit()
        process._running = False
        process.runningChanged.emit()
        process.exited.emit(0, 0)
    appearance = find("hyprAppearance")
    toggle = find("settingsHonorHyprland")
    flip = find("tableFlip")
    old_scale = item.property("tableScale")
    old_reduced = item.property("reducedMotion")
    old_width = find("tableWindow").width()
    item.setProperty("reducedMotion", True)
    item.setProperty("settingsOpen", True)
    with patch.object(Process, "_run", read_options):
        QMetaObject.invokeMethod(toggle, "toggled")
        wait(300)
        check(item.property("honorHyprland") and toggle.property("checked"), "toggle did not save")
        check(json.loads((work / "state/solo/ui.json").read_text())["honor_hyprland"], "preference missing on disk")
        for scale in (1, 2):
            item.setUiScale("table", scale)
            wait(300)
            find("tableWindow").setProperty("width", 360 * scale)
            panel.resize(360 * scale, HEIGHT)
            wait(50)
            check(abs(flip.x() * scale - 16) < 0.1 and abs(flip.y() * scale - 10) < 0.1, "gaps changed with Table zoom")
            for name in ("tableSurface", "settingsSurface"):
                surface = find(name)
                check(abs(surface.property("radius") * scale - 8) < 0.1, name + " rounding differs")
                spec = surface.property("borderSpec").toVariant()
                check(abs(spec["widths"]["top"] * scale - 3) < 0.1, name + " border width differs")
                check(spec["gradient"]["colors"] == resolved["border"]["colors"], "border gradient lost")
        check(appearance.property("shadowEnabled"), "shadow not enabled")
        panel.grabWindow().save(str(out / "settings-honor-hyprland.png"))
        # Simulate compositor reload and loss, through the same refresh entrypoint.
        resolved["rounding"] = 0
        resolved["shadow"]["enabled"] = False
        appearance.refresh()
        wait(100)
        check(find("settingsSurface").property("radius") == 0, "refresh kept old rounding")
        check(not appearance.property("shadowEnabled"), "disabled shadow remained")
        resolved = {"available": False, "error": "Hyprland unavailable"}
        appearance.refresh()
        wait(100)
        check(not appearance.property("active") and appearance.property("error"), "unavailable compositor did not fall back")
        QMetaObject.invokeMethod(toggle, "toggled")
        wait(300)
        check(not item.property("honorHyprland") and not appearance.property("active"), "off did not restore shell style")
        count = len(reads)
        appearance.refresh()
        wait(50)
        check(len(reads) == count, "off still queries Hyprland")
    item.setUiScale("table", old_scale)
    wait(300)
    item.setProperty("settingsOpen", False)
    item.setProperty("reducedMotion", old_reduced)
    find("tableWindow").setProperty("width", old_width)
    panel.resize(360, HEIGHT)
    return problems
