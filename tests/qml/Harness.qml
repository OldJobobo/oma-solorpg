import QtQuick
import "../../book"
import "../.." as Solo

// Renders the Book with a theme like Omarchy's default (Tokyo Night) for screenshots.
Item {
  id: harness
  width: 1280
  height: 860
  property var game: null
  property real bookScale: 1
  property var turn: ({ status: "idle" })

  Solo.Theme {
    id: theme
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
