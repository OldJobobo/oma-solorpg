import QtQuick
import "Md.js" as Md

// One beat of the story. The GM's words read like a book; everything the dice decided
// is set in the table's monospace, so the two never blur together.
Item {
  id: entry
  property var theme
  property var beat: ({})
  property bool opensScene: false   // the GM's first words in a scene get an illuminated initial

  readonly property string kind: beat.kind || ""
  width: parent ? parent.width : 400
  implicitHeight: loader.item ? loader.item.implicitHeight + gap : 0
  readonly property real gap: kind === "gm" || kind === "scene" || kind === "end" ? theme.body * 1.1 : theme.body * 0.45

  Loader {
    id: loader
    width: entry.width
    sourceComponent: ({
      gm: narration, player: player, roll: roll, voice: voice, omen: omen, scene: scene, end: ending,
      hit: blow, hurt: blow, foe: blow, fight: note, oracle: oracle, event: note, clock: note, light: note,
    })[entry.kind] || note
  }

  function verdict(outcome) {
    if (!outcome) return ""
    if (outcome.dragon) return "DRAGON"
    if (outcome.demon) return "DEMON"
    if (outcome.successes !== undefined) return outcome.successes + (outcome.successes === 1 ? " success" : " successes")
    if (outcome.hit !== undefined) return outcome.hit.replace("_", " ") + (outcome.match ? " (match)" : "")
    return outcome.success ? "success" : "failure"
  }

  // Dice fixed by SOLO_SEED (tests, demos) are marked, so a seeded roll never reads as a free one.
  function seeded() {
    return beat.seed !== undefined ? "seeded " + beat.seed : ""
  }

  function verdictColor(outcome) {
    if (!outcome) return theme.text
    if (outcome.dragon) return theme.gold
    if (outcome.demon || !outcome.success) return theme.urgentText
    return theme.accentText
  }

  Component {
    id: narration
    Text {
      textFormat: Text.RichText
      wrapMode: Text.Wrap
      color: entry.theme.text
      font.family: entry.theme.serif
      font.pixelSize: entry.theme.prose
      lineHeight: 1.3
      text: Md.render(entry.beat.text, entry.theme.mono, entry.opensScene ? String(entry.theme.gold) : "", entry.theme.prose)
    }
  }

  Component {
    id: player
    Item {
      implicitHeight: said.implicitHeight
      Rectangle {
        width: 2
        height: said.height
        color: entry.theme.faint
      }
      Text {
        id: said
        x: entry.theme.body
        width: parent.width - x
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: entry.theme.dim
        font.family: entry.theme.serif
        font.italic: true
        font.pixelSize: entry.theme.prose * 0.95
        lineHeight: 1.2
        text: entry.beat.text
      }
    }
  }

  Component {
    id: roll
    Row {
      spacing: entry.theme.body * 0.6
      Text {
        textFormat: Text.PlainText
        font.family: entry.theme.mono
        font.pixelSize: entry.theme.body * 1.4
        color: entry.verdictColor(entry.beat.outcome)
        text: entry.beat.death ? "☠" : entry.beat.burned ? "✹" : "⚄"
        anchors.verticalCenter: parent.verticalCenter
      }
      Column {
        Text {
          textFormat: Text.StyledText
          font.family: entry.theme.mono
          font.pixelSize: entry.theme.body
          color: entry.theme.text
          text: (entry.beat.pushed ? "pushed " : entry.beat.death ? "death roll " : entry.beat.burned ? "burned momentum on " : "") + "<b>" + entry.html(entry.beat.label || "") + "</b>"
            + (entry.beat.outcome && entry.beat.outcome.result !== undefined ? "  " + entry.beat.outcome.result + " vs " + entry.beat.outcome.target : "")
            + (entry.beat.outcome && entry.beat.outcome.hit !== undefined ? "  " + entry.beat.outcome.score + " vs " + entry.beat.outcome.challenge.join(" · ") : "")
            + "  <span style=\"color:" + entry.verdictColor(entry.beat.outcome) + "\">" + entry.verdict(entry.beat.outcome) + "</span>"
        }
        Text {
          visible: text !== ""
          textFormat: Text.PlainText
          font.family: entry.theme.mono
          font.pixelSize: entry.theme.small
          color: entry.theme.dim
          text: [entry.beat.purpose || "",
                 entry.beat.boons ? entry.beat.boons + (entry.beat.boons === 1 ? " boon" : " boons") : "",
                 entry.beat.banes ? entry.beat.banes + (entry.beat.banes === 1 ? " bane" : " banes") : "",
                 entry.beat.outcome && entry.beat.outcome.rolls && entry.beat.outcome.rolls.length > 1 ? "rolled " + entry.beat.outcome.rolls.join(" and ") : "",
                 entry.beat.outcome && entry.beat.outcome.groups ? entry.beat.outcome.groups.map(g => g.name + " " + (g.rolls.join(" ") || "-")).join("  ") : "",
                 entry.seeded()]
            .filter(t => t !== "").join(" · ")
        }
      }
    }
  }

  Component {
    id: voice
    Item {
      implicitHeight: voiceColumn.implicitHeight
      Rectangle {
        width: 3
        height: voiceColumn.height
        color: entry.theme.accent
        radius: 1
      }
      Column {
        id: voiceColumn
        x: entry.theme.body
        width: parent.width - x
        spacing: 2
        Text {
          textFormat: Text.PlainText
          font.family: entry.theme.mono
          font.pixelSize: entry.theme.small
          font.letterSpacing: 1.5
          color: entry.theme.accentText
          text: (entry.beat.label || "").toUpperCase() + "  [" + (entry.beat.outcome ? entry.beat.outcome.target : "") + "]  "
            + (entry.beat.outcome && entry.beat.outcome.dragon ? "DRAGON" : "SUCCESS")
            + (entry.seeded() ? "  " + entry.seeded().toUpperCase() : "")
        }
        Text {
          width: parent.width
          textFormat: Text.PlainText
          wrapMode: Text.Wrap
          font.family: entry.theme.serif
          font.italic: true
          font.pixelSize: entry.theme.prose * 0.95
          lineHeight: 1.2
          color: entry.theme.text
          text: entry.beat.text
        }
      }
    }
  }

  Component {
    id: omen
    Text {
      horizontalAlignment: Text.AlignHCenter
      textFormat: Text.PlainText
      wrapMode: Text.Wrap
      font.family: entry.theme.serif
      font.italic: true
      font.pixelSize: entry.theme.prose * 0.95
      color: entry.theme.dim
      text: "~  " + (entry.beat.text || "").replace(/^[^:]*\(\d+\):\s*/, "") + "  ~" + (entry.seeded() ? "  (" + entry.seeded() + ")" : "")
      opacity: 0
      Component.onCompleted: fade.start()
      NumberAnimation on opacity { id: fade; running: false; to: 1; duration: 2400; easing.type: Easing.InQuad }
    }
  }

  Component {
    id: scene
    Column {
      spacing: 4
      topPadding: entry.theme.body
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        font.family: entry.theme.mono
        font.pixelSize: entry.theme.small
        color: entry.theme.faint
        text: "─".repeat(8) + "  ✦  " + "─".repeat(8)
      }
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        font.family: entry.theme.serif
        font.pixelSize: entry.theme.heading
        font.letterSpacing: 2
        font.capitalization: Font.SmallCaps
        color: entry.theme.text
        text: entry.beat.title || ""
      }
    }
  }

  Component {
    id: ending
    Column {
      spacing: 6
      topPadding: entry.theme.body
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        font.family: entry.theme.serif
        font.pixelSize: entry.theme.heading
        font.capitalization: Font.SmallCaps
        color: entry.theme.gold
        text: "The End"
      }
      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        font.family: entry.theme.serif
        font.italic: true
        font.pixelSize: entry.theme.prose
        color: entry.theme.text
        text: entry.beat.text || ""
      }
    }
  }

  Component {
    id: blow
    Text {
      textFormat: Text.PlainText
      wrapMode: Text.Wrap
      font.family: entry.theme.mono
      font.pixelSize: entry.theme.small
      color: entry.kind === "hurt" ? entry.theme.urgentText : entry.kind === "hit" ? entry.theme.accentText : entry.theme.dim
      text: (entry.kind === "hurt" ? "→ " : entry.kind === "hit" ? "⚔ " : "← ") + (entry.beat.text || "") + (entry.seeded() ? " · " + entry.seeded() : "")
    }
  }

  Component {
    id: oracle
    Text {
      textFormat: Text.PlainText
      wrapMode: Text.Wrap
      font.family: entry.theme.mono
      font.pixelSize: entry.theme.small
      color: entry.theme.text
      text: "☉ " + (entry.beat.text || "") + (entry.seeded() ? " · " + entry.seeded() : "")
    }
  }

  Component {
    id: note
    Text {
      textFormat: Text.PlainText
      wrapMode: Text.Wrap
      font.family: entry.theme.mono
      font.pixelSize: entry.theme.small
      color: entry.theme.dim
      text: "· " + (entry.beat.text || "") + (entry.seeded() ? " · " + entry.seeded() : "")
    }
  }

  function html(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }
}
