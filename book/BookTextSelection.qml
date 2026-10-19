import QtQuick

// One selection per Book. Dragging text must not turn into a flick, and a new
// story beat must not scroll away from the passage the player is copying.
QtObject {
  id: selection
  // An Item reference is nulled by Qt if a virtualized passage is destroyed.
  // SelectableText supplies its selectedText/menuOpen/deselect protocol.
  property Item owner: null
  property bool dragging: false
  readonly property bool engaged: dragging || (owner !== null && (owner.selectedText !== "" || owner.menuOpen))
  onOwnerChanged: if (!owner) dragging = false

  function claim(passage) {
    if (owner === passage) return
    var previous = owner
    owner = passage
    if (previous) previous.deselect()
  }

  function hold(passage, held) {
    if (held) claim(passage)
    if (owner === passage) dragging = held
  }

  function release(passage) {
    if (owner !== passage) return
    owner = null
    dragging = false
  }

  function clear() {
    var previous = owner
    if (previous) previous.deselect()
    owner = null
    dragging = false
  }
}
