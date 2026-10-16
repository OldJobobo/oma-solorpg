import QtQuick

// A heading that folds its section away. Click it, or Enter or Space on it, to open or close.
Heading {
  id: fold
  property string label: ""
  property bool open: false
  // The Table's colours: the text's under the pointer or the keyboard, dim otherwise.
  property color textColor
  property color dim
  // What opening or closing it does; a fold whose state is kept elsewhere (a move group) says so.
  property var toggle: () => fold.open = !fold.open
  text: (open ? "▾ " : "▸ ") + label
  color: foldMouse.containsMouse || activeFocus ? fold.textColor : fold.dim
  activeFocusOnTab: true
  Keys.onPressed: event => {
    if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
      fold.toggle()
      event.accepted = true
    }
  }
  Accessible.role: Accessible.Button
  Accessible.name: label
  Accessible.description: open ? "Open: click to fold it away" : "Folded: click to open it"
  Accessible.onPressAction: fold.toggle()

  MouseArea {
    id: foldMouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: fold.toggle()
  }
}
