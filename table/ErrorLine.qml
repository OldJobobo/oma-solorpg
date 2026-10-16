import QtQuick
// Qualified: from Qt 6.12 QtQuick has a Color of its own, which a bare Color would mean.
import qs.Commons as Commons

// What went wrong, in red, under the part of the Table it belongs to (its `place`), and
// nothing when nothing did. The Panel gives it the words, from its commands and its reads.
Line {
  property string place: ""
  visible: text !== ""
  color: Commons.Color.urgent
  size: Commons.Style.font.bodySmall
}
