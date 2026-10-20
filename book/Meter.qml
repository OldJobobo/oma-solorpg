import QtQuick

// A track as a line of text: HP  ██████████░░░░  9/14.
// Flat fill and dim empty track, without changing labels or numbers.
Row {
  id: meter
  objectName: "resourceMeter"
  property var theme
  property string label: ""
  property int value: 0
  property int maximum: 1
  property int cells: 14

  readonly property int filled: Math.max(0, Math.min(cells, Math.round(cells * value / Math.max(1, maximum))))
  readonly property bool low: value * 4 <= maximum
  spacing: wordSpace.advanceWidth

  component Ink: Text {
    font.family: meter.theme.mono
    font.pixelSize: meter.theme.small
    color: meter.theme.text
  }

  TextMetrics { id: wordSpace; font: name.font; text: "\u00a0" }

  Ink {
    id: name
    objectName: "resourceMeterLabel"
    anchors.baseline: blocks.baseline
    textFormat: Text.StyledText
    text: "<span style=\"color:" + meter.theme.dim + "\">" + meter.label.toUpperCase() + "</span>"
  }

  SolidBlocks {
    id: blocks
    objectName: "resourceMeterBlocks"
    font.family: meter.theme.mono
    font.pixelSize: meter.theme.small
    color: meter.theme.text
    emptyColor: meter.theme.faint
    text: "█".repeat(meter.filled) + "░".repeat(meter.cells - meter.filled)
  }

  Ink {
    objectName: "resourceMeterValue"
    anchors.baseline: blocks.baseline
    textFormat: Text.PlainText
    text: meter.value + "/" + meter.maximum
  }
}
