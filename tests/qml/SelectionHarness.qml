import QtQuick
import "../../book"

Item {
  id: harness
  width: 900
  height: 700
  property string prose: "The river is **quiet**, and the lamps are waiting.\n\nA second paragraph says *listen first*."
  property bool customSelectionColors: false
  QtObject {
    id: theme
    property color text: "#c0caf5"
    property color dim: Qt.darker(text, 1.6)
    property color faint: Qt.rgba(text.r, text.g, text.b, 0.22)
    property color background: "#1a1b26"
    property color surface: "#20212e"
    property color accent: "#7aa2f7"
    property color urgent: "#f7768e"
    property color gold: "#e0af68"
    property var selection: harness.customSelectionColors ? "#e0af68" : undefined
    property var selectedText: harness.customSelectionColors ? "#1a1b26" : undefined
    property string mono: "DejaVu Sans Mono"
    property string serif: "DejaVu Serif"
    property real small: 12
    property real body: 14
    property real prose: 16
    property real radius: 4
  }
  BookTextSelection { id: selection; objectName: "selectionController" }
  Rectangle { anchors.fill: parent; color: theme.background }

  Flickable {
    id: flick
    objectName: "selectionFlickable"
    x: 20; y: 20; width: 620; height: 500
    contentHeight: passages.height
    clip: true
    boundsBehavior: Flickable.StopAtBounds
    Column {
      id: passages
      width: parent.width
      spacing: 16
      StoryEntry {
        objectName: "selectionGMEntry"
        width: parent.width
        theme: theme
        selectionController: selection
        beat: ({ kind: "gm", text: harness.prose })
      }
      SelectableText {
        objectName: "selectionPlainPassage"
        width: parent.width
        theme: theme
        selectionController: selection
        wrapMode: Text.Wrap
        text: "Player: I say <b>hello</b> & wait."
      }
      SelectableText {
        objectName: "selectionDropcapPassage"
        width: parent.width
        theme: theme
        selectionController: selection
        textFormat: Text.RichText
        wrapMode: Text.Wrap
        text: "<table style=\"float:left\"><tr><td style=\"font-size:48px\">M</td></tr></table><p>arrow Ford lies quiet.</p>"
      }
      Item { width: 1; height: 700 }
    }
  }

  TextEdit {
    objectName: "selectionInput"
    x: 20; y: 560; width: 620; height: 70
    color: theme.text
    font.pixelSize: theme.prose
    selectionColor: theme.accent
    selectedTextColor: theme.text
    text: "A draft that must remain editable"
    onActiveFocusChanged: if (activeFocus) selection.clear()
  }
}
