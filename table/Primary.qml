import QtQuick
import QtQuick.Layouts
import qs.Commons as Commons
import qs.Ui

// The button a screen leads to (New adventure, Begin adventure, the death roll): the width
// of the Table, and lit. The Panel gives it the Table's text colour.
Button {
  Layout.fillWidth: true
  Layout.topMargin: Commons.Style.space(8)
  bordered: true
  selected: true
  verticalPadding: Commons.Style.space(8)
}
