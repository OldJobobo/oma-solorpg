import QtQuick
import QtQuick.Layouts
import qs.Commons as Commons

// A line of the Table's text, in the shell's font, wrapped to the width it is given. The
// Panel gives it the Table's text colour.
//
// Text here comes from packs and from the GM's commits, so it is never read as HTML.
Text {
  property int size: Commons.Style.font.body
  Layout.fillWidth: true
  textFormat: Text.PlainText
  font.family: Commons.Style.font.family
  font.pixelSize: size
  wrapMode: Text.Wrap
}
