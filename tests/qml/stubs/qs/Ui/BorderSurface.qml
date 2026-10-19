import QtQuick
import qs.Commons

// Offscreen substitute: exposes the full spec for assertions, draws a flat ring.
Rectangle {
  property var borderSpec: Border.none()
  border.color: borderSpec.color
  border.width: Border.top(borderSpec)
}
