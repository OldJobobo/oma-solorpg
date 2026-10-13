import QtQuick
import Quickshell
import Quickshell.Io
// Qualified: from Qt 6.12 QtQuick has a Color of its own, which a bare Color would mean.
import qs.Commons as Commons
import qs.Ui

// The d20 in the bar. It follows the game: it spins when a die is cast and lands with a
// flare of gold for a Dragon or red for a Demon; it is lit when the GM is waiting for your
// answer, pulses slowly red while the hero is dying, and turns into a skull once they are
// dead. The tooltip says who and where. Left click opens or closes the Table; right click
// opens the Book.
BarWidget {
  id: root
  moduleName: "cabral.oma-solorpg"

  readonly property string solo: decodeURIComponent(Qt.resolvedUrl("bin/solo").toString().replace(/^file:\/\//, ""))
  readonly property string stateDir: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/solo"
  property string campaign: ""
  property var game: null

  readonly property var pc: game && game.pc ? game.pc : null
  readonly property bool dying: pc !== null && !!pc.dying
  readonly property bool dead: pc !== null && pc.dead === true
  readonly property bool waiting: game !== null && game.awaiting_player === true && !dead && !(game.ended)
  readonly property color resting: root.waiting ? Commons.Color.accent : (root.bar ? root.bar.barForeground : Commons.Color.foreground)

  // The last roll the d20 has spun for, so a reload never spins it again, and the flare
  // it lands with (gold, the Book's Dragon colour, or red).
  property int rollSeen: -1
  property color flare: "#d9a441"
  property real flareLevel: 0

  // The game belongs to its campaign: another one picked, or this one deleted, drops it
  // before anything new loads. Deleting takes `current` away first, so the old state.json
  // is no longer watched when it goes, and a hero left dying would pulse on for good.
  onCampaignChanged: {
    root.game = null
    root.rollSeen = -1
  }
  onGameChanged: {
    var story = root.game && root.game.story ? root.game.story : []
    var roll = story.filter(b => b.kind === "roll").pop()
    var seq = roll ? roll.seq : 0
    if (root.rollSeen >= 0 && seq > root.rollSeen) {
      var outcome = roll.outcome || {}
      root.flare = outcome.dragon ? "#d9a441" : Commons.Color.urgent
      spin.flares = !!(outcome.dragon || outcome.demon)
      spin.restart()
    }
    root.rollSeen = seq
  }

  SequentialAnimation {
    id: spin
    property bool flares: false
    NumberAnimation { target: button; property: "rotation"; from: 0; to: 720; duration: 1200; easing.type: Easing.OutCubic }
    ScriptAction { script: if (spin.flares) flaring.restart() }
    NumberAnimation { target: button; property: "scale"; from: 1.3; to: 1; duration: 320; easing.type: Easing.OutBack }
  }

  SequentialAnimation {
    id: flaring
    NumberAnimation { target: root; property: "flareLevel"; to: 1; duration: 90 }
    PauseAnimation { duration: 1600 }
    NumberAnimation { target: root; property: "flareLevel"; to: 0; duration: 900; easing.type: Easing.InQuad }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  FileView {
    path: root.stateDir + "/current"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.campaign = text().trim()
    onLoadFailed: root.campaign = ""
  }

  FileView {
    path: root.campaign !== "" ? root.campaign + "/state.json" : ""
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try {
        root.game = JSON.parse(text())
      } catch (e) {
        // Caught mid-write; the next change brings the whole file.
      }
    }
    onLoadFailed: root.game = null
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: String.fromCodePoint(root.dead ? 0xF068C : 0xF1155)  // Nerd Font md-skull, md-dice_d20
    active: root.dying
    foreground: Qt.tint(root.resting, Qt.rgba(root.flare.r, root.flare.g, root.flare.b, root.flareLevel))
    // The button fades its own opacity on `dimmed`; toggling it makes the dying pulse.
    dimmed: root.dead || (root.dying && root.pulse)
    tooltipText: root.tooltip()
    onPressed: function(button) {
      if (button === Qt.RightButton) {
        Quickshell.execDetached([root.solo, "play"])
      } else {
        Quickshell.execDetached(["omarchy-shell", "shell", "toggle", "cabral.oma-solorpg"])
      }
    }
  }

  property bool pulse: false
  Timer {
    interval: 800
    repeat: true
    running: root.dying
    onTriggered: root.pulse = !root.pulse
    onRunningChanged: if (!running) root.pulse = false
  }

  function tooltip() {
    if (!root.pc) return "oma-solorpg (right click: the Book)"
    var hp = root.pc.tracks.hp ? " · HP " + root.pc.tracks.hp.value + "/" + root.pc.tracks.hp.max : ""
    var line = root.pc.name + " · " + (root.game.scene_title || "") + hp
    var now = root.dead ? root.pc.name + " has fallen." : root.dying ? "Dying: roll against death." : root.waiting ? "The GM is waiting for you." : ""
    return line + (now ? "\n" + now : "") + "\nLeft click: the Table · right click: the Book"
  }
}
