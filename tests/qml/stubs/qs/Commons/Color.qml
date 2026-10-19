pragma Singleton
import QtQuick

// Stand-in for omarchy-shell's Color (Tokyo Night values) for offscreen checks.
QtObject {
  property color foreground: "#c0caf5"
  property color background: "#1a1b26"
  property color accent: "#7aa2f7"
  property color urgent: "#f7768e"
  property color muted: "#9aa5ce"
  readonly property QtObject popups: QtObject {
    property color background: "#1a1b26"
    property color text: "#c0caf5"
    property color border: "#33467c"
  }
  readonly property QtObject tooltip: QtObject {
    property color background: "#16161e"
    property color text: "#c0caf5"
    property color border: "#33467c"
  }
}
