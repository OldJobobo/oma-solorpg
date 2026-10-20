import QtQuick

// Preserve the text bar's metrics, but draw solid runs and opted-in empty
// tracks once. Overlapping block glyphs leave seams, bumps and uneven stippling.
Item {
  id: blocks
  property string text: ""
  property real tracking: -1
  property int glyphRenderType: Text.CurveRendering
  property alias font: layout.font
  property alias color: glyphs.color
  // Upper resource meters opt in; Momentum keeps its shaded cells as text.
  property color emptyColor: "transparent"
  readonly property var runs: findRuns("█", false).concat(emptyColor.a > 0 ? findRuns("░", true) : [])

  function findRuns(glyph, empty) {
    var result = [], pattern = new RegExp(glyph + "+", "g"), match
    while ((match = pattern.exec(blocks.text)) !== null)
      result.push({ start: match.index, cells: match[0].length, empty: empty })
    return result
  }
  implicitWidth: layout.implicitWidth
  implicitHeight: layout.implicitHeight
  baselineOffset: layout.baselineOffset

  // The original glyphs only measure the bar; none of their edges are painted.
  Text {
    id: layout
    objectName: "meterCellLayout"
    visible: false
    textFormat: Text.PlainText
    renderType: blocks.glyphRenderType
    font.letterSpacing: blocks.tracking
    text: blocks.text
  }
  TextMetrics { id: cell; font: layout.font; text: "█" }

  Text {
    id: glyphs
    objectName: "meterCellGlyphs"
    textFormat: Text.PlainText
    renderType: blocks.glyphRenderType
    font: layout.font
    // Zero markers and cap dots stay text. Only opted-in empty tracks are flat.
    text: blocks.emptyColor.a > 0 ? blocks.text.replace(/[█░]/g, "\u00a0") : blocks.text.replace(/█/g, "\u00a0")
  }

  Repeater {
    model: blocks.runs
    delegate: Rectangle {
      required property var modelData
      objectName: modelData.empty ? "emptyBlockRun" : "solidBlockRun"
      x: modelData.start * cell.advanceWidth
      y: layout.baselineOffset + cell.tightBoundingRect.y
      width: modelData.cells * cell.advanceWidth
      height: cell.tightBoundingRect.height
      color: modelData.empty ? blocks.emptyColor : glyphs.color
      radius: 0
      antialiasing: false
    }
  }
}
