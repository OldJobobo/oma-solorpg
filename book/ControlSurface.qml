import QtQuick

// Omarchy provides the native border renderer through the theme. The Book need
// not import shell modules (and can still be rendered independently in tests).
Item {
  id: chrome
  required property var theme
  property string controlState: "normal"
  property bool framed: true
  property color baseColor: "transparent"
  readonly property alias surface: factory.item

  Loader {
    id: factory
    anchors.fill: parent
    sourceComponent: chrome.theme.controlSurface
  }
  Binding { target: factory.item; property: "controlState"; value: chrome.controlState; when: factory.item !== null }
  Binding { target: factory.item; property: "framed"; value: chrome.framed; when: factory.item !== null }
  Binding { target: factory.item; property: "baseColor"; value: chrome.baseColor; when: factory.item !== null }
}
