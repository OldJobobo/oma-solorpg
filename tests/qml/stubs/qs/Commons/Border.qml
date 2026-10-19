pragma Singleton
import QtQuick

// Border specs are inspected by tests; rendering the shell's Shape rings belongs
// to Omarchy. Keep the same spec shape, including gradients and per-side widths.
QtObject {
  property var popupWidths: ({ top: 2, right: 2, bottom: 2, left: 2 })
  property var popupGradient: ({ colors: ["#78824b", "#3c4125"], angle: 35, enabled: true })
  function flat(color, width) {
    return { color: color, widths: { top: width, right: width, bottom: width, left: width },
      gradient: { colors: [], angle: 0, enabled: false } }
  }
  function none() { return flat("transparent", 0) }
  function surfaceSpec(section, token, color, width) {
    return { color: color, widths: popupWidths, gradient: popupGradient }
  }
  function controlSpec(state, foreground, accent) {
    var spec = flat(accent, state === "selected" ? 0 : 1)
    spec.gradient = popupGradient
    return spec
  }
  function top(spec) { return spec.widths.top }
  function right(spec) { return spec.widths.right }
  function bottom(spec) { return spec.widths.bottom }
  function left(spec) { return spec.widths.left }
}
