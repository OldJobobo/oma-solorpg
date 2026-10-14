import QtQuick
import "../../book"
import "../../book/Common.js" as Common

// Renders the Book with a theme like Omarchy's default (Tokyo Night) for screenshots.
Item {
  id: harness
  width: 1280
  height: 860
  property var game: null
  property var turn: ({ status: "idle" })

  QtObject {
    id: theme
    property color text: "#c0caf5"
    property color dim: Common.fade(text, surface, 4.6, 0.5)  // as the plugin derives them (Panel.qml)
    property color faint: Common.fade(text, surface, 3, 0.65)
    property color background: "#1a1b26"
    property color surface: "#20212e"
    property color accent: "#7aa2f7"
    property color urgent: "#f7768e"
    property color gold: "#e0af68"
    property string mono: "DejaVu Sans Mono"
    property string serif: "DejaVu Serif"
    property real small: 12
    property real body: 14
    property real prose: 16
    property real title: 17
    property real heading: 20
    property real display: 28
    property real radius: 4
  }

  // What is on the page, newest first, as "seq:kind".
  function page() {
    var model = view.resources.filter(r => r && r.count !== undefined && typeof r.get === "function")[0]
    var out = []
    for (var i = 0; model && i < model.count; i++) {
      var beat = JSON.parse(model.get(i).json)
      out.push(beat.seq + ":" + beat.kind)
    }
    return out
  }

  BookView {
    id: view
    objectName: "book"
    anchors.fill: parent
    theme: theme
    game: harness.game
    turn: harness.turn
  }
}
