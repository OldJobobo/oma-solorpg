import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "book"

// Player-owned interface preferences, on the reverse of the existing Table.
// Both faces inherit Table zoom; Book zoom never resizes this sidebar.
FocusScope {
  id: settings
  objectName: "tableSettings"
  required property var theme
  property real bookScale: 1
  property real tableScale: 1
  property bool honorHyprland: false
  property string hyprlandError: ""
  property bool scaleBusy: false
  property string scaleTarget: ""
  property string scaleError: ""
  property string pace: "normal"
  property var effects: ({})
  property bool bookSupported: true
  property bool busy: false
  property string errorPlace: ""
  property string errorText: ""
  signal dismissed()
  signal scaleRequested(string target, real value)
  signal honorHyprlandRequested(bool on)
  signal paceRequested(string pace)
  signal effectRequested(string effect, bool on)

  Keys.onEscapePressed: dismissed()
  function focusReturn() { returnButton.forceActiveFocus() }

  component Label: Text {
    Layout.fillWidth: true
    Layout.minimumWidth: 0
    textFormat: Text.PlainText
    wrapMode: Text.Wrap
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    color: settings.theme.text
  }
  component Caption: Label { font.pixelSize: Style.font.caption; color: settings.theme.dim }
  component Heading: Caption {
    Layout.topMargin: Style.space(18)
    font.capitalization: Font.AllUppercase
    font.letterSpacing: 1
  }
  component Choice: Button {
    focusable: true
    foreground: settings.theme.text
    bordered: true
    fontSize: Style.font.bodySmall
    horizontalPadding: Style.space(10)
    verticalPadding: Style.space(6)
    enabled: !settings.busy
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.onPressAction: if (enabled) clicked()
  }
  component Effect: Item {
    id: effect
    required property string label
    required property string description
    property bool checked: false
    signal toggled()
    Layout.fillWidth: true
    implicitHeight: Math.max(words.implicitHeight, Style.space(28)) + Style.space(16)
    activeFocusOnTab: true
    enabled: !settings.busy
    Accessible.role: Accessible.CheckBox
    Accessible.name: label
    Accessible.description: description
    Accessible.checkable: true
    Accessible.checked: checked
    Accessible.onToggleAction: if (enabled) toggled()
    Keys.onSpacePressed: toggled()
    Keys.onReturnPressed: toggled()
    Rectangle {
      anchors.fill: parent
      color: effect.activeFocus || mouse.containsMouse ? settings.theme.faint : "transparent"
      radius: settings.theme.radius
    }
    MouseArea {
      id: mouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: { effect.forceActiveFocus(); effect.toggled() }
    }
    RowLayout {
      anchors { fill: parent; margins: Style.space(6) }
      spacing: Style.space(12)
      opacity: effect.enabled ? 1 : 0.6
      ColumnLayout {
        id: words
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: Style.space(3)
        Label { text: effect.label }
        Caption { text: effect.description }
      }
      Rectangle {
        implicitWidth: Style.space(44)
        implicitHeight: Style.space(24)
        radius: height / 2
        color: settings.theme.faint
        border.width: 1
        border.color: effect.checked ? settings.theme.accent : settings.theme.dim
        Rectangle {
          width: Style.space(18)
          height: width
          radius: width / 2
          x: effect.checked ? parent.width - width - Style.space(3) : Style.space(3)
          anchors.verticalCenter: parent.verticalCenter
          color: effect.checked ? settings.theme.accent : settings.theme.dim
          Text {
            anchors.centerIn: parent
            textFormat: Text.PlainText
            text: effect.checked ? "✓" : "−"
            font.family: Style.font.family
            font.pixelSize: Style.font.caption * 0.8
            color: settings.theme.background
          }
        }
      }
    }
  }

  RowLayout {
    id: header
    objectName: "settingsHeader"
    anchors { left: parent.left; right: parent.right; top: parent.top }
    spacing: Style.space(8)
    Label { text: "Settings"; font.pixelSize: Style.font.heading; font.bold: true }
    Choice {
      id: returnButton
      objectName: "settingsCloseButton"
      Layout.minimumWidth: Math.max(implicitWidth, Style.space(32))
      Layout.minimumHeight: Math.max(implicitHeight, Style.space(32))
      text: "×"
      fontSize: Style.font.title
      horizontalPadding: Style.space(6)
      enabled: true
      Accessible.name: "Close settings and return to the Table"
      tooltipText: "Back to the Table (Esc)"
      onClicked: settings.dismissed()
    }
  }
  Flickable {
    id: scroll
    objectName: "settingsScroll"
    anchors { left: parent.left; right: parent.right; top: header.bottom; bottom: parent.bottom; topMargin: Style.space(12) }
    contentHeight: column.implicitHeight
    boundsBehavior: Flickable.StopAtBounds
    clip: true
    ColumnLayout {
      id: column
      width: scroll.width
      spacing: Style.space(6)
      Heading { text: "Appearance"; Layout.topMargin: 0 }
      Caption { text: "Independent scales · saved for all campaigns" }
      Label { text: "Book scale" }
      ScaleSelector {
        objectName: "settingsBookScale"
        Layout.fillWidth: true
        theme: settings.theme
        targetName: "Book"
        value: settings.bookScale
        busy: settings.scaleBusy
        onScaleRequested: value => settings.scaleRequested("book", value)
      }
      Caption { text: "The story window only. Also adjustable in the Book sidebar." }
      Label { text: "Table & settings scale"; Layout.topMargin: Style.space(8) }
      ScaleSelector {
        objectName: "settingsTableScale"
        Layout.fillWidth: true
        theme: settings.theme
        targetName: "Table and settings"
        value: settings.tableScale
        busy: settings.scaleBusy
        onScaleRequested: value => settings.scaleRequested("table", value)
      }
      Caption { text: "Both sides of this sidebar. Does not change the Book or desktop." }
      Caption { visible: settings.scaleBusy; text: settings.scaleTarget === "hyprland" ? "Saving appearance…" : "Saving " + (settings.scaleTarget === "book" ? "Book" : "Table") + " scale…" }
      Label { visible: settings.scaleError !== ""; text: settings.scaleError; color: settings.theme.urgent }

      Effect {
        objectName: "settingsHonorHyprland"
        label: "Honor Hyprland settings"
        description: "Use the desktop's resolved gaps, corners, border and shadow for the Table and Settings. The Book already follows Hyprland."
        checked: settings.honorHyprland
        enabled: !settings.scaleBusy
        onToggled: settings.honorHyprlandRequested(!checked)
      }
      Caption { visible: settings.hyprlandError !== ""; text: settings.hyprlandError }

      Heading { text: "Game master" }
      Caption { text: "All campaigns" }
      Label { text: "GM pace" }
      Flow {
        id: paces
        Layout.fillWidth: true
        spacing: Style.space(4)
        Repeater {
          model: [["quick", "Quick"], ["normal", "Normal"], ["careful", "Careful"]]
          delegate: Choice {
            required property var modelData
            objectName: "settingsPace_" + modelData[0]
            width: Math.max(implicitWidth, (paces.width - paces.spacing * 2) / 3)
            text: modelData[1]
            selected: settings.pace === modelData[0]
            enabled: !settings.busy && settings.bookSupported
            Accessible.role: Accessible.RadioButton
            Accessible.checkable: true
            Accessible.checked: selected
            Accessible.name: "GM pace: " + modelData[1]
            onClicked: settings.paceRequested(modelData[0])
          }
        }
      }
      Caption {
        text: !settings.bookSupported ? "Your GM runs in a terminal and keeps its own pace."
          : settings.pace === "quick" ? "Answers sooner and uses fewer tokens."
          : settings.pace === "careful" ? "Thinks longer about the rules. Slower, and uses more tokens."
          : "Balances thinking time with a steady pace of play."
      }
      Label { visible: settings.errorPlace === "pace" && settings.errorText !== ""; text: settings.errorText; color: settings.theme.urgent }

      Heading { text: "Atmosphere" }
      Caption { text: "All campaigns · switches save immediately" }
      ColumnLayout {
        Layout.fillWidth: true
        spacing: 0
        Repeater {
          model: [
            ["sound", "Sound", "Dice, bells and drums, in time with the Book."],
            ["borders", "Window border effects", "Gold for a Dragon, red for a Demon or a dying hero."],
            ["screen", "Screen effects", "Flashes, jolts and colour changes as the story unfolds."],
            ["candle", "Candlelight", "Warms the screen while the Book is open. Off by default."],
            ["omens", "Omen notifications", "Brings news from the world's hidden clocks."],
            ["screensaver", "Hero screensaver", "Shows your hero while the Book is open."]
          ]
          delegate: Effect {
            required property var modelData
            objectName: "settingsEffect_" + modelData[0]
            label: modelData[1]
            description: modelData[2]
            checked: settings.effects[modelData[0]] !== false
            onToggled: settings.effectRequested(modelData[0], !checked)
          }
        }
      }
      Label { visible: settings.errorPlace === "effects" && settings.errorText !== ""; text: settings.errorText; color: settings.theme.urgent }
      Item { Layout.preferredHeight: Style.space(12) }
    }
  }
}
