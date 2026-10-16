import QtQuick
// Qualified: from Qt 6.12 QtQuick has a Color of its own, which a bare Color would mean.
import qs.Commons as Commons

// A status tag (a condition held, a clue found). Clickable things are Buttons. Quiet
// tags are dim until lit, so the conditions the hero holds stand out from the rest.
Rectangle {
  id: tag
  property string label: ""
  property bool lit: false
  property bool quiet: false
  // The Table's colours.
  property color textColor
  property color dim
  property color faint
  implicitWidth: tagText.implicitWidth + Commons.Style.space(12)
  implicitHeight: tagText.implicitHeight + Commons.Style.space(6)
  radius: Commons.Style.cornerRadius
  color: lit ? Qt.rgba(Commons.Color.urgent.r, Commons.Color.urgent.g, Commons.Color.urgent.b, 0.25) : "transparent"
  border.width: 1
  border.color: lit ? Commons.Color.urgent : tag.faint

  Text {
    id: tagText
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: tag.label
    color: tag.quiet && !tag.lit ? tag.dim : tag.textColor
    font.family: Commons.Style.font.family
    font.pixelSize: Commons.Style.font.caption
  }
}
