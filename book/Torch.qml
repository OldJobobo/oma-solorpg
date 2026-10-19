import QtQuick
import QtQuick.Effects
import QtQuick.Particles

// The light the hero carries: a flame that flickers, red at the tip and nearly white at
// the root, a glow around it and a few embers going up; beside it, how much is left, a bar
// that reddens as it burns down. The flame shrinks as the torch does. In a dark place with
// nothing burning, a warning instead.
Column {
  id: torch
  property var theme
  property bool gpu: true
  property var light: null       // {label, left, burns}
  property bool dark: false

  readonly property real share: light ? Math.max(0, light.left / Math.max(1, light.burns)) : 0
  // Frames of the flame, tallest while the torch is new. Each row is tip, body or root.
  readonly property var frames: share > 0.5
    ? [["    (    ", "   ) )   ", "  ( ( )  ", " ( ) ) ) ", "  \\ ( /  ", "   \\_/   "],
       ["     )   ", "    ( (  ", "   ) ) ) ", "  ( ( (  ", "  \\ ) /  ", "   \\_/   "],
       ["   (     ", "   ) )   ", "  ( ( )  ", "  ) ) )  ", "  \\ ( /  ", "   \\_/   "]]
    : share > 0.15
    ? [["         ", "    (    ", "   ) )   ", "  ( ( )  ", "   \\ /   ", "   \\_/   "],
       ["         ", "     )   ", "    ( (  ", "   ) ) ) ", "   \\ /   ", "   \\_/   "]]
    : [["         ", "         ", "         ", "    ,    ", "   (.)   ", "   \\_/   "],
       ["         ", "         ", "         ", "    .    ", "   (,)   ", "   \\_/   "]]
  readonly property var stick: ["    |    ", "    |    "]
  property int frame: 0
  readonly property var flame: frames[frame % frames.length]

  function rows(from, to) {
    return flame.map((row, i) => i >= from && i < to ? row : " ".repeat(row.length)).concat(stick.map(r => " ".repeat(r.length))).join("\n")
  }

  visible: !!light || dark
  spacing: 2

  Timer {
    interval: 180 + Math.random() * 160
    running: !!torch.light && torch.visible
    repeat: true
    onTriggered: { torch.frame = (torch.frame + 1) % torch.frames.length; interval = 140 + Math.random() * 220 }
  }

  Row {
    spacing: 12
    visible: !!torch.light

    Item {
      width: body.implicitWidth
      height: body.implicitHeight

      // The glow: a blurred copy of the flame, breathing with it.
      Text {
        visible: torch.gpu
        textFormat: Text.PlainText
        font: body.font
        lineHeight: 0.9
        color: torch.theme.gold
        text: torch.rows(0, 6)
        opacity: 0.55 + 0.25 * Math.sin(torch.frame * 1.7)
        layer.enabled: visible
        layer.effect: MultiEffect { blurEnabled: true; blur: 1.0; blurMax: 24; brightness: 0.3 }
      }
      Text {  // the tip
        textFormat: Text.PlainText
        font: body.font
        lineHeight: 0.9
        color: Qt.tint(torch.theme.gold, Qt.rgba(torch.theme.urgent.r, torch.theme.urgent.g, torch.theme.urgent.b, 0.65))
        text: torch.rows(0, 2)
      }
      Text {  // the body
        id: body
        textFormat: Text.PlainText
        font.family: torch.theme.mono
        font.pixelSize: torch.theme.small
        lineHeight: 0.9
        color: torch.share > 0.15 ? torch.theme.gold : torch.theme.urgent
        text: torch.rows(2, 4)
      }
      Text {  // the root, hottest
        textFormat: Text.PlainText
        font: body.font
        lineHeight: 0.9
        color: Qt.tint(torch.theme.gold, "#bfffffff")
        text: torch.rows(4, 6)
      }
      Text {  // the stick
        textFormat: Text.PlainText
        font: body.font
        lineHeight: 0.9
        color: torch.theme.dim
        text: torch.flame.map(r => " ".repeat(r.length)).concat(torch.stick).join("\n")
      }

      // Embers going up from the flame.
      ParticleSystem { id: sparks; running: torch.gpu && !!torch.light && torch.visible }
      ImageParticle {
        system: sparks
        source: "qrc:///particleresources/glowdot.png"
        color: torch.theme.gold
        colorVariation: 0.2
        alpha: 0.7
      }
      Emitter {
        system: sparks
        x: body.width / 2 - 4
        y: body.height * 0.25
        width: 8
        height: 4
        emitRate: 2.5 * Math.max(0.3, torch.share)
        lifeSpan: 1400
        lifeSpanVariation: 400
        size: 5
        sizeVariation: 3
        endSize: 1
        velocity: AngleDirection { angle: -90; angleVariation: 20; magnitude: 26; magnitudeVariation: 12 }
        acceleration: PointDirection { xVariation: 12 }
      }
    }

    Column {
      anchors.verticalCenter: parent.verticalCenter
      spacing: 5
      Text {
        textFormat: Text.PlainText
        font.family: torch.theme.mono
        font.pixelSize: torch.theme.small
        color: torch.theme.text
        text: torch.light ? torch.light.label : ""
      }
      // What is left, burning down: gold while there is plenty, redder toward the end.
      Rectangle {
        width: torch.theme.small * 7
        height: 3
        radius: 1.5
        color: torch.theme.faint
        Rectangle {
          width: parent.width * torch.share
          height: parent.height
          radius: parent.radius
          color: Qt.tint(torch.theme.gold, Qt.rgba(torch.theme.urgent.r, torch.theme.urgent.g, torch.theme.urgent.b, 1 - Math.min(1, torch.share * 2)))
          Behavior on width { NumberAnimation { duration: 800 } }
        }
      }
      Text {
        textFormat: Text.PlainText
        font.family: torch.theme.mono
        font.pixelSize: torch.theme.small
        color: torch.theme.dim
        text: torch.light ? torch.hours(torch.light.left) + " left" : ""
      }
    }
  }

  Text {
    visible: !torch.light && torch.dark
    textFormat: Text.PlainText
    font.family: torch.theme.mono
    font.pixelSize: torch.theme.small
    font.italic: true
    color: torch.theme.urgentText
    text: "It is dark here."
    SequentialAnimation on opacity {
      running: !torch.light && torch.dark && torch.visible
      loops: Animation.Infinite
      NumberAnimation { to: 0.5; duration: 1600; easing.type: Easing.InOutSine }
      NumberAnimation { to: 1.0; duration: 1600; easing.type: Easing.InOutSine }
    }
  }

  function hours(seconds) {
    var minutes = Math.floor(seconds / 60)
    return minutes >= 60 ? Math.floor(minutes / 60) + " h " + (minutes % 60) + " min" : minutes + " min"
  }
}
