pragma Singleton
import QtQuick

// Stand-in for omarchy-shell's Style for offscreen checks.
QtObject {
  id: style
  // Enlarge text without giving a fixed-width panel more room.
  property real fontScale: 1
  readonly property real cornerRadius: 4
  readonly property real gapsOut: 10
  readonly property QtObject font: QtObject {
    readonly property string family: "DejaVu Sans Mono"
    readonly property real caption: Math.round(10 * style.fontScale)
    readonly property real bodySmall: Math.round(11 * style.fontScale)
    readonly property real body: Math.round(12 * style.fontScale)
    readonly property real subtitle: Math.round(13 * style.fontScale)
    readonly property real title: Math.round(14 * style.fontScale)
    readonly property real heading: Math.round(16 * style.fontScale)
    readonly property real display: Math.round(24 * style.fontScale)
  }
  readonly property QtObject spacing: QtObject {
    readonly property real controlPaddingX: 8
    readonly property real controlPaddingY: 4
  }
  function space(px) { return px }
}
