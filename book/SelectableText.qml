import QtQuick
import QtQuick.Controls as Controls

// Text-like sizing and formatting, backed by a read-only editor. Plain content
// stays plain; the Book's already-sanitized rich text keeps its styling.
Item {
  id: passage
  objectName: "selectablePassage"
  required property var theme
  property BookTextSelection selectionController: null
  property string text: ""
  property int textFormat: Text.PlainText
  property int wrapMode: Text.NoWrap
  property real lineHeight: 1
  // Older Book themes have only accent/text; native selection roles are optional.
  readonly property color selectionBackground: theme.selection !== undefined ? theme.selection
    : Qt.tint(theme.background, Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.35))
  readonly property color selectionForeground: theme.selectedText !== undefined ? theme.selectedText : theme.text
  property alias font: editor.font
  property alias color: editor.color
  property alias horizontalAlignment: editor.horizontalAlignment
  readonly property alias selectedText: editor.selectedText
  readonly property alias selectionStart: editor.selectionStart
  readonly property alias selectionEnd: editor.selectionEnd
  readonly property alias length: editor.length
  readonly property rect endRectangle: editor.positionToRectangle(editor.length)
  readonly property bool selecting: selectionMouse.pressed && (selectionMouse.pressedButtons & Qt.LeftButton) !== 0
  readonly property bool menuOpen: copyMenu.opened
  property string renderedSource: ""
  property int renderedFormat: TextEdit.PlainText
  implicitWidth: editor.implicitWidth
  implicitHeight: editor.contentHeight

  function escaped(value) {
    return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  }

  function refresh() {
    if (!editor || !copyMenu || selecting || editor.selectedText !== "" || copyMenu.opened) return
    var rich = textFormat !== Text.PlainText || lineHeight !== 1
    var content = textFormat === Text.PlainText && rich ? escaped(text).replace(/\n/g, "<br>") : text
    if (rich && lineHeight !== 1) {
      var style = "line-height:" + (metrics.height * lineHeight) + "px"
      content = textFormat === Text.PlainText ? "<p style=\"margin:0;" + style + "\">" + content + "</p>"
        : content.replace(/<p>/g, "<p style=\"" + style + "\">")
    }
    var format = rich ? TextEdit.RichText : TextEdit.PlainText
    // Compare the source we applied, not QTextDocument's HTML serialization.
    // Reapplying identical rich text while a click clears a selection resets the
    // document/cursor and makes selection jump on the native Qt renderer.
    if (renderedSource !== content || renderedFormat !== format) {
      renderedSource = content
      renderedFormat = format
      editor.textFormat = format
      editor.text = content
    }
  }

  function showCopyMenu(x, y) {
    editor.forceActiveFocus()
    var point = editor.mapToItem(copyMenu.parent, x, y)
    copyMenu.popup(point.x, point.y)
  }

  function select(start, end) { editor.select(start, end) }
  function selectAll() { editor.forceActiveFocus(); editor.selectAll() }
  function deselect() { copyMenu.close(); editor.deselect(); refresh() }

  function copy() {
    if (editor.selectedText === "") return
    // Qt puts table boundary markers around the illuminated initial. They are
    // layout, not prose: copying "Marrow" must not turn it into "M\n\narrow".
    var plain = editor.selectedText
    if (textFormat !== Text.PlainText && /<table\b/i.test(text)) plain = plain.replace(/\ufdd1\u2029?/g, "")
    plain = plain.replace(/[\ufdd0\ufdd1]/g, "").replace(/[\u2028\u2029]/g, "\n")
    clipboard.text = plain
    clipboard.selectAll()
    clipboard.copy()
    clipboard.clear()
  }

  function copyPassage() {
    var start = editor.selectionStart, end = editor.selectionEnd
    editor.selectAll()
    copy()
    editor.select(start, end)
  }

  onTextChanged: refresh()
  onTextFormatChanged: refresh()
  onLineHeightChanged: refresh()
  onSelectingChanged: {
    if (selectionController) selectionController.hold(passage, selecting)
    if (!selecting) refresh()
  }
  onVisibleChanged: if (!visible && selectionController) { selectionController.release(passage); deselect() }
  Component.onCompleted: refresh()

  FontMetrics { id: metrics; font: editor.font; onHeightChanged: passage.refresh() }

  TextEdit {
    id: editor
    objectName: "selectableEditor"
    width: passage.width
    height: contentHeight
    padding: 0
    color: passage.theme.text
    font.family: passage.theme.serif
    font.pixelSize: passage.theme.prose
    wrapMode: passage.wrapMode === Text.NoWrap ? TextEdit.NoWrap : TextEdit.Wrap
    readOnly: true
    // One MouseArea below owns pointer selection, rather than competing with
    // TextEdit's grab handlers and the surrounding Flickable.
    selectByMouse: false
    selectByKeyboard: true
    persistentSelection: true
    cursorVisible: false
    selectionColor: passage.selectionBackground
    selectedTextColor: passage.selectionForeground
    onActiveFocusChanged: if (activeFocus && passage.selectionController) passage.selectionController.claim(passage)
    onSelectedTextChanged: {
      if (selectedText !== "" && passage.selectionController) passage.selectionController.claim(passage)
      if (selectedText === "") passage.refresh()
    }
    Keys.onPressed: event => {
      if (event.matches(StandardKey.Copy) || (event.key === Qt.Key_C && (event.modifiers & (Qt.ControlModifier | Qt.MetaModifier)) && !(event.modifiers & Qt.AltModifier))) {
        passage.copy()
        event.accepted = true
      } else if (event.key === Qt.Key_Escape) {
        passage.deselect()
        event.accepted = true
      }
    }
  }

  // Native mouse events reliably reach this area (unlike passive handlers on
  // TextEdit in Quickshell). Keep the grab for vertical drags too, without
  // toggling Flickable.interactive mid-gesture. Wheel/touch scrolling stays native.
  MouseArea {
    id: selectionMouse
    parent: editor
    anchors.fill: parent
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    preventStealing: true
    cursorShape: Qt.IBeamCursor
    property int anchor: 0
    property bool words: false

    onPressed: mouse => {
      // Let synthesized touch presses reach the Flickable instead of turning a
      // finger swipe into a mouse selection with an unstealable grab.
      if (mouse.source === Qt.MouseEventSynthesizedByQt) { mouse.accepted = false; return }
      editor.forceActiveFocus()
      if (mouse.button !== Qt.LeftButton) return
      words = false
      var position = editor.positionAt(mouse.x, mouse.y)
      if (mouse.modifiers & Qt.ShiftModifier) {
        anchor = editor.cursorPosition === editor.selectionStart ? editor.selectionEnd : editor.selectionStart
      } else anchor = position
      editor.select(anchor, position)
    }
    onPositionChanged: mouse => {
      if (!(pressedButtons & Qt.LeftButton)) return
      var position = editor.positionAt(mouse.x, mouse.y)
      if (words) editor.moveCursorSelection(position, TextEdit.SelectWords)
      else editor.select(anchor, position)
    }
    onDoubleClicked: mouse => {
      if (mouse.button !== Qt.LeftButton) return
      editor.cursorPosition = editor.positionAt(mouse.x, mouse.y)
      editor.selectWord()
      anchor = editor.selectionStart
      words = true
    }
    onClicked: mouse => {
      if (mouse.button === Qt.RightButton) passage.showCopyMenu(mouse.x, mouse.y)
    }
  }

  Shortcut {
    sequences: [StandardKey.Copy, "Ctrl+Shift+C", "Meta+C", "Ctrl+Meta+C"]
    context: Qt.WindowShortcut
    enabled: passage.selectedText !== "" && editor.activeFocus && !copyMenu.opened
    onActivated: { passage.copy(); copyMenu.close() }
  }

  Controls.Menu {
    id: copyMenu
    objectName: "passageCopyMenu"
    // Keep the menu in the window overlay, outside the clipped story list and
    // effects layer; do not depend on native popup-window support in Quickshell.
    parent: Controls.Overlay.overlay
    popupType: Controls.Popup.Item
    focus: true
    // The custom background has no implicit size. Without this the default
    // menu style can collapse its items to zero width (a seemingly dead click).
    implicitWidth: Math.max(180, copyAction.implicitWidth, selectAction.implicitWidth) + leftPadding + rightPadding
    font.family: passage.theme.mono
    font.pixelSize: passage.theme.small
    palette.window: passage.theme.surface
    palette.windowText: passage.theme.text
    palette.text: passage.theme.text
    palette.highlight: passage.selectionBackground
    palette.highlightedText: passage.selectionForeground
    background: Rectangle {
      color: passage.theme.surface
      radius: passage.theme.radius
      border.width: 1
      border.color: passage.theme.faint
    }
    Controls.MenuItem {
      id: copyAction
      objectName: "copyPassageAction"
      text: "Copy"
      enabled: passage.length > 0
      onTriggered: passage.selectedText !== "" ? passage.copy() : passage.copyPassage()
      // A modal popup suppresses shortcuts from the passage underneath it.
      // Register these inside the menu's own visual/focus scope as well.
      Shortcut {
        sequences: [StandardKey.Copy, "Ctrl+Shift+C", "Meta+C", "Ctrl+Meta+C"]
        context: Qt.WindowShortcut
        enabled: copyMenu.opened && passage.length > 0
        onActivated: {
          passage.selectedText !== "" ? passage.copy() : passage.copyPassage()
          copyMenu.close()
        }
      }
    }
    Controls.MenuItem {
      id: selectAction
      objectName: "selectPassageAction"
      text: "Select passage"
      onTriggered: passage.selectAll()
    }
    onClosed: refreshAfterMenu.restart()
  }

  Timer { id: refreshAfterMenu; interval: 0; onTriggered: passage.refresh() }

  // A plain-text clipboard payload, never markup or decorative table markers.
  TextEdit { id: clipboard; visible: false; textFormat: TextEdit.PlainText }
}
