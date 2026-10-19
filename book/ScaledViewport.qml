import QtQuick

// App-only zoom: lay out at the available logical size, then let the scene graph
// scale every native control, font, hit target and spacing together. No texture
// layer or desktop-wide DPI change, and no recreation of the Book/Table state.
Item {
  id: viewport
  property real factor: 1
  readonly property real effectiveFactor: isFinite(factor) && factor >= 1 && factor <= 2 ? factor : 1
  default property alias content: canvas.data
  clip: true

  readonly property Item canvas: Item {
    id: canvas
    parent: viewport
    width: viewport.width / viewport.effectiveFactor
    height: viewport.height / viewport.effectiveFactor
    scale: viewport.effectiveFactor
    transformOrigin: Item.TopLeft
  }
}
