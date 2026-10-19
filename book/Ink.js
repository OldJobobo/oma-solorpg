.pragma library

// Text roles are not decorative fills. Composite alpha before measuring, then move
// only unreadable ink toward the theme's foreground (or black/white as a last resort).
function over(ink, paper) {
  return Qt.rgba(ink.r * ink.a + paper.r * (1 - ink.a),
                 ink.g * ink.a + paper.g * (1 - ink.a),
                 ink.b * ink.a + paper.b * (1 - ink.a), 1)
}

function luminance(color) {
  function linear(n) { return n <= 0.04045 ? n / 12.92 : Math.pow((n + 0.055) / 1.055, 2.4) }
  return linear(color.r) * 0.2126 + linear(color.g) * 0.7152 + linear(color.b) * 0.0722
}

function contrast(ink, paper) {
  var a = luminance(over(ink, paper)), b = luminance(paper)
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

function readable(ink, paper, foreground) {
  // A little headroom survives conversion to 8-bit RGB.
  var minimum = 4.55
  ink = over(ink, paper)
  if (contrast(ink, paper) >= minimum) return ink
  var target = over(foreground, paper)
  if (contrast(target, paper) < minimum) {
    var black = Qt.rgba(0, 0, 0, 1), white = Qt.rgba(1, 1, 1, 1)
    target = contrast(black, paper) > contrast(white, paper) ? black : white
  }
  function mix(amount) {
    return Qt.rgba(ink.r + (target.r - ink.r) * amount,
                   ink.g + (target.g - ink.g) * amount,
                   ink.b + (target.b - ink.b) * amount, 1)
  }
  var low = 0, high = 1
  for (var i = 0; i < 20; i++) {
    var middle = (low + high) / 2
    if (contrast(mix(middle), paper) >= minimum) high = middle
    else low = middle
  }
  return mix(high)
}
