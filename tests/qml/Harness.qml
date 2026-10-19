import QtQuick
import "../../book"
import "../.." as Solo

// Renders the Book with a theme like Omarchy's default (Tokyo Night) for screenshots.
Item {
  id: harness
  width: 1280
  height: 860
  property var game: null
  property var turn: ({ status: "idle" })

  Solo.Theme {
    id: theme
    mono: "DejaVu Sans Mono"
    serif: "DejaVu Serif"
    small: 12
    body: 14
    prose: 16
    title: 17
    heading: 20
    display: 28
  }

  BookView {
    id: view
    objectName: "book"
    anchors.fill: parent
    theme: theme
    game: harness.game
    turn: harness.turn
    active: false
  }
}
