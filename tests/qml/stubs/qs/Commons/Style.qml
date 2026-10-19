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
    readonly property real inputPaddingY: 7
    readonly property real controlGap: 8
  }
  property color normalInk: "#c0caf5"
  property color hoverInk: "#e0af68"
  property color focusInk: "#e0af68"
  property color selectedInk: "#e0af68"
  property color pressedInk: "#bb9af7"
  property color selectionTint: "#667aa2f7"
  function normalStateColor() { return normalInk }
  function hoverStateColor() { return hoverInk }
  function focusStateColor() { return focusInk }
  function selectedStateColor() { return selectedInk }
  function pressedStateColor() { return pressedInk }
  function normalFillFor() { return Qt.rgba(normalInk.r, normalInk.g, normalInk.b, 0.04) }
  function hoverFillFor() { return Qt.rgba(hoverInk.r, hoverInk.g, hoverInk.b, 0.08) }
  function focusFillFor() { return Qt.rgba(focusInk.r, focusInk.g, focusInk.b, 0.10) }
  function selectedFillFor() { return Qt.rgba(selectedInk.r, selectedInk.g, selectedInk.b, 0.16) }
  function pressedFillFor() { return Qt.rgba(pressedInk.r, pressedInk.g, pressedInk.b, 0.22) }
  function selectionFillFor() { return selectionTint }
  function space(px) { return px }
}
