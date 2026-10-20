import QtQuick
import "../../book"

Rectangle {
  id: harness
  width: 900
  height: 640
  color: "#161616"
  property real zoom: 1
  property real fontSize: 11
  property string fontFamily: "monospace"
  property int resource: 5
  property int progressTicks: 18
  property var momentum: ({ value: 4, max: 10 })

  QtObject {
    id: theme
    property string mono: harness.fontFamily
    property real small: harness.fontSize
    property real body: harness.fontSize
    property color text: "#e0dacd"
    property color dim: "#a7a192"
    property color faint: "#38e0dacd"
    property color accent: "#98a67a"
    property color accentText: accent
    property color urgent: "#e3695e"
  }

  ScaledViewport {
    id: viewport
    anchors.fill: parent
    factor: harness.zoom
  }

  Column {
    parent: viewport.canvas
    x: 20; y: 20
    spacing: 14
    Meter { theme: theme; label: "health"; value: harness.resource; maximum: 5 }
    Momentum { theme: theme; track: harness.momentum; spec: ({ min: -6, max: 10 }) }
    Text {
      textFormat: Text.PlainText
      font.family: theme.mono
      font.pixelSize: theme.small
      color: theme.text
      text: "Normal text and ASCII stay unchanged: /\\_()  0123456789"
    }
    Progress {
      theme: theme
      width: 380
      spec: ({ boxes: 10, ticks: 4 })
      progress: ({
        vow: { name: "Silence the bell", kind: "vow", rank: "dangerous", ticks: harness.progressTicks, ended: false },
        road: { name: "The barrow road", kind: "journey", rank: "troublesome", ticks: harness.progressTicks, ended: false }
      })
    }
  }
}
