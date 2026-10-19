import QtQuick
import "../../book"

// Renders the Book with a theme like Omarchy's default (Tokyo Night) for screenshots.
Item {
  id: harness
  width: 1280
  height: 860
  property var game: null
  property real bookScale: 1
  property var turn: ({ status: "idle" })

  QtObject {
    id: theme
    objectName: "theme"
    property color text: "#c0caf5"
    property color dim: Qt.darker(text, 1.6)
    property color faint: Qt.rgba(text.r, text.g, text.b, 0.22)
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

  ScaledViewport {
    id: viewport
    objectName: "bookViewport"
    anchors.fill: parent
    factor: harness.bookScale
  }
  BookView {
    id: view
    objectName: "book"
    parent: viewport.canvas
    anchors.fill: parent
    theme: theme
    bookScale: harness.bookScale
    onScaleRequested: value => harness.bookScale = value
    game: harness.game
    turn: harness.turn
    active: false
  }
}
