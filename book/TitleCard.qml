import QtQuick
import QtQuick.Effects

// Entering a scene: its name decrypts out of noise, letter by letter, the way Omarchy's
// screensaver brings its logo in, then settles into the book's own lettering with a
// breath of light, between two rules that draw themselves out from the middle. Then the
// card fades and the story carries on.
Item {
  id: card
  property var theme
  property bool gpu: true
  property string title: ""
  property string subtitle: ""
  property string shown: ""
  property int revealed: 0
  readonly property bool settled: revealed >= title.length && title.length > 0

  readonly property string noise: "░▒▓█/\\|<>*+#%&@$~=-_"

  anchors.fill: parent
  visible: opacity > 0
  opacity: 0

  function show(name, under) {
    title = name || ""
    subtitle = under || ""
    revealed = 0
    shown = scramble()
    opacity = 1
    fadeOut.stop()
    rules.width = 0
    decrypt.restart()
    drawRules.restart()
  }

  // Gone at once, wherever it had got to.
  function dismiss() {
    decrypt.stop()
    hold.stop()
    fadeOut.stop()
    drawRules.stop()
    opacity = 0
  }

  function scramble() {
    var out = ""
    for (var i = 0; i < title.length; i++) {
      var c = title[i]
      out += i < revealed || c === " " ? c : noise[Math.floor(Math.random() * noise.length)]
    }
    return out
  }

  Timer {
    id: decrypt
    interval: 38
    repeat: true
    onTriggered: {
      if (Math.random() < 0.55) card.revealed += 1
      card.shown = card.scramble()
      if (card.revealed >= card.title.length) {
        stop()
        card.shown = card.title
        hold.restart()
      }
    }
  }

  Timer { id: hold; interval: 2000; onTriggered: fadeOut.restart() }
  NumberAnimation { id: fadeOut; target: card; property: "opacity"; to: 0; duration: 800; easing.type: Easing.InQuad }
  NumberAnimation { id: drawRules; target: rules; property: "width"; from: 0; to: card.width * 0.5; duration: 1300; easing.type: Easing.OutCubic }

  MouseArea {
    anchors.fill: parent
    onClicked: { decrypt.stop(); hold.stop(); fadeOut.restart() }
  }

  Rectangle {
    anchors.fill: parent
    color: card.theme.background
    opacity: card.gpu ? 0.55 : 0.9
  }

  // The rules above and below: a line each way from a jewel in the middle.
  Item { id: rules; width: 0 }

  component Rule: Item {
    id: rule
    property var theme
    property real reach: 0
    width: reach
    height: jewel.height
    Rectangle { anchors.verticalCenter: parent.verticalCenter; anchors.right: jewel.left; anchors.rightMargin: 8; width: Math.max(0, rule.reach / 2 - 14); height: 1; color: rule.theme.faint }
    Text { id: jewel; anchors.centerIn: parent; text: "◆"; color: rule.theme.gold; font.pixelSize: rule.theme.small; opacity: rule.reach > 20 ? 1 : 0 }
    Rectangle { anchors.verticalCenter: parent.verticalCenter; anchors.left: jewel.right; anchors.leftMargin: 8; width: Math.max(0, rule.reach / 2 - 14); height: 1; color: rule.theme.faint }
  }

  Column {
    anchors.centerIn: parent
    width: parent.width * 0.8
    spacing: card.theme.body * 1.1

    Rule { anchors.horizontalCenter: parent.horizontalCenter; theme: card.theme; reach: rules.width }

    Item {
      width: parent.width
      height: Math.max(noiseText.implicitHeight, finalText.implicitHeight)

      // While it decrypts: the table's monospace, noise settling into letters.
      Text {
        id: noiseText
        anchors.centerIn: parent
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font.family: card.theme.mono
        font.pixelSize: card.theme.display * 1.3
        font.letterSpacing: 3
        color: card.theme.accent
        text: card.shown
        opacity: card.settled ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: 450 } }
      }

      // Settled: the book's lettering, with a breath of light behind it.
      Text {
        id: glow
        anchors.centerIn: parent
        width: parent.width
        visible: card.gpu
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font: finalText.font
        color: card.theme.gold
        text: card.title
        opacity: card.settled ? 0.55 : 0
        Behavior on opacity { NumberAnimation { duration: 900; easing.type: Easing.OutQuad } }
        layer.enabled: visible && opacity > 0
        layer.effect: MultiEffect { blurEnabled: true; blur: 1.0; blurMax: 32 }
      }
      Text {
        id: finalText
        anchors.centerIn: parent
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font.family: card.theme.serif
        font.pixelSize: card.theme.display * 1.6
        font.capitalization: Font.SmallCaps
        font.letterSpacing: card.settled ? 4 : 12
        color: card.theme.text
        text: card.title
        opacity: card.settled ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 600 } }
        Behavior on font.letterSpacing { NumberAnimation { duration: 900; easing.type: Easing.OutCubic } }
      }
    }

    Text {
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      visible: card.subtitle !== ""
      textFormat: Text.PlainText
      font.family: card.theme.serif
      font.italic: true
      font.pixelSize: card.theme.prose
      color: card.theme.dim
      opacity: card.settled ? 1 : 0
      text: card.subtitle
      Behavior on opacity { NumberAnimation { duration: 700 } }
    }

    Rule { anchors.horizontalCenter: parent.horizontalCenter; theme: card.theme; reach: rules.width }
  }
}
