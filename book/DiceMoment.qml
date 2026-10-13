import QtQuick
import QtQuick.Effects
import QtQuick.Particles

// The moment a die is cast. Every roll, whoever made it (the player on the table, the GM
// in a turn), stops the Book for a breath: the skill and its target, the die tumbling,
// spinning and slowing, then where it lands. It lands with a punch and a ring; a Dragon
// throws gold sparks and glows, a Demon shakes and spits red embers. A move (Ironsworn)
// throws an action die and two challenge dice and reads them as a strong hit, a weak hit
// or a miss; a progress roll throws only the challenge dice.
Item {
  id: moment
  property var theme
  property bool gpu: true           // effects need the GPU; without it the moment is plainer
  property var beat: null
  property var faces: []            // what each die shows right now
  property bool landed: false
  property int ticks: 0
  // The dice have come to rest (the Book lights the page for a Dragon or a Demon then,
  // not while they are still tumbling).
  signal settled(var outcome)

  anchors.fill: parent
  visible: opacity > 0
  opacity: 0

  readonly property var outcome: beat ? beat.outcome || {} : {}
  readonly property bool pool: outcome.groups !== undefined
  readonly property bool move: outcome.hit !== undefined
  // A move's action die comes first, when it has one (a progress roll doesn't).
  readonly property int actionDice: move && outcome.action !== undefined ? 1 : 0
  readonly property var finals: move
    ? (actionDice ? [outcome.action] : []).concat(outcome.challenge)
    : pool
    ? outcome.groups.reduce((all, g) => all.concat(g.rolls), []).slice(0, 12)
    : (outcome.rolls && outcome.rolls.length ? outcome.rolls : [outcome.result])
  // Each die's sides, so a tumbling d10 (a Blade Runner step die) never shows a 17.
  readonly property var sides: move
    ? finals.map((_, i) => i < actionDice ? 6 : 10)
    : pool
    ? outcome.groups.reduce((all, g) => all.concat(g.rolls.map(() => g.sides || 6)), []).slice(0, 12)
    : finals.map(() => 20)
  readonly property color verdictColor: outcome.dragon ? theme.gold : outcome.demon || !outcome.success ? theme.urgent : theme.accent
  readonly property string verdict: move ? outcome.hit.replace("_", " ").toUpperCase() + (outcome.match ? " · MATCH" : "")
    : outcome.dragon ? "DRAGON" : outcome.demon ? "DEMON"
    : pool ? (outcome.successes + (outcome.successes === 1 ? " SUCCESS" : " SUCCESSES")) + triggered : outcome.success ? "SUCCESS" : "FAILURE"
  // A move's score in parts: the action die, the stat and the adds, or a track's full boxes.
  readonly property string score: !move ? "" : actionDice
    ? (outcome.dulled ? "0 (the " + outcome.action + " is cancelled)" : outcome.action) + " + " + outcome.stat + (outcome.adds ? " + " + outcome.adds : "") + " = " + outcome.score
    : "progress " + outcome.progress
  // What a pool's dice set off (a 1 on a stress die: panic), said with the result.
  readonly property string triggered: outcome.triggers && outcome.triggers.length ? " · " + outcome.triggers.join(", ").toUpperCase() : ""

  function show(entry) {
    beat = entry
    landed = false
    ticks = 0
    faces = finals.map((_, i) => moment.random(i))
    tumble.interval = 45
    tumble.restart()
    hold.stop()
    fadeOut.stop()
    opacity = 1
    card.scale = 0.85
    popIn.restart()
    spin.restart()
  }

  // Gone at once, whatever it was doing (the Book was shut).
  function end() {
    tumble.stop()
    hold.stop()
    fadeOut.stop()
    spin.stop()
    opacity = 0
  }

  function random(i) {
    return 1 + Math.floor(Math.random() * (sides[i] || 6))
  }

  // A move's dice once they land: the action die plain, a challenge die green when the score
  // beats it, red when it doesn't, and gold when momentum was burned to cancel it.
  function moveTint(index) {
    if (index < actionDice) return outcome.dulled ? theme.faint : theme.text
    var die = index - actionDice
    return outcome.cancelled.indexOf(die) >= 0 ? theme.gold : outcome.score > outcome.challenge[die] ? theme.accent : theme.urgent
  }

  Timer {
    id: tumble
    repeat: true
    onTriggered: {
      moment.ticks += 1
      if (moment.ticks >= 14) {
        stop()
        moment.faces = moment.finals
        moment.landed = true
        spin.stop()
        land.restart()
        ringShape.burst()
        if (moment.outcome.dragon && moment.gpu) sparks.burst(70)
        if (moment.outcome.demon) {
          shake.restart()
          if (moment.gpu) embers.burst(45)
        }
        hold.restart()
        moment.settled(moment.outcome)
      } else {
        moment.faces = moment.finals.map((_, i) => moment.random(i))
        interval = 45 + moment.ticks * moment.ticks * 1.6
      }
    }
  }

  Timer { id: hold; interval: moment.outcome.dragon || moment.outcome.demon ? 2200 : 1500; onTriggered: fadeOut.restart() }
  NumberAnimation { id: fadeOut; target: moment; property: "opacity"; to: 0; duration: 450; easing.type: Easing.InQuad }
  NumberAnimation { id: popIn; target: card; property: "scale"; to: 1; duration: 240; easing.type: Easing.OutBack }
  // Tumbling: the dice rock from side to side, less and less, and bob as they bounce.
  ParallelAnimation {
    id: spin
    SequentialAnimation {
      loops: Animation.Infinite
      NumberAnimation { target: dice; property: "rotation"; to: 18; duration: 90; easing.type: Easing.InOutSine }
      NumberAnimation { target: dice; property: "rotation"; to: -14; duration: 120; easing.type: Easing.InOutSine }
    }
    SequentialAnimation {
      loops: Animation.Infinite
      NumberAnimation { target: dice; property: "y"; to: -moment.theme.body * 0.8; duration: 120; easing.type: Easing.OutQuad }
      NumberAnimation { target: dice; property: "y"; to: 0; duration: 150; easing.type: Easing.InQuad }
    }
  }
  SequentialAnimation {
    id: land
    ParallelAnimation {
      NumberAnimation { target: dice; property: "y"; to: 0; duration: 60 }
      NumberAnimation { target: dice; property: "rotation"; to: 0; duration: 140; easing.type: Easing.OutBack }
      NumberAnimation { target: card; property: "scale"; to: 1.1; duration: 80; easing.type: Easing.OutQuad }
    }
    NumberAnimation { target: card; property: "scale"; to: 1.0; duration: 320; easing.type: Easing.OutBack }
  }
  SequentialAnimation {
    id: shake
    loops: 4
    NumberAnimation { target: card; property: "anchors.horizontalCenterOffset"; to: -10; duration: 35 }
    NumberAnimation { target: card; property: "anchors.horizontalCenterOffset"; to: 10; duration: 55 }
    NumberAnimation { target: card; property: "anchors.horizontalCenterOffset"; to: 0; duration: 35 }
  }

  MouseArea {
    anchors.fill: parent
    onClicked: { hold.stop(); fadeOut.restart() }
  }

  Rectangle {
    anchors.fill: parent
    color: moment.theme.background
    opacity: moment.gpu ? 0.45 : 0.72
  }

  // A Dragon or a Demon: the card glows its colour (a blurred copy behind it).
  Rectangle {
    anchors.fill: card
    anchors.margins: -moment.theme.body * 0.4
    visible: moment.gpu && moment.landed && !!(moment.outcome.dragon || moment.outcome.demon)
    radius: card.radius * 2
    color: moment.verdictColor
    opacity: 0.55
    layer.enabled: visible
    layer.effect: MultiEffect { blurEnabled: true; blur: 1.0; blurMax: 48 }
    SequentialAnimation on opacity {
      running: moment.landed && moment.visible
      loops: Animation.Infinite
      NumberAnimation { to: 0.3; duration: 900; easing.type: Easing.InOutSine }
      NumberAnimation { to: 0.6; duration: 900; easing.type: Easing.InOutSine }
    }
  }

  Rectangle {
    id: card
    anchors.centerIn: parent
    width: column.implicitWidth + moment.theme.body * 4
    height: column.implicitHeight + moment.theme.body * 3
    radius: moment.theme.radius
    color: moment.theme.surface
    border.width: moment.landed && (moment.outcome.dragon || moment.outcome.demon) ? 2 : 1
    border.color: moment.landed ? moment.verdictColor : moment.theme.faint

    Column {
      id: column
      anchors.centerIn: parent
      spacing: moment.theme.body * 0.6

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        font.family: moment.theme.mono
        font.pixelSize: moment.theme.small
        font.letterSpacing: 3
        color: moment.theme.dim
        text: moment.beat ? ((moment.beat.death ? "DEATH ROLL · " : moment.beat.pushed ? "PUSHED · " : moment.beat.burned ? "MOMENTUM BURNED · " : "")
                             + (moment.beat.label || "").toUpperCase() + (moment.move && moment.beat.purpose ? " " + moment.beat.purpose.toUpperCase() : "")
                             + (moment.beat.seed !== undefined ? " · SEEDED " + moment.beat.seed : "")) : ""
      }

      Item {
        anchors.horizontalCenter: parent.horizontalCenter
        width: dice.implicitWidth
        height: dice.implicitHeight + moment.theme.body

        Grid {
          id: dice
          columns: moment.pool ? Math.min(6, moment.faces.length) : Math.max(1, moment.faces.length)
          spacing: moment.theme.body * (moment.pool || moment.move ? 0.8 : 1.4)
          transformOrigin: Item.Center

          Repeater {
            model: moment.faces.length
            delegate: Text {
              required property int index
              readonly property int face: moment.faces[index] || 0
              // With boons or banes the d20 that counts is lit; the other stays dim. In a pool
              // every die that scores is lit (a 6 or more: step dice score from 6 as well).
              readonly property bool counts: moment.pool ? face >= 6 : moment.faces.length < 2 || face === moment.outcome.result
              textFormat: Text.PlainText
              font.family: moment.theme.mono
              font.pixelSize: moment.theme.body * (moment.pool ? 1.05 : 1.25)
              lineHeight: 0.95
              color: !moment.landed ? moment.theme.text : moment.move ? moment.moveTint(index) : counts ? moment.verdictColor : moment.theme.faint
              text: moment.pool || moment.move ? moment.d6(face, moment.sides[index]) : moment.d20(face)
            }
          }
        }
      }

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: moment.move
        textFormat: Text.PlainText
        font.family: moment.theme.mono
        font.pixelSize: moment.theme.body
        color: moment.theme.dim
        text: moment.score + (moment.move ? "  against  " + moment.outcome.challenge.join("  and  ") : "")
        opacity: moment.landed ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 220 } }
      }

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        visible: !moment.pool && !moment.move && moment.outcome.target !== undefined
        textFormat: Text.PlainText
        font.family: moment.theme.mono
        font.pixelSize: moment.theme.body
        color: moment.theme.dim
        text: "needs " + moment.outcome.target + " or less"
      }

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        textFormat: Text.PlainText
        font.family: moment.theme.serif
        font.pixelSize: moment.theme.display
        font.letterSpacing: moment.landed ? 6 : 0
        color: moment.verdictColor
        opacity: moment.landed ? 1 : 0
        text: moment.verdict
        Behavior on opacity { NumberAnimation { duration: 220 } }
        Behavior on font.letterSpacing { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
      }
    }
  }

  // Where the dice land: a ring goes out from them.
  Rectangle {
    id: ringShape
    anchors.centerIn: card
    width: card.width * 0.5
    height: width
    radius: width / 2
    color: "transparent"
    border.width: 2
    border.color: moment.verdictColor
    opacity: 0
    function burst() { ringOut.restart() }
    ParallelAnimation {
      id: ringOut
      NumberAnimation { target: ringShape; property: "width"; from: card.width * 0.3; to: card.width * 1.6; duration: 700; easing.type: Easing.OutCubic }
      NumberAnimation { target: ringShape; property: "opacity"; from: 0.8; to: 0; duration: 700; easing.type: Easing.OutQuad }
    }
  }

  // Sparks for a Dragon, embers for a Demon (GPU particles: nothing without one).
  ParticleSystem { id: particles; running: moment.visible && moment.gpu }
  ImageParticle {
    system: particles
    groups: ["spark"]
    source: "qrc:///particleresources/glowdot.png"
    color: moment.theme.gold
    colorVariation: 0.15
    alpha: 0.9
    entryEffect: ImageParticle.Scale
  }
  ImageParticle {
    system: particles
    groups: ["ember"]
    source: "qrc:///particleresources/glowdot.png"
    color: moment.theme.urgent
    colorVariation: 0.1
    alpha: 0.8
  }
  Emitter {
    id: sparks
    system: particles
    group: "spark"
    anchors.centerIn: card
    width: card.width * 0.4
    height: card.height * 0.3
    enabled: false
    lifeSpan: 1400
    lifeSpanVariation: 500
    size: moment.theme.body * 1.1
    sizeVariation: moment.theme.body * 0.6
    endSize: 2
    velocity: AngleDirection { angleVariation: 360; magnitude: 260; magnitudeVariation: 160 }
    acceleration: PointDirection { y: 140 }
  }
  Emitter {
    id: embers
    system: particles
    group: "ember"
    anchors.horizontalCenter: card.horizontalCenter
    anchors.bottom: card.bottom
    width: card.width
    height: 10
    enabled: false
    lifeSpan: 1800
    lifeSpanVariation: 600
    size: moment.theme.body * 0.8
    sizeVariation: moment.theme.body * 0.4
    endSize: 1
    velocity: AngleDirection { angle: -90; angleVariation: 35; magnitude: 90; magnitudeVariation: 50 }
    acceleration: PointDirection { y: -30; xVariation: 30 }
  }

  // A d20 in text: the face that came up is the triangle in the middle, with its number.
  function d20(n) {
    var s = String(n)
    var label = s.length === 1 ? "  " + s + "  " : " " + s + "  "
    return "     .-^-.\n"
         + "  .-' / \\ '-.\n"
         + " /   /   \\   \\\n"
         + "|   /" + label + "\\   |\n"
         + "|  /_______\\  |\n"
         + " \\  \\     /  /\n"
         + "  '-.\\   /.-'\n"
         + "     '-.-'"
  }

  // A d6 shows its pips; a bigger die in a pool (a d8, d10, d12) shows its number.
  function d6(n, sides) {
    if ((sides || 6) === 6 && n >= 1 && n <= 6) {
      var pips = [["   ", " o ", "   "], ["o  ", "   ", "  o"], ["o  ", " o ", "  o"],
                  ["o o", "   ", "o o"], ["o o", " o ", "o o"], ["o o", "o o", "o o"]][n - 1]
      return ".-------.\n" + pips.map(r => "| " + r.split("").join(" ").replace(/o/g, "●").slice(0, 5) + " |").join("\n") + "\n'-------'"
    }
    var s = String(n)
    return ".-------.\n|       |\n|" + (s.length === 1 ? "   " + s + "   " : "  " + s + "   ") + "|\n|       |\n'-------'"
  }
}
