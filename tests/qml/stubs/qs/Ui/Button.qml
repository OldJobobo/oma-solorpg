import QtQuick
import qs.Commons
import qs.Commons as Shell

// Stand-in for omarchy-shell's Button: the properties the plugin sets, drawn simply.
Rectangle {
  id: button
  property string text: ""
  property string tooltipText: ""
  property bool selected: false
  property bool bordered: false
  property bool focusable: false
  property color foreground: Shell.Color.foreground
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.body
  property real horizontalPadding: 8
  property real verticalPadding: 4
  signal clicked()
  activeFocusOnTab: focusable
  Keys.onReturnPressed: if (focusable) button.clicked()
  Keys.onEnterPressed: if (focusable) button.clicked()
  Keys.onSpacePressed: if (focusable) button.clicked()
  implicitWidth: label.implicitWidth + horizontalPadding * 2
  implicitHeight: label.implicitHeight + verticalPadding * 2
  radius: 3
  color: selected ? Qt.rgba(foreground.r, foreground.g, foreground.b, 0.15) : "transparent"
  border.width: bordered ? 1 : 0
  border.color: selected ? Shell.Color.accent : Qt.rgba(foreground.r, foreground.g, foreground.b, 0.3)
  Text {
    id: label
    anchors.centerIn: parent
    text: button.text
    color: button.foreground
    font.family: button.fontFamily
    font.pixelSize: button.fontSize
  }
  MouseArea { anchors.fill: parent; onClicked: button.clicked() }
}
