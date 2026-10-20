import QtQuick
import QtQuick.Controls as Controls
import qs.Commons

// A native keyboard-accessible dropdown; every family previews itself.
Controls.ComboBox {
  id: picker
  objectName: "bookSerifFontPicker"
  required property var theme
  property string family: ""
  property var families: []
  property bool busy: false
  signal familyRequested(string family)
  readonly property var choices: [""].concat(family !== "" && families.indexOf(family) === -1 ? [family] : []).concat(families)
  function selectedIndex() { return Math.max(0, choices.indexOf(family)) }

  model: choices
  currentIndex: selectedIndex()
  enabled: !busy
  implicitHeight: Math.max(Style.space(38), selectedFont.implicitHeight + Style.space(16))
  leftPadding: Style.space(10)
  rightPadding: Style.space(30)
  topPadding: Style.space(8)
  bottomPadding: Style.space(8)
  Accessible.name: "Book serif font"
  Accessible.description: "Choose a reading font for the Book, or System default to follow Omarchy."
  onActivated: index => {
    familyRequested(choices[index])
    // Keep the saved choice authoritative, including after a failed write.
    currentIndex = Qt.binding(() => picker.selectedIndex())
  }

  contentItem: Text {
    id: selectedFont
    text: picker.family === "" ? "System default" : picker.family
    font.family: picker.family === "" ? "serif" : picker.family
    font.pixelSize: Style.font.body
    color: picker.theme.text
    textFormat: Text.PlainText
    elide: Text.ElideRight
    verticalAlignment: Text.AlignVCenter
  }
  indicator: Text {
    x: picker.width - width - Style.space(10)
    anchors.verticalCenter: parent.verticalCenter
    text: "▾"
    color: picker.theme.dim
    font.pixelSize: Style.font.body
  }
  background: ControlSurface {
    theme: picker.theme
    controlState: !picker.enabled ? "disabled" : picker.activeFocus ? "focus" : picker.hovered ? "hover-cursor" : "normal"
    baseColor: picker.theme.surface
  }
  delegate: Controls.ItemDelegate {
    id: option
    required property string modelData
    required property int index
    objectName: "serifFontOption_" + index
    width: fontList.width
    implicitHeight: Math.max(Style.space(38), preview.implicitHeight + Style.space(16))
    highlighted: picker.highlightedIndex === index
    padding: Style.space(10)
    Accessible.name: modelData || "System default"
    contentItem: Text {
      id: preview
      objectName: "serifFontPreview_" + option.index
      text: option.modelData || "System default"
      font.family: option.modelData || "serif"
      font.pixelSize: Style.font.body
      color: picker.theme.text
      textFormat: Text.PlainText
      elide: Text.ElideRight
    }
    background: ControlSurface {
      theme: picker.theme
      framed: false
      controlState: option.highlighted ? "focus" : option.hovered ? "hover-cursor" : "normal"
    }
  }
  popup: Controls.Popup {
    objectName: "serifFontPopup"
    y: picker.height + Style.space(4)
    width: picker.width
    padding: Style.space(4)
    implicitHeight: Math.min(contentItem.implicitHeight + topPadding + bottomPadding, Style.space(280))
    contentItem: ListView {
      id: fontList
      objectName: "serifFontList"
      implicitHeight: contentHeight
      clip: true
      model: picker.popup.visible ? picker.delegateModel : null
      currentIndex: picker.highlightedIndex
      boundsBehavior: Flickable.StopAtBounds
      Controls.ScrollIndicator.vertical: Controls.ScrollIndicator {}
    }
    background: Rectangle {
      color: picker.theme.surfacePaper
      radius: picker.theme.radius
      border.color: picker.theme.dim
      border.width: 1
    }
  }
}
