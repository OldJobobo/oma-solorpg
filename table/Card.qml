import QtQuick
import QtQuick.Layouts
// Qualified: from Qt 6.12 QtQuick has a Color of its own, which a bare Color would mean.
import qs.Commons as Commons

// A card on the Table: a campaign, an adventure, a fallen hero, a foe, a vow. What is put in
// it is laid out in a column. The Panel gives it the Table's colours.
//
// A card that can be clicked is a button to the keyboard (Tab to it, Enter or Space) and to a screen reader, by `name`.
Rectangle {
  id: card
  property bool selected: false
  property bool clickable: true
  property string name: ""
  // The Table's colours: the text's rings the card with the keyboard, the shade fills a
  // card under the pointer or the keyboard.
  property color textColor
  property color faint
  property color shade
  signal clicked()
  default property alias content: cardColumn.data
  Layout.fillWidth: true
  implicitHeight: cardColumn.implicitHeight + Commons.Style.space(16)
  radius: Commons.Style.cornerRadius
  // Hovered or with the keyboard, it takes the shade dim is measured on; the keyboard's card is ringed in the text colour.
  color: card.clickable && (cardMouse.containsMouse || card.activeFocus) ? card.shade : "transparent"
  border.width: selected || card.activeFocus ? 2 : 1
  border.color: card.activeFocus ? card.textColor : selected ? Commons.Color.accent : card.faint
  activeFocusOnTab: clickable
  Keys.onPressed: event => {
    if (card.clickable && (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)) {
      card.clicked()
      event.accepted = true
    }
  }
  Accessible.role: clickable ? Accessible.Button : Accessible.Grouping
  Accessible.name: name
  Accessible.onPressAction: if (card.clickable) card.clicked()

  // Under the content, so a button inside a card takes its own clicks.
  MouseArea {
    id: cardMouse
    anchors.fill: parent
    enabled: card.clickable
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: card.clicked()
  }

  ColumnLayout {
    id: cardColumn
    anchors { left: parent.left; right: parent.right; top: parent.top; margins: Commons.Style.space(8) }
    spacing: Commons.Style.space(2)
  }
}
