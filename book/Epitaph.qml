import QtQuick
import QtQuick.Particles

// When the hero dies, the Book closes on a gravestone: their face cut into the stone,
// their name, where they fell and to whom, and the last words the player gave them. The
// page behind has gone grey, and ash drifts down. The Home screen keeps it in the Hall of
// the Fallen. Click, and the story can be read again.
Item {
  id: epitaph
  property var theme
  property bool gpu: true
  property var game: null
  signal dismissed()

  readonly property var pc: game ? game.pc : null
  readonly property var fallen: game && game.fallen ? game.fallen : ({})
  readonly property var face: game && game.portrait ? game.portrait.lines : []
  readonly property string name: pc ? pc.name.toUpperCase().split("").join(" ") : ""
  readonly property string info: pc ? Object.keys(pc.info).map(k => pc.info[k]).join(" · ") : ""

  // The stone as text, in layers of the same shape: the stone itself, what is carved into
  // it, and the name, so each takes its own colour and they line up exactly.
  readonly property int inner: Math.max(28, face.reduce((w, l) => Math.max(w, l.length), 0) + 8, name.length + 6, info.length + 6)
  readonly property var carved: ["", "R . I . P", ""].concat(face).concat(["", "", "", ""])
  readonly property var stone: build()

  function centred(text, width) {
    var left = Math.floor((width - text.length) / 2)
    return " ".repeat(Math.max(0, left)) + text + " ".repeat(Math.max(0, width - text.length - left))
  }

  function build() {
    var w = inner, rows = { shape: [], carving: [], name: [] }
    function add(shape, carving, named) {
      rows.shape.push(shape)
      rows.carving.push(carving || " ".repeat(shape.length))
      rows.name.push(named || " ".repeat(shape.length))
    }
    var blank = " ".repeat(w)
    add("    .-" + "~".repeat(w - 6) + "-.    ")
    add("  .'" + " ".repeat(w - 2) + "'.  ")
    add(" /" + " ".repeat(w + 2) + "\\ ")
    for (var i = 0; i < carved.length; i++) {
      var line = centred(carved[i], w)
      var row = i === carved.length - 3 ? centred(name, w) : i === carved.length - 2 ? centred(info, w) : ""
      add(" |" + " ".repeat(w + 2) + "| ", "  " + " " + line + " " + "  ",
          row ? "  " + " " + row + " " + "  " : "")
    }
    add(" |" + "_".repeat(w + 2) + "| ")
    var grass = ""
    var tufts = ["\\|/", ",,", "'", "\\|/", ",", ",,,", "'"]
    while (grass.length < w + 6) grass += tufts[grass.length % tufts.length] + " "
    add(grass.slice(0, w + 6))
    return rows
  }

  Rectangle {
    anchors.fill: parent
    color: epitaph.theme.background
    opacity: epitaph.gpu ? 0.7 : 0.94
  }

  MouseArea { anchors.fill: parent; onClicked: epitaph.dismissed() }

  // Ash, drifting down over it all.
  ParticleSystem { id: ash; running: epitaph.visible && epitaph.gpu }
  ImageParticle {
    system: ash
    source: "qrc:///particleresources/fuzzydot.png"
    color: Qt.tint(epitaph.theme.background, Qt.rgba(epitaph.theme.text.r, epitaph.theme.text.g, epitaph.theme.text.b, 0.45))
    colorVariation: 0.05
    alpha: 0.18
  }
  Emitter {
    system: ash
    anchors { left: parent.left; right: parent.right; top: parent.top }
    height: 1
    emitRate: 7
    lifeSpan: 9000
    size: 4
    sizeVariation: 3
    velocity: PointDirection { y: 38; yVariation: 14; xVariation: 12 }
    acceleration: PointDirection { xVariation: 6 }
  }

  Column {
    id: column
    anchors.centerIn: parent
    anchors.verticalCenterOffset: rise
    width: Math.min(parent.width * 0.85, epitaph.theme.body * 48)
    spacing: epitaph.theme.body * 0.6
    property real rise: 0

    Item {
      anchors.horizontalCenter: parent.horizontalCenter
      width: shape.implicitWidth
      height: shape.implicitHeight

      FontMetrics { id: cell; font: shape.font }
      // The stone has body: a slab behind the lines, rounded at the top like them.
      Rectangle {
        x: cell.averageCharacterWidth * 1.5
        y: shape.height / epitaph.stone.shape.length * 0.6
        width: shape.width - cell.averageCharacterWidth * 3
        height: shape.height - shape.height / epitaph.stone.shape.length * 1.6
        radius: cell.averageCharacterWidth * 5
        color: Qt.tint(epitaph.theme.surface, Qt.rgba(epitaph.theme.text.r, epitaph.theme.text.g, epitaph.theme.text.b, 0.07))
        border.width: 1
        border.color: Qt.rgba(epitaph.theme.text.r, epitaph.theme.text.g, epitaph.theme.text.b, 0.06)
      }

      Text {
        id: shape
        textFormat: Text.PlainText
        font.family: epitaph.theme.mono
        font.pixelSize: epitaph.theme.small
        lineHeight: 1.0
        color: epitaph.theme.dim
        text: epitaph.stone.shape.join("\n")
      }
      Text {
        textFormat: Text.PlainText
        font: shape.font
        lineHeight: 1.0
        color: Qt.tint(epitaph.theme.dim, Qt.rgba(epitaph.theme.text.r, epitaph.theme.text.g, epitaph.theme.text.b, 0.25))
        text: epitaph.stone.carving.join("\n")
      }
      Text {
        id: named
        textFormat: Text.PlainText
        font: shape.font
        lineHeight: 1.0
        color: epitaph.theme.text
        text: epitaph.stone.name.join("\n")
        opacity: 0
      }
    }

    Text {
      id: where
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.Wrap
      textFormat: Text.PlainText
      font.family: epitaph.theme.serif
      font.pixelSize: epitaph.theme.prose
      color: epitaph.theme.dim
      opacity: 0
      text: epitaph.pc ? "Fell in " + (epitaph.fallen.scene || "the dark") + (epitaph.fallen.by ? ", to " + epitaph.fallen.by : "") + "." : ""
    }

    Text {
      id: words
      visible: !!epitaph.fallen.epitaph
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.Wrap
      textFormat: Text.PlainText
      font.family: epitaph.theme.serif
      font.italic: true
      font.pixelSize: epitaph.theme.prose * 1.15
      color: epitaph.theme.text
      opacity: 0
      text: "“" + (epitaph.fallen.epitaph || "") + "”"
    }

    Text {
      id: hint
      anchors.horizontalCenter: parent.horizontalCenter
      textFormat: Text.PlainText
      font.family: epitaph.theme.mono
      font.pixelSize: epitaph.theme.small
      color: epitaph.theme.faint
      opacity: 0
      text: "click to read the story again"
    }
  }

  // The stone rises out of the dark, then the name comes, then the words.
  SequentialAnimation {
    id: arrive
    ParallelAnimation {
      NumberAnimation { target: column; property: "rise"; from: epitaph.theme.body * 3; to: 0; duration: 1600; easing.type: Easing.OutCubic }
      NumberAnimation { target: column; property: "opacity"; from: 0; to: 1; duration: 1400 }
    }
    NumberAnimation { target: named; property: "opacity"; to: 1; duration: 900 }
    NumberAnimation { target: where; property: "opacity"; to: 1; duration: 700 }
    NumberAnimation { target: words; property: "opacity"; to: 1; duration: 1200 }
    PauseAnimation { duration: 800 }
    NumberAnimation { target: hint; property: "opacity"; to: 1; duration: 800 }
  }
  onVisibleChanged: visible ? arrive.restart() : arrive.complete()
  Component.onCompleted: if (visible) arrive.restart()
}
