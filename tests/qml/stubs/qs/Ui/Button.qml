import QtQuick
import qs.Commons

// Stand-in for omarchy-shell's Button: the properties the plugin sets, drawn simply.
Rectangle {
  id: button
  property string text: ""
  property string tooltipText: ""
  property bool selected: false
  property bool bordered: false
  property color foreground: Color.foreground
  property string fontFamily: Style.font.family
  property real fontSize: Style.font.body
  property real horizontalPadding: 8
  property real verticalPadding: 4
  signal clicked()
  implicitWidth: label.implicitWidth + horizontalPadding * 2
  implicitHeight: label.implicitHeight + verticalPadding * 2
  radius: 3
  color: selected ? Qt.rgba(foreground.r, foreground.g, foreground.b, 0.15) : "transparent"
  border.width: bordered ? 1 : 0
  border.color: selected ? Color.accent : Qt.rgba(foreground.r, foreground.g, foreground.b, 0.3)
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
