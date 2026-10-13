import QtQuick
import QtQuick.Effects

// The hero's face in text. It is drawn in layers, one per kind of stroke (the line of the
// face, hair, headgear, gold, eyes, brows and mouth, a wound): each is the same text with
// every other character blanked, so they line up exactly and each takes its own colour.
// The face breathes, blinks now and then, and a bad wound throbs. A Dragon lights the eyes
// gold. When the face changes (a new condition, a wound, a Dragon) it flickers once.
Item {
  id: face
  property var theme
  property var portrait: null
  property real cell: theme.body

  readonly property string tint: portrait ? portrait.tint : "normal"
  readonly property string mood: portrait ? portrait.mood : "calm"
  readonly property var lines: portrait ? portrait.lines : []
  // A state.json from before the ink existed draws everything as the line of the face.
  readonly property var ink: portrait && portrait.ink && portrait.ink.length === lines.length ? portrait.ink : lines.map(l => l.replace(/[^ ]/g, "."))
  readonly property string art: lines.join("\n")
  readonly property bool alive: mood !== "dead" && mood !== "dying"
  property bool blinking: false

  readonly property color line: tint === "grave" ? theme.urgent
    : tint === "hurt" ? Qt.tint(theme.text, Qt.rgba(theme.urgent.r, theme.urgent.g, theme.urgent.b, 0.35)) : theme.text
  readonly property color hair: Qt.tint(line, Qt.rgba(theme.gold.r, theme.gold.g, theme.gold.b, 0.3))
  readonly property color steel: Qt.tint(theme.dim, Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.3))
  readonly property color eyes: mood === "triumph" ? theme.gold : mood === "angry" ? theme.urgent
    : mood === "dead" ? theme.dim : line

  implicitWidth: base.implicitWidth
  implicitHeight: base.implicitHeight

  // The lines with every character whose ink isn't one of `kinds` blanked out.
  function strokes(kinds, closed) {
    var out = []
    for (var i = 0; i < lines.length; i++) {
      var row = "", marks = ink[i] || ""
      for (var j = 0; j < lines[i].length; j++) {
        var kind = marks.charAt(j)
        row += kinds.indexOf(kind) === -1 ? " " : closed && kind === "e" ? "─" : lines[i].charAt(j)
      }
      out.push(row)
    }
    return out.join("\n")
  }

  // Everything together, invisible: it gives the face its size and the layers their font.
  Text {
    id: base
    textFormat: Text.PlainText
    font.family: face.theme.mono
    font.pixelSize: face.cell
    lineHeight: 1.0
    text: face.art
    opacity: 0
  }

  Item {
    id: drawn
    anchors.fill: parent

    Text { textFormat: Text.PlainText; font: base.font; lineHeight: 1.0; text: face.strokes(".bma"); color: face.line }
    Text { textFormat: Text.PlainText; font: base.font; lineHeight: 1.0; text: face.strokes("h"); color: face.hair; opacity: 0.75 }
    Text { textFormat: Text.PlainText; font: base.font; lineHeight: 1.0; text: face.strokes("g"); color: face.steel }
    Text { textFormat: Text.PlainText; font: base.font; lineHeight: 1.0; text: face.strokes("o"); color: face.theme.gold }
    Text {
      id: wound
      textFormat: Text.PlainText
      font: base.font
      lineHeight: 1.0
      text: face.strokes("w")
      color: face.theme.urgent
      SequentialAnimation on opacity {
        running: !!face.portrait && face.portrait.wounds >= 2 && face.alive && face.visible
        loops: Animation.Infinite
        onRunningChanged: if (!running) wound.opacity = 1
        NumberAnimation { to: 0.45; duration: 900; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
      }
    }
    // A Dragon: the eyes catch the light. The glow is a blurred copy behind them, so a
    // machine that can't draw effects still shows the eyes.
    Text {
      visible: face.mood === "triumph"
      textFormat: Text.PlainText
      font: base.font
      lineHeight: 1.0
      text: face.strokes("e")
      color: face.theme.gold
      layer.enabled: visible
      layer.effect: MultiEffect {
        blurEnabled: true
        blur: 0.8
        blurMax: 16
        brightness: 0.4
      }
    }
    Text {
      textFormat: Text.PlainText
      font: base.font
      lineHeight: 1.0
      text: face.strokes("e", face.blinking)
      color: face.eyes
    }
  }

  // Now and then the eyes close for a moment, as long as they are open.
  Timer {
    interval: 3200 + Math.random() * 4000
    repeat: true
    running: face.alive && face.mood !== "exhausted" && face.visible
    onTriggered: {
      face.blinking = true
      unblink.restart()
      interval = 2600 + Math.random() * 5200
    }
  }
  Timer { id: unblink; interval: 130; onTriggered: face.blinking = false }

  onArtChanged: if (art !== "" && visible) flicker.restart()

  SequentialAnimation on opacity {
    running: !!face.portrait && face.portrait.mood !== "dead" && face.visible
    loops: Animation.Infinite
    NumberAnimation { to: 0.84; duration: 2600; easing.type: Easing.InOutSine }
    NumberAnimation { to: 1.0; duration: 2600; easing.type: Easing.InOutSine }
  }

  SequentialAnimation {
    id: flicker
    NumberAnimation { target: face; property: "scale"; to: 1.04; duration: 90 }
    NumberAnimation { target: face; property: "scale"; to: 0.99; duration: 110 }
    NumberAnimation { target: face; property: "scale"; to: 1.0; duration: 160 }
  }
}
