import QtQuick
import QtQuick.Controls as Controls

// One vocabulary for both faces: direct choices in Settings, a quiet stepper in
// the Book's margin. The owner persists the choice and supplies the saved value.
Item {
  id: selector
  required property var theme
  property real value: 1
  property string targetName: "Book"
  property bool compact: false
  property bool busy: false
  readonly property var values: [1, 1.25, 1.5, 1.75, 2]
  readonly property int index: values.indexOf(value)
  implicitWidth: compact ? compactRow.implicitWidth : choices.implicitWidth
  implicitHeight: compact ? compactRow.implicitHeight : choices.implicitHeight
  signal scaleRequested(real value)

  function request(value) {
    if (!busy && values.indexOf(value) !== -1 && value !== selector.value) scaleRequested(value)
  }

  component ScaleButton: Controls.AbstractButton {
    id: button
    property bool selected: false
    property bool quiet: false
    property string hint: ""
    enabled: !selector.busy
    focusPolicy: Qt.StrongFocus
    // AbstractButton handles Space; Return/Enter need explicit activation on Qt 6.11.
    Keys.onReturnPressed: if (enabled) clicked()
    Keys.onEnterPressed: if (enabled) clicked()
    hoverEnabled: true
    leftPadding: Math.round(selector.theme.body * 0.4)
    rightPadding: leftPadding
    topPadding: Math.max(2, Math.round(selector.theme.body * 0.2))
    bottomPadding: topPadding
    implicitWidth: implicitContentWidth + leftPadding + rightPadding
    implicitHeight: implicitContentHeight + topPadding + bottomPadding
    Accessible.role: Accessible.Button
    Accessible.name: hint || text
    background: Rectangle {
      radius: selector.theme.radius
      color: button.down ? Qt.rgba(selector.theme.accent.r, selector.theme.accent.g, selector.theme.accent.b, 0.2)
        : button.selected || button.activeFocus || button.hovered ? Qt.rgba(selector.theme.text.r, selector.theme.text.g, selector.theme.text.b, 0.08) : "transparent"
      border.width: button.quiet && !button.activeFocus && !button.hovered ? 0 : 1
      border.color: button.selected || button.activeFocus ? selector.theme.accent : selector.theme.faint
    }
    contentItem: Text {
      text: button.text
      textFormat: Text.PlainText
      font.family: selector.theme.mono
      font.pixelSize: selector.theme.small
      color: !button.enabled ? selector.theme.dim : button.activeFocus || button.hovered ? selector.theme.accent
        : button.quiet ? selector.theme.dim : selector.theme.text
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }
    HoverHandler { cursorShape: button.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    Controls.ToolTip.visible: hovered && hint !== ""
    Controls.ToolTip.text: hint
    Controls.ToolTip.delay: 650
  }

  Flow {
    id: choices
    visible: !selector.compact
    width: selector.width
    spacing: selector.theme.body * 0.3
    Repeater {
      model: selector.values
      delegate: ScaleButton {
        required property real modelData
        objectName: "appScale_" + String(modelData)
        width: Math.max(implicitWidth, (choices.width - choices.spacing * 4) / 5)
        text: String(modelData) + "×"
        selected: selector.value === modelData
        Accessible.role: Accessible.RadioButton
        Accessible.name: selector.targetName + " scale " + String(modelData) + " times"
        Accessible.checkable: true
        Accessible.checked: selected
        onClicked: selector.request(modelData)
      }
    }
  }

  Row {
    id: compactRow
    visible: selector.compact
    spacing: selector.theme.body * 0.3
    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: "Scale"
      textFormat: Text.PlainText
      color: selector.theme.dim
      font.family: selector.theme.mono
      font.pixelSize: selector.theme.small
    }
    ScaleButton {
      objectName: "bookScaleDecrease"
      text: "−"
      quiet: true
      enabled: !selector.busy && selector.index > 0
      hint: "Smaller " + selector.targetName
      onClicked: selector.request(selector.values[selector.index - 1])
    }
    ScaleButton {
      objectName: "bookScaleReset"
      text: String(selector.value) + "×"
      quiet: true
      implicitWidth: widestValue.width + leftPadding + rightPadding
      hint: selector.targetName + " scale · reset to 1×"
      onClicked: selector.request(1)
      TextMetrics { id: widestValue; font.family: selector.theme.mono; font.pixelSize: selector.theme.small; text: "1.75×" }
    }
    ScaleButton {
      objectName: "bookScaleIncrease"
      text: "+"
      quiet: true
      enabled: !selector.busy && selector.index >= 0 && selector.index < selector.values.length - 1
      hint: "Larger " + selector.targetName
      onClicked: selector.request(selector.values[selector.index + 1])
    }
  }
}
