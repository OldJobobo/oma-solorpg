import QtQuick

// Everything the hero has learned, like a CRPG's journal: the people met, with their
// faces; what they want and fear, blanked out until the story reveals it; secrets found;
// promises made; clues. A foe's numbers appear once the hero has fought it.
Rectangle {
  id: codex
  property var theme
  property BookTextSelection selectionController: null
  property var game: null
  signal closed()

  readonly property var people: game && game.codex ? game.codex : []
  readonly property var faces: game && game.faces ? game.faces : ({})

  color: theme.surface
  border.width: 1
  border.color: theme.faint
  radius: theme.radius

  component Passage: SelectableText {
    objectName: "codexPassage"
    theme: codex.theme
    selectionController: codex.selectionController
  }

  MouseArea { anchors.fill: parent }  // clicks stay in the codex

  Flickable {
    id: flick
    anchors.fill: parent
    anchors.margins: codex.theme.body
    contentHeight: column.implicitHeight
    boundsBehavior: Flickable.StopAtBounds
    clip: true

    Column {
      id: column
      width: flick.width
      spacing: codex.theme.body

      Row {
        width: parent.width
        Passage {
          width: parent.width - close.width
          textFormat: Text.PlainText
          font.family: codex.theme.serif
          font.pixelSize: codex.theme.heading
          font.capitalization: Font.SmallCaps
          color: codex.theme.text
          text: "Codex"
        }
        Text {
          id: close
          textFormat: Text.PlainText
          font.family: codex.theme.mono
          font.pixelSize: codex.theme.body
          color: closeMouse.containsMouse ? codex.theme.text : codex.theme.dim
          text: "×"
          MouseArea { id: closeMouse; anchors.fill: parent; anchors.margins: -8; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: codex.closed() }
        }
      }

      Passage {
        visible: codex.people.length === 0
        width: parent.width
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        font.family: codex.theme.serif
        font.italic: true
        font.pixelSize: codex.theme.prose
        color: codex.theme.dim
        text: "No one yet. The pages fill as the hero meets people."
      }

      Repeater {
        model: codex.people
        delegate: Row {
          id: person
          required property var modelData
          width: column.width
          spacing: codex.theme.body

          Passage {
            id: face
            textFormat: Text.PlainText
            font.family: codex.theme.mono
            font.pixelSize: codex.theme.small * 0.9
            color: modelData.fate === "dead" ? codex.theme.faint : codex.theme.text
            text: (codex.faces[modelData.id] || []).join("\n")
          }

          Column {
            width: person.width - face.width - person.spacing
            spacing: 3

            Passage {
              width: parent.width
              wrapMode: Text.Wrap
              textFormat: Text.PlainText
              font.family: codex.theme.serif
              font.pixelSize: codex.theme.prose
              font.bold: true
              color: codex.theme.text
              text: modelData.name + (modelData.fate !== "alive" ? " (" + modelData.fate + ")" : "")
            }
            Passage {
              width: parent.width
              wrapMode: Text.Wrap
              textFormat: Text.PlainText
              font.family: codex.theme.mono
              font.pixelSize: codex.theme.small
              color: codex.theme.dim
              text: [modelData.role, modelData.faction, modelData.attitude].filter(t => t).join(" · ")
            }
            Repeater {
              model: ["wants", "fears"].filter(k => person.modelData.known[k])
              delegate: Passage {
                required property string modelData
                width: parent.width
                wrapMode: Text.Wrap
                textFormat: Text.StyledText
                font.family: codex.theme.serif
                font.pixelSize: codex.theme.prose * 0.92
                color: codex.theme.text
                text: "<i>" + modelData.charAt(0).toUpperCase() + modelData.slice(1) + ":</i> " + codex.html(person.modelData.known[modelData])
              }
            }
            Repeater {
              model: person.modelData.secrets
              delegate: Passage {
                required property string modelData
                width: parent.width
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
                font.family: codex.theme.serif
                font.italic: true
                font.pixelSize: codex.theme.prose * 0.92
                color: codex.theme.gold
                text: "✦ " + modelData
              }
            }
            Repeater {
              model: person.modelData.memories
              delegate: Passage {
                required property string modelData
                width: parent.width
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
                font.family: codex.theme.serif
                font.pixelSize: codex.theme.prose * 0.9
                color: codex.theme.dim
                text: "Remembers: " + modelData
              }
            }
            // What the hero doesn't know yet: blanked, so the page shows there is more.
            Passage {
              visible: modelData.unknown > 0
              width: parent.width
              wrapMode: Text.Wrap
              textFormat: Text.PlainText
              font.family: codex.theme.mono
              font.pixelSize: codex.theme.small
              color: codex.theme.faint
              text: Array(modelData.unknown).fill("▒▒▒▒▒ ▒▒▒ ▒▒▒▒▒▒").join("\n")
            }
            Passage {
              visible: modelData.stats !== null
              textFormat: Text.PlainText
              font.family: codex.theme.mono
              font.pixelSize: codex.theme.small
              color: codex.theme.dim
              text: modelData.stats ? "Fought: HP " + modelData.stats.hp + " · armor " + modelData.stats.armor : ""
            }
          }
        }
      }

      Passage {
        visible: codex.promiseLines().length > 0
        textFormat: Text.PlainText
        font.family: codex.theme.serif
        font.pixelSize: codex.theme.title
        font.capitalization: Font.SmallCaps
        color: codex.theme.text
        text: "Promises"
      }
      Repeater {
        model: codex.promiseLines()
        delegate: Passage {
          required property string modelData
          width: column.width
          wrapMode: Text.Wrap
          textFormat: Text.PlainText
          font.family: codex.theme.serif
          font.pixelSize: codex.theme.prose * 0.92
          color: codex.theme.text
          text: modelData
        }
      }

      Passage {
        visible: codex.game !== null && codex.game.clues.length > 0
        textFormat: Text.PlainText
        font.family: codex.theme.serif
        font.pixelSize: codex.theme.title
        font.capitalization: Font.SmallCaps
        color: codex.theme.text
        text: "Clues"
      }
      Passage {
        visible: codex.game !== null && codex.game.clues.length > 0
        width: column.width
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        font.family: codex.theme.mono
        font.pixelSize: codex.theme.small
        color: codex.theme.text
        text: codex.game ? codex.game.clues.map(c => "◆ " + c.replace(/_/g, " ")).join("\n") : ""
      }
    }
  }

  function promiseLines() {
    if (!game) return []
    return Object.keys(game.promises).map(k => {
      var p = game.promises[k]
      var npc = game.npcs[p.npc]
      return (npc ? npc.name : p.npc) + ": " + p.terms + " (" + p.status + ")"
    })
  }

  function html(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }
}
