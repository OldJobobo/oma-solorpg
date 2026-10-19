import QtQuick
import qs.Commons
import qs.Ui
import "book/Ink.js" as Ink

// The shell owns the styling; the Book stays plain QtQuick and receives this
// vocabulary plus a native surface factory. All bindings follow theme changes.
QtObject {
  id: theme
  objectName: "soloTheme"

  property color background: Color.popups.background
  readonly property color paper: Ink.over(background, Color.background)
  property color text: Ink.readable(Color.popups.text, paper, Color.foreground)
  property color surface: Qt.tint(background, Qt.rgba(text.r, text.g, text.b, 0.05))
  readonly property color surfacePaper: Ink.over(surface, paper)
  property color dim: Ink.readable(Color.muted, surfacePaper, text)
  property color faint: Qt.rgba(text.r, text.g, text.b, 0.22)
  property color accent: Color.accent
  property color urgent: Color.urgent
  // Separate readable text from effect/border colors, which stay unchanged.
  readonly property color urgentText: Ink.readable(urgent, surfacePaper, text)
  readonly property color accentText: Ink.readable(accent, surfacePaper, text)
  readonly property color placeholder: dim
  property color gold: "#d9a441"
  property string mono: Style.font.family
  property string serif: "serif"
  property real small: Style.font.bodySmall
  property real body: Style.font.body
  property real prose: Math.round(Style.font.body * 1.5)
  property real title: Style.font.title
  property real heading: Math.round(Style.font.heading * 1.2)
  property real display: Style.font.display
  property real radius: Style.cornerRadius

  readonly property real controlPaddingX: Style.spacing.controlPaddingX
  readonly property real controlPaddingY: Style.spacing.controlPaddingY
  readonly property real inputPaddingY: Style.spacing.inputPaddingY
  readonly property real controlGap: Style.spacing.controlGap
  // Reserve every state's border so focus/hover never shift the text.
  readonly property real controlInset: Math.max.apply(null, ["normal", "hover-cursor", "focus", "selected"].map(function(state) {
    var spec = Border.controlSpec(state, theme.text, theme.accent)
    return Math.max(Border.top(spec), Border.right(spec), Border.bottom(spec), Border.left(spec))
  }))
  readonly property color selection: Style.selectionFillFor(text, accent)
  readonly property color selectedText: Ink.readable(text, Ink.over(selection, Ink.over(controlFill("focus"), surfacePaper)), text)

  function controlFill(state) {
    if (state === "disabled") return Qt.rgba(0, 0, 0, 0)
    if (state === "pressed") return Style.pressedFillFor(text, accent)
    if (state === "focus") return Style.focusFillFor(text, accent)
    if (state === "hover-cursor") return Style.hoverFillFor(text, accent)
    if (state === "selected") return Style.selectedFillFor(text, accent)
    return Style.normalFillFor(text, accent)
  }

  function inputText(ink, state) {
    return Ink.readable(ink, Ink.over(controlFill(state), surfacePaper), text)
  }

  function controlText(state) {
    var ink = state === "disabled" ? dim
      : state === "pressed" ? Style.pressedStateColor(text, accent)
      : state === "focus" ? Style.focusStateColor(text, accent)
      : state === "hover-cursor" ? Style.hoverStateColor(text, accent)
      : state === "selected" ? Style.selectedStateColor(text, accent)
      : Style.normalStateColor(text, accent)
    return inputText(ink, state)
  }

  readonly property Component controlSurface: Component {
    BorderSurface {
      property string controlState: "normal"
      property bool framed: true
      property color baseColor: "transparent"
      color: controlState === "normal" && !framed ? baseColor : Qt.tint(baseColor, theme.controlFill(controlState))
      borderSpec: controlState === "disabled" || (!framed && controlState === "normal") ? Border.none()
        : Border.controlSpec(controlState === "pressed" ? "hover-cursor" : controlState, theme.text, theme.accent)
      radius: theme.radius
    }
  }
}
