import QtQuick

// Momentum runs below zero. Keep its zero marker and dotted ceiling as text,
// but paint each solid run once so it cannot have internal glyph seams.
Row {
  id: meter
  objectName: "momentumMeter"
  property var theme
  property var track: ({ value: 0, max: 10 })
  property var spec: ({ min: -6, max: 10 })
  spacing: wordSpace.advanceWidth

  function bar() {
    var out = ""
    for (var n = spec.min; n <= -1; n++)
      out += track.value < 0 && n >= track.value ? "█" : "░"
    out += "│"
    for (n = 1; n <= spec.max; n++)
      out += n > track.max ? "·" : track.value >= n ? "█" : "░"
    return out
  }

  component Ink: Text {
    font.family: meter.theme.mono
    font.pixelSize: meter.theme.small
    color: meter.theme.text
  }

  TextMetrics { id: wordSpace; font: name.font; text: "\u00a0" }

  Ink {
    id: name
    objectName: "momentumMeterLabel"
    anchors.baseline: blocks.baseline
    textFormat: Text.StyledText
    text: "<span style=\"color:" + meter.theme.dim + "\">MOMENTUM</span>"
  }

  SolidBlocks {
    id: blocks
    objectName: "momentumMeterBlocks"
    // Flat fills do not need squeezed glyphs; preserve the shaded-cell pattern.
    tracking: 0
    font.family: meter.theme.mono
    font.pixelSize: meter.theme.small
    color: meter.theme.text
    text: meter.bar()
  }

  Ink {
    objectName: "momentumMeterValue"
    anchors.baseline: blocks.baseline
    textFormat: Text.PlainText
    text: (meter.track.value > 0 ? "+" : "") + meter.track.value
  }
}
