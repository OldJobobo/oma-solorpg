import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import QtQuick.Controls as Controls
import "Md.js" as Md

// The Book: where the story is read and told. The GM's narration streams in as it is
// written, every roll stops the page for a moment, scenes open with their name, and the
// hero's face on the left follows what happens to them. The player writes at the bottom.
//
// Plain QtQuick on purpose: the window around it (BookWindow.qml) brings the shell, and
// tests/qml renders this view offscreen against real engine state.
Item {
  id: book
  property var theme
  property real bookScale: 1
  property bool scaleBusy: false
  property string scaleError: ""
  property var game: null          // state.json
  property var turn: ({ status: "idle" })   // .solo/turn.json
  property var agent: ({ agent: "", book: true })
  property string campaign: ""     // the campaign's folder: another one starts the Book over
  property string actionError: ""  // why the last thing clicked here (light a torch) was refused
  property bool active: true       // the window is showing
  property bool codexOpen: false
  property bool combatExpanded: false
  property bool epitaphDismissed: false
  property bool cutting: false     // the X-card panel is open
  property int seen: -1            // the newest story seq already shown (no replays on load)
  readonly property bool epitaphShown: dead && !epitaphDismissed

  signal scaleRequested(real value)
  signal send(string text)
  signal stop()
  signal retry()
  signal act(var args)             // an engine command for the table: ["light", "torch"]
  signal cut(string note, string line, string veil)   // the X-card: cut the GM's last message, and maybe add a line or a veil
  signal openTable()
  signal openTerminal()
  signal diceLanded(int seq, string campaignAtThrow)

  BookTextSelection { id: textSelection; objectName: "bookTextSelection" }

  component Passage: SelectableText {
    objectName: "bookPassage"
    theme: book.theme
    selectionController: textSelection
  }

  // Blur, glow and particles need the GPU. Qt Quick's software renderer can't draw them,
  // and would draw nothing where they are: without it every effect steps aside.
  readonly property bool gpu: GraphicsInfo.api !== GraphicsInfo.Software
  readonly property var pc: game ? game.pc : null
  readonly property var story: game && game.story ? game.story : []
  readonly property bool busy: turn && (turn.status === "thinking" || turn.status === "writing")
  readonly property bool dead: pc !== null && pc.dead === true
  // There is a GM message to cut, and the GM isn't in the middle of writing another.
  readonly property bool canCut: !busy && !dead && agent.book !== false && story.some(b => b.kind === "gm")
  readonly property bool carriesLight: pc !== null && pc.items.some(i => /(^|\s)torch(es)?$/i.test(i))
  // The story column's width: a line of about 75 characters, however wide the window.
  readonly property real measure: theme.prose * 38
  // Writing fields get a little more room than buttons: the serif text is larger.
  readonly property real fieldPaddingX: Math.round(theme.controlPaddingX * 1.5) + theme.controlInset
  readonly property real fieldPaddingY: Math.round(theme.inputPaddingY * 1.3) + theme.controlInset
  // How far a Link's label sits inside its own hover fill, so rows of links can line up with text.
  readonly property real linkInsetX: theme.controlPaddingX / 2 + theme.controlInset
  readonly property real linkInsetY: theme.controlPaddingY / 2 + theme.controlInset

  onGameChanged: react()
  onActiveChanged: if (active && game) titleCard.show(game.scene_title, game.title)
  // Another campaign's story is numbered from its own start: what this one had seen means
  // nothing there, and would hold back its dice and scene cards until it caught up.
  onCampaignChanged: {
    textSelection.clear()
    seen = -1
    epitaphDismissed = false
    codexOpen = false
    combatExpanded = false
    cutting = false
    storyModel.clear()
    storyNewest = -1
  }
  // A new hero took up the story: the next death gets its gravestone too.
  onDeadChanged: if (!dead) epitaphDismissed = false

  // New story beats since the last look: a new scene gets its title card, a new roll its
  // moment. The first load only remembers where the story is. It reads game.story, not
  // the `story` binding, which hasn't caught up yet while gameChanged is being handled.
  function react() {
    if (!game) return
    var beats = game.story || []
    grow(beats)
    var newest = beats.length ? beats[beats.length - 1].seq : 0
    if (seen < 0) {
      seen = newest
      if (active) titleCard.show(game.scene_title, game.title)
      return
    }
    var fresh = beats.filter(b => b.seq > seen)
    seen = Math.max(seen, newest)
    var scene = fresh.filter(b => b.kind === "scene").pop()
    var roll = fresh.filter(b => b.kind === "roll" || b.kind === "voice").pop()
    var hurt = fresh.some(b => b.kind === "hurt" && (b.dealt || 0) > 0)
    if (scene) titleCard.show(scene.title, game.title)
    else if (roll && roll.kind === "roll") {
      // What the dice bring lands when they do (see dice.onSettled).
      dice.campaignAtThrow = book.campaign
      dice.show(roll)
      hurtOnLanding = hurt
      hurt = false
    }
    if (hurt) strike("hurt")
    else if (!dice.visible && roll && roll.outcome && (roll.outcome.dragon || roll.outcome.demon))
      strike(roll.outcome.dragon ? "dragon" : "demon")
    if (fresh.length) storyView.follow()
  }

  // A blow that came with a roll waits for the dice to land.
  property bool hurtOnLanding: false

  function strike(kind) {
    atmosphere.flash(kind)
    if (kind !== "dragon") shake.restart()
  }

  // The story on the page grows a beat at a time: a reload of state.json adds what is new
  // and leaves the rest alone, so the page is never rebuilt and nothing on it plays twice
  // (an omen fading in). Newest first, for a list that runs bottom to top.
  ListModel { id: storyModel }
  property int storyNewest: -1

  function grow(beats) {
    var newest = beats.length ? beats[beats.length - 1].seq : -1
    if (newest < storyNewest) {  // a story that doesn't carry on from this one: start over
      storyModel.clear()
      storyNewest = -1
    }
    for (var i = 0; i < beats.length; i++) {
      if (beats[i].seq > storyNewest) {
        storyModel.insert(0, { seq: beats[i].seq, json: JSON.stringify(beats[i]), opens: beats[i].kind === "gm" && opensScene(beats, i) })
      }
    }
    while (storyModel.count > beats.length) storyModel.remove(storyModel.count - 1)
    storyNewest = Math.max(storyNewest, newest)
  }

  // The GM's first words since the hero entered a scene (voices and rolls may come between).
  function opensScene(beats, index) {
    for (var i = index - 1; i >= 0; i--) {
      if (beats[i].kind === "scene") return true
      if (beats[i].kind === "gm" || beats[i].kind === "player") return false
    }
    return false
  }

  function elapsed(seconds) {
    var day = Math.floor(seconds / 86400) + 1
    var rest = seconds % 86400
    var pad = n => (n < 10 ? "0" : "") + n
    return "Day " + day + ", " + pad(Math.floor(rest / 3600)) + ":" + pad(Math.floor(rest % 3600 / 60))
  }

  Rectangle {
    anchors.fill: parent
    color: book.theme.background
  }

  // Quiet links at rest, native themed controls on hover, press and keyboard focus.
  component Link: Controls.AbstractButton {
    id: link
    property bool selected: false
    property real maximumWidth: Infinity
    readonly property string controlState: !enabled ? "disabled" : down ? "pressed"
      : activeFocus ? "focus" : hovered ? "hover-cursor" : selected ? "selected" : "normal"
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    implicitWidth: Math.min(maximumWidth, implicitContentWidth + leftPadding + rightPadding)
    implicitHeight: implicitContentHeight + topPadding + bottomPadding
    leftPadding: book.theme.controlPaddingX / 2 + book.theme.controlInset
    rightPadding: leftPadding
    topPadding: book.theme.controlPaddingY / 2 + book.theme.controlInset
    bottomPadding: topPadding
    background: ControlSurface {
      theme: book.theme
      framed: false
      controlState: link.controlState
    }
    contentItem: Text {
      text: link.text
      textFormat: Text.PlainText
      wrapMode: Text.Wrap
      font.family: book.theme.mono
      font.pixelSize: book.theme.small
      color: book.theme.controlText(link.controlState)
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }
    HoverHandler { cursorShape: link.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
  }

  // The page: the hero in the margin beside a column of text, centred in a wide window.
  // Behind a moment (a roll, a new scene, the gravestone) it goes soft; in a dark place with
  // nothing burning it dims; dying it loses its colour, and dead it is grey. A hit shakes it.
  Item {
    id: page
    anchors.fill: parent
    property real softness: book.gpu && (dice.visible || titleCard.visible || epitaphShown) ? 1 : 0
    property real saturation: !book.gpu ? 0 : book.dead ? -1 : book.pc && book.pc.dying ? -0.55 : 0
    property real brightness: book.gpu && book.game && book.game.dark && !book.game.light ? -0.18 : 0
    Behavior on softness { NumberAnimation { duration: 350; easing.type: Easing.OutQuad } }
    Behavior on saturation { NumberAnimation { duration: 2500; easing.type: Easing.InOutQuad } }
    Behavior on brightness { NumberAnimation { duration: 1800 } }
    layer.enabled: book.gpu && (softness > 0.001 || saturation < -0.001 || brightness < -0.001)
    layer.effect: MultiEffect {
      blurEnabled: page.softness > 0
      blur: page.softness * 0.55
      blurMax: 32
      saturation: page.saturation
      brightness: page.brightness
    }

    SequentialAnimation {
      id: shake
      NumberAnimation { target: page; property: "x"; to: -9; duration: 40 }
      NumberAnimation { target: page; property: "x"; to: 7; duration: 60 }
      NumberAnimation { target: page; property: "x"; to: -4; duration: 60 }
      NumberAnimation { target: page; property: "x"; to: 0; duration: 90 }
    }

    GridLayout {
      id: pageRow
      objectName: "bookPageLayout"
      anchors { top: parent.top; bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; margins: book.theme.body * 1.4 }
      width: Math.min(book.width - book.theme.body * 2.8, (sideFrame.visible ? sideFrame.Layout.preferredWidth + columnSpacing : 0) + book.measure)
      readonly property bool stacked: width < sideFrame.Layout.preferredWidth + book.theme.body * 29
      columns: stacked ? 1 : 2
      columnSpacing: book.theme.body * 2.4
      rowSpacing: book.theme.body * 0.8

      // The hero ------------------------------------------------------------------------

      ColumnLayout {
        id: sideFrame
        objectName: "bookSidebarFrame"
        visible: book.pc !== null
        Layout.fillHeight: !pageRow.stacked
        Layout.fillWidth: pageRow.stacked
        // Zooming a small Book stacks the independently scrolling hero above
        // the story. Keep the scale footer reachable instead of hiding it.
        Layout.preferredHeight: pageRow.stacked ? Math.max(scaleFooter.implicitHeight + book.theme.body * 2,
          Math.min(pageRow.height * 0.3, sideColumn.implicitHeight + scaleFooter.implicitHeight + spacing)) : -1
        Layout.minimumHeight: 0
        Layout.preferredWidth: Math.ceil(Math.max(heroPortrait.implicitWidth, vitals.implicitWidth, book.theme.small * 16, scaleFooter.implicitWidth))
        Layout.minimumWidth: pageRow.stacked ? 0 : Layout.preferredWidth
        Layout.maximumWidth: pageRow.stacked ? Infinity : Layout.preferredWidth
        spacing: book.theme.body * 0.7

        Flickable {
          id: side
          objectName: "bookSidebar"
          Layout.fillHeight: true
          Layout.fillWidth: true
          Layout.minimumHeight: 0
          Layout.minimumWidth: 0
          contentHeight: sideColumn.implicitHeight
          boundsBehavior: Flickable.StopAtBounds
          clip: true

          Column {
            id: sideColumn
            width: side.width
            spacing: book.theme.body * 0.7

            Portrait {
              id: heroPortrait
              visible: !pageRow.stacked
              theme: book.theme
              portrait: book.game ? book.game.portrait : null
              cell: book.theme.small
            }

            Text {
              textFormat: Text.PlainText
              font.family: book.theme.serif
              font.pixelSize: book.theme.heading
              color: book.theme.text
              width: parent.width
              wrapMode: Text.Wrap
              text: book.pc ? book.pc.name : ""
            }

            Text {
              textFormat: Text.PlainText
              font.family: book.theme.mono
              font.pixelSize: book.theme.small
              color: book.theme.dim
              width: parent.width
              wrapMode: Text.Wrap
              text: book.pc ? Object.keys(book.pc.info).map(k => book.pc.info[k]).join(" · ") : ""
            }

            Column {
              id: vitals
              objectName: "bookVitals"
              spacing: sideColumn.spacing

              Repeater {
                model: book.pc ? Object.keys(book.pc.tracks).filter(k => book.pc.tracks[k].min === undefined) : []
                delegate: Meter {
                  required property string modelData
                  theme: book.theme
                  label: modelData
                  value: book.pc.tracks[modelData].value
                  maximum: book.pc.tracks[modelData].max
                }
              }

              // Momentum runs below zero, so it has a bar of its own (Ironsworn).
              Momentum {
                visible: !!book.pc && !!book.pc.tracks.momentum && !!book.game.labels.momentum
                theme: book.theme
                track: book.pc && book.pc.tracks.momentum ? book.pc.tracks.momentum : ({ value: 0, max: 10 })
                spec: book.game && book.game.labels.momentum ? book.game.labels.momentum : ({ min: -6, max: 10 })
              }
            }

            Text {
              visible: text !== ""
              textFormat: Text.PlainText
              font.family: book.theme.mono
              font.pixelSize: book.theme.small
              color: book.theme.urgentText
              width: parent.width
              wrapMode: Text.Wrap
              text: book.pc ? (book.pc.dying ? "DYING · " + book.pc.dying.successes + " saved, " + book.pc.dying.failures + " lost\n" : "")
                + book.pc.conditions.join(" · ") : ""
            }

            Torch {
              theme: book.theme
              gpu: book.gpu
              light: book.game && book.game.light ? book.game.light : null
              dark: book.game ? book.game.dark === true : false
            }

            Link {
              visible: !!book.game && !book.game.light && book.carriesLight && !book.dead
              text: "→ light a torch"
              onClicked: book.act(["light", "torch"])
            }

            Text {
              visible: book.actionError !== ""
              width: side.width
              wrapMode: Text.Wrap
              textFormat: Text.PlainText
              font.family: book.theme.mono
              font.pixelSize: book.theme.small
              color: book.theme.urgentText
              text: book.actionError
            }

            Item { width: 1; height: book.theme.body * 0.4 }

            Text {
              visible: vows.visible
              textFormat: Text.PlainText
              font.family: book.theme.mono
              font.pixelSize: book.theme.small
              font.letterSpacing: 2
              color: book.theme.dim
              text: "VOWS AND ROADS"
            }

            Progress {
              id: vows
              width: side.width
              theme: book.theme
              progress: book.game && book.game.progress ? book.game.progress : ({})
              spec: book.game && book.game.labels ? book.game.labels.progress : null
            }

            Item { visible: vows.visible; width: 1; height: book.theme.body * 0.4 }

            Text {
              textFormat: Text.PlainText
              font.family: book.theme.mono
              font.pixelSize: book.theme.small
              font.letterSpacing: 2
              color: book.theme.dim
              text: "THE WAY HERE"
            }

            Route {
              width: side.width
              wrapMode: Text.Wrap
              theme: book.theme
              steps: book.game && book.game.route ? book.game.route : []
            }
          }
        }

        ColumnLayout {
          id: scaleFooter
          objectName: "bookScaleFooter"
          Layout.fillWidth: true
          spacing: book.theme.body * 0.3
          ScaleSelector {
            objectName: "bookScaleSelector"
            Layout.fillWidth: true
            theme: book.theme
            compact: true
            value: book.bookScale
            busy: book.scaleBusy
            onScaleRequested: value => book.scaleRequested(value)
          }
          Text {
            Layout.fillWidth: true
            visible: book.scaleError !== ""
            textFormat: Text.PlainText
            text: book.scaleError
            wrapMode: Text.Wrap
            color: book.theme.urgentText
            font.family: book.theme.mono
            font.pixelSize: book.theme.small
          }
        }
      }

      // The story ------------------------------------------------------------------------

      ColumnLayout {
        id: storyColumn
        objectName: "bookStory"
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumWidth: 0
        Layout.minimumHeight: 0
        spacing: book.theme.body * 0.8

        GridLayout {
          objectName: "bookHeader"
          Layout.fillWidth: true
          columns: storyColumn.width < book.theme.small * 50 ? 1 : 2
          columnSpacing: book.theme.controlGap
          rowSpacing: book.theme.controlGap

          Column {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Text {
              width: parent.width
              elide: Text.ElideRight
              textFormat: Text.PlainText
              font.family: book.theme.serif
              font.pixelSize: book.theme.display
              font.capitalization: Font.SmallCaps
              color: book.theme.text
              text: book.game ? book.game.scene_title || "" : "The Book"
            }
            Text {
              width: parent.width
              wrapMode: Text.Wrap
              textFormat: Text.PlainText
              font.family: book.theme.mono
              font.pixelSize: book.theme.small
              color: book.theme.dim
              text: book.game ? book.game.title + " · " + book.elapsed(book.game.time) : ""
            }
          }
          Flow {
            id: navigation
            objectName: "bookNavigation"
            Layout.alignment: Qt.AlignRight
            Layout.maximumWidth: storyColumn.width
            Layout.preferredWidth: codexLink.implicitWidth + tableLink.implicitWidth + terminalLink.implicitWidth + spacing * 2
            spacing: book.theme.controlGap
            Link { id: codexLink; objectName: "codexLink"; maximumWidth: parent.width; text: "codex"; selected: book.codexOpen; onClicked: book.codexOpen = !book.codexOpen }
            Link { id: tableLink; maximumWidth: parent.width; text: "table"; onClicked: book.openTable() }
            Link { id: terminalLink; maximumWidth: parent.width; text: "terminal"; onClicked: book.openTerminal() }
          }
        }

        Controls.AbstractButton {
          id: combatToggle
          objectName: "bookCombatToggle"
          visible: pageRow.stacked && !!book.game && !!book.game.combat
          text: (book.combatExpanded ? "Hide fight" : "Show fight") + " · Round " + (book.game && book.game.combat ? book.game.combat.round : 1)
          activeFocusOnTab: true
          contentItem: Text {
            textFormat: Text.PlainText
            text: combatToggle.text
            font.family: book.theme.mono
            font.pixelSize: book.theme.small
            color: combatToggle.activeFocus || combatToggle.hovered ? book.theme.accent : book.theme.dim
          }
          background: Rectangle {
            color: "transparent"
            border.width: combatToggle.activeFocus ? 1 : 0
            border.color: book.theme.accent
            radius: book.theme.radius
          }
          onClicked: book.combatExpanded = !book.combatExpanded
        }

        // A wrapped fight must not push writing or the scale control offscreen.
        // In a narrow Book it is available on demand; a wide Book keeps it open.
        Flickable {
          objectName: "bookCombatView"
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.minimumHeight: 0
          Layout.maximumHeight: Layout.preferredHeight
          Layout.preferredHeight: Math.min(battle.implicitHeight, Math.max(0,
            pageRow.height - (pageRow.stacked ? sideFrame.Layout.preferredHeight + pageRow.rowSpacing : 0)) * 0.4)
          visible: !!book.game && !!book.game.combat && (!pageRow.stacked || book.combatExpanded)
          contentHeight: battle.implicitHeight
          boundsBehavior: Flickable.StopAtBounds
          clip: true
          Tableau {
            id: battle
            width: parent.width
            theme: book.theme
            fight: book.game && book.game.combat ? book.game.combat : null
            figures: book.game && book.game.figures ? book.game.figures : ({ hero: [], foes: {} })
            hero: book.pc
          }
        }

        Item {
          Layout.fillWidth: true
          Layout.fillHeight: true
          Layout.minimumHeight: Math.min(book.theme.body * 3, pageRow.height * 0.05)

          ListView {
            id: storyView
            objectName: "bookStoryView"
            anchors.fill: parent
            clip: true
            spacing: 0
            boundsBehavior: Flickable.StopAtBounds
            // Newest at the bottom, like a page being written: the list runs bottom to top over
            // the story reversed, and the GM's words in progress sit below the last beat.
            verticalLayoutDirection: ListView.BottomToTop
            model: storyModel
            cacheBuffer: 4000
            delegate: StoryEntry {
              required property string json
              required property bool opens
              width: storyView.width - book.theme.body
              theme: book.theme
              selectionController: textSelection
              beat: JSON.parse(json)
              opensScene: opens
            }
            header: Column {
              width: storyView.width - book.theme.body
              onImplicitHeightChanged: storyView.follow()
              spacing: book.theme.body * 0.5
              topPadding: book.theme.body * 0.5

              // The player's words, while the GM is answering them.
              Passage {
                visible: book.busy && (book.turn.player || "") !== "" && !book.story.some(b => b.kind === "player" && b.text === book.turn.player)
                width: parent.width
                wrapMode: Text.Wrap
                textFormat: Text.PlainText
                font.family: book.theme.serif
                font.italic: true
                font.pixelSize: book.theme.prose * 0.95
                color: book.theme.dim
                text: book.turn.player || ""
              }

              // The GM writing: its words appear as they come, at a pace that reads like writing.
              Passage {
                id: live
                objectName: "livePassage"
                property int shown: 0
                readonly property string full: book.busy ? (book.turn.text || "") : ""
                visible: full !== ""
                width: parent.width
                textFormat: Text.RichText
                wrapMode: Text.Wrap
                color: book.theme.text
                font.family: book.theme.serif
                font.pixelSize: book.theme.prose
                lineHeight: 1.3
                text: Md.render(full.slice(0, shown), book.theme.mono, "")
                // The cursor is decoration, never part of the copied passage.
                Text {
                  visible: live.shown < live.full.length
                  x: live.endRectangle.x
                  y: live.endRectangle.y
                  textFormat: Text.PlainText
                  font: live.font
                  color: book.theme.accent
                  text: "▌"
                }
                onFullChanged: if (full.length < shown) shown = 0
                Timer {
                  interval: 16
                  repeat: true
                  running: live.shown < live.full.length
                  onTriggered: live.shown = Math.min(live.full.length, live.shown + Math.max(1, Math.ceil((live.full.length - live.shown) / 40)))
                }
              }

              Text {
                id: quill
                property int dots: 0
                visible: book.busy
                textFormat: Text.PlainText
                font.family: book.theme.mono
                font.pixelSize: book.theme.small
                color: book.theme.dim
                text: "✒ the GM is " + (book.turn.doing || "thinking") + ".".repeat(dots + 1)
                Timer { interval: 420; repeat: true; running: quill.visible; onTriggered: quill.dots = (quill.dots + 1) % 3 }
              }

              Row {
                visible: book.turn.status === "error" || book.turn.status === "stopped"
                spacing: book.theme.body
                Passage {
                  textFormat: Text.PlainText
                  font.family: book.theme.mono
                  font.pixelSize: book.theme.small
                  color: book.turn.status === "error" ? book.theme.urgentText : book.theme.dim
                  text: book.turn.status === "error" ? book.turn.error || "The GM ran into a problem." : "Stopped."
                }
                Link { text: "try again"; onClicked: book.retry() }
              }
            }

            // A new beat brings the page back down to it, unless the player has scrolled far up to reread.
            function follow() {
              if (textSelection.engaged) return
              if (atYEnd || Math.abs(contentY - originY - contentHeight + height) < book.theme.body * 30) followStory.restart()
            }
            Timer {
              id: followStory
              interval: 0
              onTriggered: if (!textSelection.engaged) storyView.positionViewAtBeginning()
            }
          }

          // A story taller than the page fades out under the heading instead of cutting a line in half.
          Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: book.theme.prose * 1.6
            visible: storyView.contentHeight > storyView.height
            gradient: Gradient {
              GradientStop { position: 0; color: book.theme.background }
              GradientStop { position: 1; color: Qt.rgba(book.theme.background.r, book.theme.background.g, book.theme.background.b, 0) }
            }
          }
        }

        // The X-card ------------------------------------------------------------------------
        // One tap cuts the GM's last message: it leaves the page, and the GM is told not to come
        // back to it. The same panel can make what was cut a line (never again) or a veil (only off screen).

        RowLayout {
          Layout.fillWidth: true
          visible: book.canCut && !book.cutting
          Item { Layout.fillWidth: true }
          Link {
            objectName: "cutLink"
            Layout.rightMargin: book.fieldPaddingX - book.linkInsetX
            text: "cut the GM's last message"
            onClicked: { book.cutting = true; cutInput.forceActiveFocus() }
          }
        }

        ControlSurface {
          id: cutPanel
          objectName: "cutPanel"
          theme: book.theme
          baseColor: book.theme.surface
          controlState: cutInput.activeFocus ? "focus" : cutHover.hovered ? "hover-cursor" : "normal"
          Layout.fillWidth: true
          visible: book.canCut && book.cutting
          implicitHeight: cutColumn.implicitHeight + book.fieldPaddingY * 2 - book.linkInsetY
          HoverHandler { id: cutHover }

          ColumnLayout {
            id: cutColumn
            anchors { left: parent.left; right: parent.right; top: parent.top }
            anchors.leftMargin: book.fieldPaddingX
            anchors.rightMargin: anchors.leftMargin
            anchors.topMargin: book.fieldPaddingY
            spacing: book.theme.controlGap

            Text {
              Layout.fillWidth: true
              wrapMode: Text.Wrap
              textFormat: Text.PlainText
              font.family: book.theme.serif
              font.pixelSize: book.theme.prose * 0.95
              color: book.theme.text
              text: "Cut the GM's last message? It leaves the page, and the GM is told not to come back to it. Say what to avoid, if you like."
            }

            // A hairline under the note, so it reads as a field rather than another sentence.
            Item {
              Layout.fillWidth: true
              Layout.topMargin: book.theme.controlGap / 2
              Layout.bottomMargin: book.theme.controlGap / 2
              implicitHeight: cutInput.implicitHeight + 4
              TextInput {
                id: cutInput
                objectName: "cutInput"
                anchors { left: parent.left; right: parent.right; top: parent.top }
                font.family: book.theme.serif
                font.pixelSize: book.theme.prose
                color: book.theme.text
                onActiveFocusChanged: if (activeFocus) textSelection.clear()
                selectionColor: book.theme.selection
                selectedTextColor: book.theme.selectedText
                selectByMouse: true
                clip: true
                Keys.onEscapePressed: book.cutting = false
                Keys.onReturnPressed: book.cutIt("")
                Text {
                  visible: cutInput.text === ""
                  textFormat: Text.PlainText
                  font: cutInput.font
                  objectName: "cutPlaceholder"
                  width: parent.width
                  elide: Text.ElideRight
                  color: book.theme.inputText(book.theme.placeholder, cutPanel.controlState)
                  text: "what to avoid (optional)"
                }
              }
              Rectangle {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 1
                color: cutInput.activeFocus ? book.theme.accent : book.theme.placeholder
                opacity: cutInput.activeFocus ? 0.8 : 0.45
              }
            }

            Flow {
              objectName: "cutActions"
              Layout.fillWidth: true
              Layout.leftMargin: -book.linkInsetX
              spacing: book.theme.controlGap
              Link { objectName: "cutNow"; maximumWidth: parent.width; text: "cut"; onClicked: book.cutIt("") }
              Link { objectName: "cutLine"; maximumWidth: parent.width; text: "cut, and never again"; enabled: cutInput.text.trim() !== ""; onClicked: book.cutIt("line") }
              Link { objectName: "cutVeil"; maximumWidth: parent.width; text: "cut, off screen only"; enabled: cutInput.text.trim() !== ""; onClicked: book.cutIt("veil") }
              Link { maximumWidth: parent.width; text: "keep it"; onClicked: book.cutting = false }
            }
          }
        }

        // Writing to the GM ------------------------------------------------------------------

        ControlSurface {
          id: composer
          objectName: "composerSurface"
          theme: book.theme
          baseColor: book.theme.surface
          controlState: input.activeFocus ? "focus" : composerHover.hovered ? "hover-cursor" : "normal"
          Layout.fillWidth: true
          visible: book.agent.book !== false
          implicitHeight: Math.max(Math.min(input.implicitHeight, book.theme.prose * 8), sendButton.implicitHeight)
            + book.fieldPaddingY * 2
          HoverHandler { id: composerHover }
          FontMetrics { id: inputMetrics; font: input.font }

          RowLayout {
            anchors.fill: parent
            anchors.leftMargin: book.fieldPaddingX
            anchors.rightMargin: anchors.leftMargin
            anchors.topMargin: book.fieldPaddingY
            anchors.bottomMargin: anchors.topMargin
            spacing: book.theme.controlGap

            Flickable {
              id: inputFlick
              Layout.fillWidth: true
              // Centred when one line is shorter than "send", so the text doesn't ride high.
              Layout.preferredHeight: Math.min(input.implicitHeight, book.theme.prose * 8)
              Layout.alignment: Qt.AlignVCenter
              contentHeight: input.implicitHeight
              clip: true
              boundsBehavior: Flickable.StopAtBounds

              TextEdit {
                id: input
                objectName: "bookInput"
                width: inputFlick.width
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                font.family: book.theme.serif
                font.pixelSize: book.theme.prose
                color: book.theme.text
                onActiveFocusChanged: if (activeFocus) textSelection.clear()
                selectionColor: book.theme.selection
                selectedTextColor: book.theme.selectedText
                selectByMouse: true
                focus: true
                Keys.onReturnPressed: event => {
                  if (event.modifiers & Qt.ShiftModifier) event.accepted = false
                  else { book.submit(); event.accepted = true }
                }
                Keys.onEnterPressed: event => { book.submit(); event.accepted = true }
                Keys.onEscapePressed: book.codexOpen = false

                Text {
                  visible: input.text === "" && !input.activeFocus || input.text === "" && book.busy
                  textFormat: Text.PlainText
                  font: input.font
                  objectName: "bookPlaceholder"
                  width: parent.width
                  elide: Text.ElideRight
                  color: book.theme.inputText(book.theme.placeholder, composer.controlState)
                  text: book.dead ? "An epilogue, if you want one…" : book.busy ? "The GM is writing…" : "What do you do?"
                }
              }
            }

            Link {
              id: sendButton
              objectName: "sendButton"
              Layout.alignment: Qt.AlignBottom
              Layout.rightMargin: -book.linkInsetX
              Layout.bottomMargin: Math.max(0, (inputMetrics.height - implicitHeight) / 2)
              text: book.busy ? "stop" : "send ↵"
              enabled: book.busy || input.text.trim() !== ""
              onClicked: book.busy ? book.stop() : book.submit()
            }
          }
        }

        Row {
          visible: book.agent.book === false
          spacing: book.theme.body
          Text {
            textFormat: Text.PlainText
            font.family: book.theme.mono
            font.pixelSize: book.theme.small
            color: book.theme.dim
            text: (book.agent.agent ? "Your GM (" + book.agent.agent + ")" : "Your GM") + " writes in its own window; the story shows here as it is recorded."
          }
          Link { text: "open the GM"; onClicked: book.openTerminal() }
        }
      }
    }
  }

  Atmosphere {
    id: atmosphere
    anchors.fill: parent
    theme: book.theme
    game: book.game
    heroX: pageRow.x + side.width / 2
    heroY: pageRow.y + book.height * 0.3
  }

  // The X-card: what the player typed is a note to the GM, or a line (never in the story) or a veil (off screen).
  function cutIt(as) {
    var text = cutInput.text.trim()
    cut(text, as === "line" ? text : "", as === "veil" ? text : "")
    cutInput.text = ""
    cutting = false
  }

  function submit() {
    var text = input.text.trim()
    if (text !== "" && !busy) {
      send(text)
      input.text = ""
    }
  }

  // Overlays ------------------------------------------------------------------------------

  Codex {
    objectName: "bookCodex"
    anchors { top: parent.top; right: parent.right; bottom: parent.bottom; margins: book.theme.body }
    width: Math.min(parent.width * 0.55, book.theme.body * 46)
    visible: book.codexOpen
    theme: book.theme
    selectionController: textSelection
    game: book.game
    onClosed: book.codexOpen = false
  }

  Epitaph {
    anchors.fill: parent
    visible: book.epitaphShown
    theme: book.theme
    gpu: book.gpu
    game: book.game
    onDismissed: book.epitaphDismissed = true
  }

  TitleCard {
    id: titleCard
    objectName: "titleCard"
    theme: book.theme
    gpu: book.gpu
  }

  DiceMoment {
    id: dice
    objectName: "dice"
    theme: book.theme
    gpu: book.gpu
    property string campaignAtThrow: ""
    onSettled: outcome => {
      book.diceLanded(dice.beat.seq, dice.campaignAtThrow)
      if (book.hurtOnLanding) book.strike("hurt")
      else if (outcome.dragon) book.strike("dragon")
      else if (outcome.demon) book.strike("demon")
      book.hurtOnLanding = false
    }
  }
}
