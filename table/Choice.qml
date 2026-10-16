import QtQuick
import qs.Commons as Commons
import qs.Ui

// The Table's button: small, with a border. The Panel gives it the Table's text colour, and
// makes an Act of it, a button that waits while a command runs.
Button {
  bordered: true
  fontSize: Commons.Style.font.bodySmall
  horizontalPadding: Commons.Style.space(8)
  verticalPadding: Commons.Style.space(3)
}
