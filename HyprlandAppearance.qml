import QtQuick
import Quickshell.Io
import qs.Commons

// One batched read on enable/open/configreloaded. No source parsing or polling.
Item {
  id: appearance
  required property string solo
  property bool requested: false
  property real uiScale: 1
  property var resolved: ({ available: false })
  readonly property bool active: requested && resolved.available === true
  readonly property string error: requested ? (resolved.error || "") : ""
  readonly property real rounding: active ? resolved.rounding / uiScale : Style.cornerRadius
  readonly property var borderSpec: {
    if (!active) return Border.none()
    var width = resolved.border_width / uiScale
    var spec = Border.flat(resolved.border.colors[0], width)
    spec.gradient = resolved.border
    return spec
  }
  readonly property bool shadowEnabled: active && resolved.shadow.enabled
  readonly property real shadowBlur: active ? resolved.shadow.range / uiScale : 0
  readonly property color shadowColor: active ? resolved.shadow.color : "transparent"
  readonly property vector2d shadowOffset: active
    ? Qt.vector2d(resolved.shadow.offset[0] / uiScale, resolved.shadow.offset[1] / uiScale) : Qt.vector2d(0, 0)
  property bool pending: false

  function gap(side) { return active ? resolved.gaps[side] / uiScale : Style.gapsOut }
  function refresh() {
    if (!requested) return
    if (reader.running) { pending = true; return }
    reader.running = true
  }
  onRequestedChanged: {
    if (requested) refresh()
    else resolved = { available: false }
  }

  Process {
    id: reader
    command: [appearance.solo, "ui", "--hyprland-appearance"]
    property string output: ""
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: reader.output = text }
    onExited: (exitCode, exitStatus) => {
      if (appearance.requested) {
        try { appearance.resolved = exitCode === 0 ? JSON.parse(reader.output) : ({ available: false, error: "Couldn't read Hyprland appearance." }) }
        catch (e) { appearance.resolved = { available: false, error: "Couldn't read Hyprland appearance." } }
      }
      if (appearance.pending) { appearance.pending = false; Qt.callLater(appearance.refresh) }
    }
  }
}
