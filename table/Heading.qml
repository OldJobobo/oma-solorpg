import QtQuick
import QtQuick.Layouts
import qs.Commons as Commons

// The name of a section of the Table, small and in capitals. The Panel gives it the
// Table's dim colour.
Text {
  Layout.fillWidth: true
  Layout.topMargin: Commons.Style.space(10)
  textFormat: Text.PlainText
  font.family: Commons.Style.font.family
  font.pixelSize: Commons.Style.font.caption
  font.capitalization: Font.AllUppercase
  font.letterSpacing: 1
}
