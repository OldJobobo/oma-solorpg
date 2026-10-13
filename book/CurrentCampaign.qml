import QtQuick
import Quickshell
import Quickshell.Io

// Which campaign is current, as `solo new`, `solo use` and `solo play` record it in
// $XDG_STATE_HOME/solo/current: the Table and the d20 both follow it. Unlike the rest of
// this folder it needs the shell.
//
// Quickshell watches a file by way of its folder, and that folder is made by the very
// first game: a watch set before it existed never fires, and every reload sets the watch
// again. So while there is nothing to read, it is read again every few seconds; once there
// is, the watch holds.
FileView {
  id: current
  property string campaign: ""

  path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/solo/current"
  watchChanges: true
  printErrors: false
  onFileChanged: reload()
  onLoaded: current.campaign = text().trim()
  onLoadFailed: current.campaign = ""

  property Timer retry: Timer {
    interval: 3000
    repeat: true
    running: current.campaign === ""
    onTriggered: current.reload()
  }
}
