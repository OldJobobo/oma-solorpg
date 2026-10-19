import QtQuick

// The way the hero came, scene by scene. Unexplored ways on show as dashes that lead
// nowhere yet: the Book never names a place the hero hasn't reached.
Text {
  id: route
  property var theme
  property var steps: []

  textFormat: Text.StyledText
  font.family: theme.mono
  font.pixelSize: theme.small
  lineHeight: 1.15
  color: theme.dim
  wrapMode: Text.NoWrap
  text: steps.map(function(step, i) {
    var mark = step.here ? "<span style=\"color:" + theme.accentText + "\">◉</span>" : "○"
    var name = step.here ? "<span style=\"color:" + theme.text + "\">" + route.html(step.title) + "</span>" : route.html(step.title)
    var ways = step.unexplored > 0 ? " <span style=\"color:" + theme.faint + "\">" + "╌".repeat(2) + " " + step.unexplored + "?</span>" : ""
    return (i > 0 ? "│<br>" : "") + mark + " " + name + ways
  }).join("<br>")

  function html(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }
}
