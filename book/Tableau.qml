import QtQuick

// A fight as a scene redrawn after every exchange, like a woodcut in a gamebook: the hero
// on one side, the foes in initiative order on the other, the last blow drawn between
// them. When a blow lands the attacker lunges, the one it hits reels and flashes, and the
// damage rises off them; a miss is a sidestep. Nobody moves otherwise; there is no map.
Rectangle {
  id: tableau
  property var theme
  property var fight: null        // state.combat
  property var figures: ({ hero: [], foes: {} })
  property var hero: null         // state.pc
  // The last exchange already drawn, so a reload of state.json never plays it again.
  property int shown: -1

  readonly property var last: fight && fight.last ? fight.last : null
  readonly property bool heroStruck: last !== null && last.from === "pc"
  readonly property var foeIds: fight ? Object.keys(fight.foes) : []

  implicitHeight: content.implicitHeight + theme.body * 2
  radius: theme.radius
  color: theme.surface
  border.width: 1
  border.color: theme.faint

  onLastChanged: {
    if (!last || last.seq === undefined || last.seq === shown) return
    var first = shown < 0
    shown = last.seq
    if (first) return
    strike.restart()
    var attacker = last.from === "pc" ? heroFighter : foeFighter(last.from)
    var target = last.to === "pc" ? heroFighter : foeFighter(last.to)
    if (attacker) attacker.lunge()
    if (target) target.struck(last.hit, last.dealt || 0)
  }

  function foeFighter(id) {
    var index = foeIds.indexOf(id)
    return index < 0 ? null : foes.itemAt(index)
  }

  // One fighter: the figure, the name and a bar of HP. `facing` is 1 (looks right, the
  // hero) or -1 (looks left, a foe), which is where a lunge goes.
  component Fighter: Item {
    id: fighter
    property var theme
    property var art: []
    property string name: ""
    property int hp: 0
    property int maximum: 1
    property bool down: false
    property bool marked: false
    property int facing: 1
    property color ink: theme.text

    implicitWidth: body.implicitWidth
    implicitHeight: body.implicitHeight
    opacity: down ? 0.55 : 1
    Behavior on opacity { NumberAnimation { duration: 600 } }

    function lunge() { lunging.restart() }
    function struck(hit, dealt) {
      if (hit) {
        pop.text = dealt > 0 ? "−" + dealt : "no harm"
        pop.color = dealt > 0 ? theme.urgent : theme.dim
        flash.restart()
        reel.restart()
      } else {
        pop.text = "miss"
        pop.color = theme.dim
        sidestep.restart()
      }
      rise.restart()
    }

    Column {
      id: body
      spacing: 4
      Text {
        id: figure
        textFormat: Text.PlainText
        font.family: fighter.theme.mono
        font.pixelSize: fighter.theme.body
        lineHeight: 1.0
        color: fighter.ink
        text: fighter.art.join("\n")
        transformOrigin: Item.Bottom
        // The fallen tip over.
        rotation: fighter.down ? fighter.facing * -8 : 0
        Behavior on rotation { NumberAnimation { duration: 500; easing.type: Easing.OutBounce } }
      }
      Text {
        textFormat: Text.PlainText
        font.family: fighter.theme.mono
        font.pixelSize: fighter.theme.small
        font.bold: fighter.marked
        color: fighter.theme.text
        text: fighter.name
      }
      Text {
        textFormat: Text.PlainText
        font.family: fighter.theme.mono
        font.pixelSize: fighter.theme.small
        color: fighter.theme.dim
        text: fighter.down ? "fallen" : fighter.bar(fighter.hp, fighter.maximum)
      }
    }

    // The damage rising off whoever took it.
    Text {
      id: pop
      x: (figure.width - width) / 2
      y: figure.height * 0.25
      opacity: 0
      textFormat: Text.PlainText
      font.family: fighter.theme.mono
      font.pixelSize: fighter.theme.body * 1.3
      font.bold: true
    }

    ParallelAnimation {
      id: rise
      NumberAnimation { target: pop; property: "y"; from: figure.height * 0.3; to: -fighter.theme.body; duration: 1100; easing.type: Easing.OutCubic }
      SequentialAnimation {
        NumberAnimation { target: pop; property: "opacity"; to: 1; duration: 90 }
        PauseAnimation { duration: 600 }
        NumberAnimation { target: pop; property: "opacity"; to: 0; duration: 400 }
      }
    }
    SequentialAnimation {
      id: lunging
      NumberAnimation { target: body; property: "x"; to: fighter.facing * fighter.theme.body * 1.2; duration: 110; easing.type: Easing.OutQuad }
      NumberAnimation { target: body; property: "x"; to: 0; duration: 320; easing.type: Easing.OutBack }
    }
    SequentialAnimation {
      id: reel
      NumberAnimation { target: body; property: "x"; to: -fighter.facing * 7; duration: 50 }
      NumberAnimation { target: body; property: "x"; to: fighter.facing * 5; duration: 70 }
      NumberAnimation { target: body; property: "x"; to: -fighter.facing * 3; duration: 70 }
      NumberAnimation { target: body; property: "x"; to: 0; duration: 90 }
    }
    SequentialAnimation {
      id: sidestep
      NumberAnimation { target: body; property: "y"; to: -5; duration: 90; easing.type: Easing.OutQuad }
      NumberAnimation { target: body; property: "y"; to: 0; duration: 260; easing.type: Easing.OutBounce }
    }
    SequentialAnimation {
      id: flash
      ColorAnimation { target: figure; property: "color"; to: fighter.theme.urgent; duration: 60 }
      ColorAnimation { target: figure; property: "color"; to: "#ffffff"; duration: 60 }
      ColorAnimation { target: figure; property: "color"; to: fighter.theme.urgent; duration: 90 }
      ColorAnimation { target: figure; property: "color"; to: fighter.ink; duration: 700 }
    }

    function bar(value, maximum) {
      var cells = 8
      var filled = Math.max(0, Math.min(cells, Math.round(cells * value / Math.max(1, maximum))))
      return "█".repeat(filled) + "░".repeat(cells - filled) + " " + value + "/" + maximum
    }
  }

  Column {
    id: content
    anchors { left: parent.left; right: parent.right; top: parent.top; margins: tableau.theme.body }
    spacing: tableau.theme.body * 0.8

    Text {
      width: parent.width
      textFormat: Text.StyledText
      font.family: tableau.theme.mono
      font.pixelSize: tableau.theme.small
      color: tableau.theme.dim
      text: tableau.fight ? "<b>ROUND " + tableau.fight.round + "</b>   " + tableau.fight.order.map(f =>
        "<span style=\"color:" + (f.id === "pc" ? tableau.theme.accent : tableau.theme.dim) + "\">[" + f.card + " " + tableau.html(f.name) + "]</span>").join(" ") : ""
    }

    Row {
      id: stage
      width: parent.width
      spacing: tableau.theme.body * 1.5

      Fighter {
        id: heroFighter
        theme: tableau.theme
        art: tableau.figures.hero || []
        name: tableau.hero ? tableau.hero.name.toUpperCase() : ""
        hp: tableau.hero && tableau.hero.tracks.hp ? tableau.hero.tracks.hp.value : 0
        maximum: tableau.hero && tableau.hero.tracks.hp ? tableau.hero.tracks.hp.max : 1
        marked: true
        facing: 1
        // Low on HP, the hero's figure keeps a little of the red.
        ink: maximum > 0 && hp * 4 <= maximum ? Qt.tint(tableau.theme.text, Qt.rgba(tableau.theme.urgent.r, tableau.theme.urgent.g, tableau.theme.urgent.b, 0.5)) : tableau.theme.text
      }

      // The last blow: an arrow from whoever struck to whoever it was aimed at.
      Text {
        id: arrow
        anchors.verticalCenter: parent.verticalCenter
        textFormat: Text.PlainText
        font.family: tableau.theme.mono
        font.pixelSize: tableau.theme.body
        color: !tableau.last ? tableau.theme.faint : tableau.heroStruck ? tableau.theme.accent : tableau.theme.urgent
        text: !tableau.last ? "  ·  ·  ·  " : tableau.heroStruck
          ? (tableau.last.hit ? "──⚔──▶" : "── ─ ─▷")
          : (tableau.last.hit ? "◀──⚔──" : "◁─ ─ ──")
        SequentialAnimation {
          id: strike
          NumberAnimation { target: arrow; property: "scale"; from: 0.6; to: 1.25; duration: 140; easing.type: Easing.OutQuad }
          NumberAnimation { target: arrow; property: "scale"; to: 1.0; duration: 220 }
        }
      }

      // The foes in initiative order; a crowd wraps onto a second line. The model is a
      // count, so a reload of state.json keeps the same fighters (and their animations).
      Flow {
        width: stage.width - heroFighter.width - arrow.width - stage.spacing * 2
        spacing: tableau.theme.body * 1.5

        Repeater {
          id: foes
          model: tableau.foeIds.length
          delegate: Fighter {
            required property int index
            readonly property string foeId: tableau.foeIds[index] || ""
            readonly property var foe: tableau.fight && tableau.fight.foes[foeId] ? tableau.fight.foes[foeId] : ({ name: "", hp: 0, max: 1, down: true })
            theme: tableau.theme
            art: tableau.figures.foes[foeId] || []
            name: foe.name
            hp: foe.hp
            maximum: foe.max
            down: foe.down
            marked: tableau.last !== null && (tableau.last.to === foeId || tableau.last.from === foeId)
            facing: -1
          }
        }
      }
    }

    Text {
      width: parent.width
      visible: tableau.last !== null
      textFormat: Text.PlainText
      wrapMode: Text.Wrap
      font.family: tableau.theme.mono
      font.pixelSize: tableau.theme.small
      color: tableau.heroStruck ? tableau.theme.text : tableau.theme.urgentText
      text: tableau.last ? tableau.last.text : ""
    }

    Text {
      width: parent.width
      visible: tableau.fight !== null && !!tableau.fight.incoming
      textFormat: Text.PlainText
      wrapMode: Text.Wrap
      font.family: tableau.theme.mono
      font.pixelSize: tableau.theme.small
      font.bold: true
      color: tableau.theme.urgentText
      text: tableau.fight && tableau.fight.incoming ? tableau.fight.incoming.name + " is about to hit: " + tableau.fight.incoming.damage
        + ". Evade, parry or take it (on the table, or tell the GM)." : ""
      SequentialAnimation on opacity {
        running: tableau.fight !== null && !!tableau.fight.incoming
        loops: Animation.Infinite
        NumberAnimation { to: 0.55; duration: 700; easing.type: Easing.InOutSine }
        NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
      }
    }
  }

  function html(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }
}
