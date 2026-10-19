import QtQuick

// The hero's progress tracks (vows, journeys, fights, bonds) as lines of text, a cell to a box:
// the box fills as its four ticks are marked, ░ ▂ ▄ ▆ █.
//   Silence the bell · dangerous vow
//   ████▄░░░░░  4 of 10
Column {
  id: tracks
  property var theme
  property var progress: ({})     // game.progress: {id: {name, kind, rank, ticks, ended}}
  property var spec: null         // game.labels.progress: boxes, ticks

  readonly property var open: spec ? Object.keys(progress).filter(id => !progress[id].ended) : []
  readonly property var levels: ["░", "▂", "▄", "▆", "█"]

  function boxes(ticks) {
    var out = ""
    for (var box = 0; box < spec.boxes; box++)
      out += levels[Math.max(0, Math.min(spec.ticks, ticks - box * spec.ticks))]
    return out
  }

  visible: open.length > 0
  spacing: theme.body * 0.5

  Repeater {
    model: tracks.open
    delegate: Column {
      required property string modelData
      readonly property var track: tracks.progress[modelData]
      width: tracks.width
      Text {
        objectName: "progressTitle"
        width: parent.width
        wrapMode: Text.Wrap
        textFormat: Text.PlainText
        font.family: tracks.theme.mono
        font.pixelSize: tracks.theme.small
        color: tracks.theme.text
        text: track.name + (track.rank ? " · " + track.rank + " " + track.kind : "")
      }
      Text {
        textFormat: Text.PlainText
        font.family: tracks.theme.mono
        font.pixelSize: tracks.theme.small
        color: tracks.theme.accent
        text: tracks.boxes(track.ticks) + "  " + Math.floor(track.ticks / tracks.spec.ticks) + " of " + tracks.spec.boxes
      }
    }
  }
}
