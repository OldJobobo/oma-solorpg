import QtQuick
import qs.Commons
import qs.Commons as Shell

// Stand-in for omarchy-shell's WidgetButton.
Item {
  id: button
  property var bar: null
  property string text: ""
  property color foreground: Shell.Color.foreground
  property color activeColor: Shell.Color.urgent
  property bool active: false
  property bool dimmed: false
  property string tooltipText: ""
  signal pressed(int button)
  implicitWidth: glyph.implicitWidth + 16
  implicitHeight: 26
  opacity: dimmed ? 0.45 : 1
  Text {
    id: glyph
    anchors.centerIn: parent
    text: button.text
    color: button.active ? button.activeColor : button.foreground
    font.pixelSize: 16
  }
}
