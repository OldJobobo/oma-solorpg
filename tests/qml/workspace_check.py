"""Exercise the real workspace-pin controller offscreen, with no compositor actions.

    QT_QPA_PLATFORM=offscreen python3 tests/qml/workspace_check.py
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QMetaObject, QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QJSValue, QQmlComponent, QQmlEngine  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def snapshot(engine, active=3, moved=False, deleted=False, special=0, target_id=3, target_name="3", using_lua=True):
    """New objects on each update: the pin must follow workspace IDs, not old objects."""
    data = {"active": active, "moved": moved, "deleted": deleted, "special": special,
            "targetId": target_id, "targetName": target_name, "usingLua": using_lua}
    backend = engine.evaluate("""(() => {
        const data = %s;
        const monitors = [{name: 'DP-1'}, {name: 'DP-2'}];
        const calls = [];
        const workspaces = [3, 4, 12, -99].filter(id => !(data.deleted && id === 3)).map(id => ({
            id: id === 3 ? data.targetId : id,
            name: id === 3 ? data.targetName : id === -99 ? 'special:game' : String(id),
            monitor: monitors[(id === 12 || (id === 3 && data.moved)) ? 1 : 0],
            activate: function() { calls.push(this.id); }
        }));
        monitors[0].activeWorkspace = workspaces.find(w => w.id === (data.active === 3 ? data.targetId : data.active)) || null;
        monitors[0].lastIpcObject = {specialWorkspace: {id: data.special}};
        monitors[1].activeWorkspace = workspaces.find(w => w.id === (data.moved ? data.targetId : 12)) || null;
        monitors[1].lastIpcObject = {specialWorkspace: {id: 0}};
        return {calls, usingLua: data.usingLua, dispatch: function(request) { calls.push(request); },
                workspaces: {values: workspaces}, focusedMonitor: monitors[1],
                monitorFor: function(screen) { return monitors.find(m => m.name === screen.name) || null; }};
    })()""" % json.dumps(data))
    assert isinstance(backend, QJSValue)
    assert not backend.isError(), backend.toString()
    return backend


def main():
    app = QGuiApplication(sys.argv)
    engine = QQmlEngine()
    errors = []
    engine.warnings.connect(lambda warnings: errors.extend(w.toString() for w in warnings))
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(REPO / "WorkspacePin.qml")))
    pin = component.create()
    assert pin is not None, "\n".join(e.toString() for e in component.errors())
    current_backend = None

    def state(active=3, moved=False, connected=True, deleted=False, special=0, **options):
        nonlocal current_backend
        backend = snapshot(engine, active=active, moved=moved, deleted=deleted, special=special, **options)
        current_backend = backend
        pin.setProperty("screens", engine.evaluate("[{name:'DP-1'}, {name:'DP-2'}]" if connected else "[{name:'DP-1'}]"))
        pin.setProperty("screen", engine.evaluate("({name:'DP-1'})"))
        pin.setProperty("hyprland", backend)
        app.processEvents()

    def call(name):
        assert QMetaObject.invokeMethod(pin, name)
        app.processEvents()

    def check(condition, message):
        if not condition:
            errors.append(message)

    def shown():
        return pin.property("shown")

    def activations():
        assert current_backend is not None
        return current_backend.property("calls").toVariant()

    state()
    call("show")
    check(shown() and not pin.property("pinned"), "the unpinned Table did not open")
    state(active=4)
    check(shown(), "unpinned behavior changed on another workspace")
    state()
    call("togglePin")
    check(pin.property("workspaceId") == 3 and shown(), "pin used the focused monitor instead of the sidebar's monitor")
    state(active=4)
    check(not shown() and pin.property("requested"), "leaving the pinned workspace closed it instead of hiding it")
    state()
    check(shown(), "returning to the workspace did not restore the Table")
    check(activations() == [], "a passive workspace change activated a workspace")
    call("hide")
    check(not shown() and pin.property("pinned"), "closing the Table lost the pin")
    state(active=4)
    call("show")
    check(not shown() and activations() == [3], "summoning elsewhere did not activate the pinned workspace")
    state()
    check(shown(), "the summoned Table did not return after activation")
    state(active=4, moved=True)
    check(shown() and pin.property("pinnedScreen").property("name").toString() == "DP-2", "the pin did not follow its workspace to another monitor")
    state(active=4, moved=True, connected=False)
    check(not shown() and pin.property("pinned"), "a disconnected monitor lost its pin or showed the Table elsewhere")
    call("show")
    check(activations() == [3], "an explicit summon could not recover a pin after monitor disconnection")
    state(active=4, moved=True)
    check(shown(), "reconnecting the workspace's monitor did not restore the Table")
    state(special=-99)
    check(not shown(), "a regular-workspace pin leaked into a special workspace")
    call("togglePin")
    call("togglePin")
    check(pin.property("workspaceId") == -99 and shown(), "the visible special workspace could not be pinned")
    state()
    check(not shown(), "a special-workspace pin leaked into the regular workspace")
    call("togglePin")
    check(shown() and not pin.property("pinned"), "unpinning did not restore global behavior")
    call("togglePin")
    state(active=4, deleted=True)
    check(not shown() and pin.property("pinned") and pin.property("requested"), "an empty workspace lost its pin or popped the Table up elsewhere")
    call("show")
    check(activations() == ['hl.dsp.focus({ workspace = "3" })'], "an empty workspace could not be recreated on an explicit summon")
    state()
    check(shown(), "returning to a recreated workspace did not restore the Table")
    call("togglePin")
    state(target_id=-7, target_name="Game")
    call("togglePin")
    state(active=4, deleted=True, target_id=-7, target_name="Game")
    call("show")
    check(activations() == ['hl.dsp.focus({ workspace = "Game" })'], "an empty named workspace could not be recreated")
    state(target_id=-8, target_name="Game")
    check(shown() and pin.property("workspaceId") == -8, "a named workspace did not return with its new ID")
    name = 'Game"\\\n});error("must remain a name");--'
    state(target_id=-8, target_name=name)
    state(active=4, deleted=True, target_id=-8, target_name=name)
    call("show")
    request = activations()[0]
    check("\n" not in request and "\\010" in request, "a workspace name was not escaped as a Lua string")
    lua = shutil.which("lua")
    if lua:
        result = subprocess.run([lua, "-e", 'hl={dsp={focus=function(p) io.write(p.workspace) end}};' + request],
                                capture_output=True, text=True, timeout=5)
        check(result.returncode == 0 and result.stdout == name, "the escaped workspace name did not round-trip through Lua")
    call("togglePin")
    state(using_lua=False)
    call("togglePin")
    state(active=4, deleted=True, using_lua=False)
    call("show")
    check(activations() == ["workspace 3"], "legacy Hyprland could not recreate an empty workspace")
    call("togglePin")
    pin.setProperty("hyprland", None)
    call("show")
    call("togglePin")
    check(shown() and not pin.property("pinned"), "unavailable Hyprland changed the unpinned behavior")
    if errors:
        print("Workspace pin errors:\n  " + "\n  ".join(errors))
        return 1
    print("Workspace pin checks passed: opt-in, hide/return, summon, close, multiple monitors, special/empty/named workspaces, safe recreation and disconnect.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
