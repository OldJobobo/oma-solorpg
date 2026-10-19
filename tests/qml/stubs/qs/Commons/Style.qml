pragma Singleton
import QtQuick

// Stand-in for omarchy-shell's Style for offscreen checks.
QtObject {
  readonly property real cornerRadius: 4
  readonly property real gapsOut: 10
  readonly property QtObject font: QtObject {
    readonly property string family: "DejaVu Sans Mono"
    readonly property real caption: 10
    readonly property real bodySmall: 11
    readonly property real body: 12
    readonly property real subtitle: 13
    readonly property real title: 14
    readonly property real heading: 16
    readonly property real display: 24
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
