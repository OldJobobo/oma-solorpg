.pragma library

// What the Table and the Book both need: their quieter text colours, and the game's time in words.

// WCAG's contrast between two colours (Qt colours, channels from 0 to 1).
function contrast(a, b) {
  function channel(v) { return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }
  function luminance(c) { return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b) }
  var la = luminance(a), lb = luminance(b)
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

// Text quieter than the body: the text colour taken toward the background, as far as it
// keeps `ratio` against it and never more than `most` of the way. Darkening the text
// instead made it louder on a light theme. A theme whose text is already under `ratio`
// keeps its text as it is.
function fade(text, background, ratio, most) {
  for (var share = most; share > 0; share -= 0.01) {
    var faded = Qt.tint(text, Qt.rgba(background.r, background.g, background.b, share))
    if (contrast(faded, background) >= ratio) return faded
  }
  return text
}
