import QtQuick

// A layer surface has no workspace of its own. Keep its requested-open state separate
// from what is actually shown, so the shell's toggle can summon a hidden, pinned Table.
QtObject {
  id: pin
  property var hyprland: null
  property var screens: []
  property var screen: null
  property bool requested: false
  property int workspaceId: 0
  property string workspaceName: ""
  property string monitorName: ""

  readonly property bool pinned: workspaceId !== 0
  readonly property var current: workspaceOn(hyprland && screen ? hyprland.monitorFor(screen) : null)
  readonly property var workspace: pinned && hyprland
    ? hyprland.workspaces.values.find(w => w.id === workspaceId)
      || hyprland.workspaces.values.find(w => w.name === workspaceName) || null : null
  readonly property string knownName: workspace ? workspace.name : ""
  readonly property string knownMonitor: workspace && workspace.monitor ? workspace.monitor.name : ""
  readonly property var pinnedScreen: pinned
    ? screens.find(s => s.name === (knownMonitor || monitorName)) || null : null
  readonly property var pinnedCurrent: workspace ? workspaceOn(workspace.monitor) : null
  readonly property bool shown: requested && (!pinned || (pinnedScreen !== null && workspace !== null
    && pinnedCurrent !== null && pinnedCurrent.id === workspace.id))

  function workspaceOn(monitor) {
    if (!monitor || !hyprland) return null
    var special = monitor.lastIpcObject && monitor.lastIpcObject.specialWorkspace
    if (special && special.id !== 0)
      return hyprland.workspaces.values.find(w => w.id === special.id) || null
    return monitor.activeWorkspace
  }

  function togglePin() {
    if (pinned) {
      workspaceId = 0
      workspaceName = ""
      monitorName = ""
    } else if (current) {
      workspaceName = current.name
      monitorName = screen ? screen.name : ""
      workspaceId = current.id
    }
  }

  function luaString(text) {
    var escaped = text.replace(/\\/g, "\\\\").replace(/"/g, '\\"')
    return '"' + escaped.replace(/[\u0000-\u001f]/g, c => "\\" + ("00" + c.charCodeAt(0)).slice(-3)) + '"'
  }

  function show() {
    requested = true
    // Only an explicit summon changes workspace; ordinary workspace changes never do.
    if (!pinned || shown || !hyprland) return
    if (workspace) workspace.activate()
    // Hyprland forgets empty workspaces. Recreate one only when the player summons it.
    else if (hyprland.usingLua) hyprland.dispatch("hl.dsp.focus({ workspace = " + luaString(workspaceName) + " })")
    else if (!/[\u0000-\u001f]/.test(workspaceName)) {
      var target = workspaceName.startsWith("special:") ? "togglespecialworkspace " + workspaceName.slice(8)
        : "workspace " + (workspaceId > 0 ? workspaceId : "name:" + workspaceName)
      hyprland.dispatch(target)
    }
  }

  function hide() {
    requested = false
  }

  function remember() {
    if (!pinned || !workspace) return
    workspaceName = workspace.name
    if (workspace.monitor) monitorName = workspace.monitor.name
    workspaceId = workspace.id
  }

  // A rename or monitor move updates the remembered destination. Keep it when an empty
  // workspace disappears, and allow named workspaces to return with a different ID.
  onWorkspaceChanged: Qt.callLater(pin.remember)
  onKnownNameChanged: Qt.callLater(pin.remember)
  onKnownMonitorChanged: Qt.callLater(pin.remember)
}
