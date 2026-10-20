import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import qs.Commons as Shell
import qs.Ui
import "book"

// oma-solorpg on the desktop: two windows and a watcher.
//
// - The Book (book/BookView.qml): where the story is read and told. The default agent
//   writes in it as GM, run headless one turn at a time by `solo gm turn`.
// - The Table: a sidebar docked on the right. Home (your campaigns and the Hall of the
//   Fallen), New adventure (pick an adventure and a hero, then begin) and Table (sheet,
//   rolls, spells and abilities, fights and a Dragon's choice, death rolls, rests, light,
//   gear and what is broken, oracle, clocks, log).
// - The watcher: while a game is on, the desktop joins in (solo desk): a Dragon flashes
//   the window borders and the screen gold, a Demon red, a blow jolts the screen, dying
//   holds a red rim round it and death greys it, omens ripple it and arrive as
//   notifications, the table has sounds, and the screen warms like candlelight while the
//   Book is open.
//
// The plugin never writes campaign files. It runs its own bin/solo and reads state.json,
// which solo rewrites after every command, so the Book, the Table and the GM always agree
// about the dice. Buttons exist only for pure mechanics; judgement stays with the GM.
// The manifest keeps this loaded, so the watcher runs with both windows closed.
//
// Toggle the Table: omarchy-shell shell toggle cabral.oma-solorpg   (or the d20 in the bar)
// Open the Book:    omarchy-shell shell summon cabral.oma-solorpg '{"book":true}'   (right click the d20)
// A screen:         omarchy-shell shell summon cabral.oma-solorpg '{"view":"new"}'
Item {
  id: root

  property var shell: null
  property var manifest: null
  readonly property bool opened: workspacePin.shown

  WorkspacePin {
    id: workspacePin
    objectName: "workspacePin"
    hyprland: Hyprland
    screens: Quickshell.screens
    screen: tableWindow.screen
  }

  // Keep the pinned workspace's monitor, even when focus moves to another display.
  Binding {
    target: tableWindow
    property: "screen"
    value: workspacePin.pinnedScreen
    when: workspacePin.pinnedScreen !== null
    restoreMode: Binding.RestoreNone
  }

  Connections {
    target: Hyprland
    function onRawEvent(event) {
      // The regular workspace can remain active underneath a special-workspace overlay.
      if (event.name === "activespecial" || event.name === "activespecialv2") Hyprland.refreshMonitors()
      if (event.name === "configreloaded") hyprAppearance.refresh()
    }
  }

  readonly property string solo: decodeURIComponent(Qt.resolvedUrl("bin/solo").toString().replace(/^file:\/\//, ""))
  readonly property string stateDir: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/solo"
  property string campaign: ""
  property var game: null
  property var library: null
  // The campaign whose card is asking "delete for good?", by folder.
  property string deleting: ""
  property string view: "home"
  property bool settingsOpen: false
  property bool reducedMotion: Quickshell.env("SOLO_REDUCED_MOTION") === "1"
  property real bookScale: 1
  property real tableScale: 1
  property bool honorHyprland: false
  HyprlandAppearance {
    id: hyprAppearance
    objectName: "hyprAppearance"
    solo: root.solo
    requested: root.honorHyprland
    uiScale: root.tableScale
  }
  readonly property bool scaleBusy: scaleAction.running
  property string scaleTarget: ""
  property string scaleError: ""
  onSettingsOpenChanged: Qt.callLater(root.focusSettingsFace)
  property string error: ""
  property string errorAt: ""

  // New adventure. The seed makes the preview exactly the hero that Begin creates.
  property string pickedAdventure: ""
  property string pickedHero: "random"
  property var picks: ({})
  property string heroName: ""
  property int seed: 1
  property var preview: null
  // The player's table settings, sent with Begin. Lines and veils are comma-separated.
  property string tone: ""
  property string lines: ""
  property string veils: ""

  // The Book, and the GM's turn in progress (.solo/turn.json).
  property bool bookOpen: false
  property var turn: ({ status: "idle" })
  property var agentInfo: ({ agent: "", book: true })
  property var effects: ({ borders: true, screen: true, sound: true, candle: false, omens: true, screensaver: true })
  property string pace: "normal"  // how long the GM thinks before it answers (solo gm pace)
  // Prepared sounds and players ({play, commands, sounds, split_dice}, from solo desk sound).
  property var sounds: ({})
  // When the dice land, in seconds: the Book's tumble (book/DiceMoment.qml), or a quick
  // throw with the Book shut. The sounds are cut to match.
  readonly property real diceLand: 1.94
  readonly property real diceLandShort: 0.5
  // Recorded impacts follow the selected animation, never a sibling or an old campaign.
  property int diceSoundSeq: -1
  property bool diceSoundBook: false
  // What the watcher has already reacted to, so a reload never replays old rolls.
  property int fxSeen: -1
  property bool fxDying: false
  property int fxFailures: 0
  property bool fxDead: false
  property bool fxFighting: false
  property int fxSaid: -1
  // A roll just came in (not one already there when the game loaded): the Table's number tumbles.
  signal rolled()

  property int boons: 0
  property int banes: 0
  property bool allSkills: false
  property string odds: "even"
  property bool tend: false
  // The fortune chart's column for the next question (Dragonbane's solo rules).
  property string oracleKind: "yes_no"
  property string target: ""
  // Moves (Ironsworn): the adds a roll takes, the move waiting for its stat or track, the move
  // groups that are open, and the track being started.
  property int adds: 0
  property string pickedMove: ""
  property var openGroups: ({ "Adventure Moves": true })
  property string trackKind: "vow"
  property string trackRank: "dangerous"
  // Magic and abilities: the power level of the next spell, the die the body gives for it, the spell waiting to
  // be prepared (it asks which to put aside), the abilities switched on for the next blow, parry, rest or round,
  // and what an ability that costs what you choose is paid.
  property int power: 1
  property string body: ""
  property string preparing: ""
  property var riders: []
  property int spend: 1

  readonly property var pc: game && game.pc ? game.pc : null
  readonly property var labels: game && game.labels ? game.labels : ({ attributes: {}, tracks: {}, conditions: [], push: "condition", rests: {}, likelihood: [] })
  // What the game rolls with: a game of moves (Ironsworn) has these, a game of skills has none.
  readonly property var moves: labels.moves || null
  readonly property var momentum: labels.momentum || null
  readonly property var progressSpec: labels.progress || null
  readonly property var lastCheck: game && game.last_check ? game.last_check : null
  readonly property bool canPush: !dead && lastCheck !== null && lastCheck.type === "check" && lastCheck.outcome.pushable === true
  // Bindings update in no fixed order when state.json reloads, so pc is checked
  // here even though canPush already implies a game.
  readonly property var pushChoices: canPush && pc && labels.push === "condition"
    ? labels.conditions.filter(c => pc.conditions.indexOf(c) === -1) : []

  // A dead hero's fight is over (the engine ends it; campaigns from before that may still hold one).
  readonly property var fight: game && game.combat && !dead ? game.combat : null
  readonly property var trackIds: pc ? Object.keys(pc.tracks) : []
  readonly property var foeIds: fight ? Object.keys(fight.foes) : []
  readonly property var kit: game && game.kit ? game.kit : ({ weapons: [], armor: 0 })
  readonly property var magic: game && game.magic ? game.magic : null
  // A Dragon on a roll waits for the player's choice, and nothing else is rolled until it is made.
  readonly property var waiting: game && game.choice && !dead ? game.choice : null
  // At zero HP. `dying` is the helpless kind: a hero who rallied themselves acts again.
  readonly property bool atZero: pc !== null && !!pc.dying
  readonly property bool dying: atZero && !pc.dying.rallied
  readonly property bool dead: pc !== null && pc.dead === true

  readonly property var adventure: library && library.adventures.length > 0
    ? (library.adventures.filter(a => a.id === root.pickedAdventure)[0] || library.adventures[0]) : null
  readonly property var system: adventure ? library.systems.filter(s => s.id === adventure.system)[0] || null : null

  readonly property color textColor: theme.text
  readonly property color dim: theme.dim
  readonly property color faint: Qt.rgba(textColor.r, textColor.g, textColor.b, 0.15)

  function open(payloadJson) {
    var payload = {}
    try {
      payload = JSON.parse(payloadJson || "{}")
    } catch (e) {
      payload = {}
    }
    currentFile.reload()
    if (payload.book) workspacePin.requested = true  // the Book never pulls the player to the Table's workspace
    else workspacePin.show()
    root.show(payload.view || (root.campaign !== "" ? "table" : "home"))
    if (payload.book) root.openBook()
  }

  function openBook() {
    if (root.campaign !== "") {
      root.ask("agent", ["-C", root.campaign, "gm", "agent"])
      // A turn that died unfinished (the machine went down) is written down as stopped,
      // so the Book doesn't wait on it; turn.json brings the news.
      root.ask("turn", ["-C", root.campaign, "gm", "status"])
      root.bookOpen = true
    }
  }

  // The desktop effects (solo desk). Detached: they must never hold up the table. `after`
  // (seconds) holds one back to land with the Book's dice.
  function desk(args, after) {
    Quickshell.execDetached([root.solo].concat(root.campaign !== "" ? ["-C", root.campaign] : []).concat(["desk"])
      .concat(after > 0 ? ["--after", after.toFixed(2)] : []).concat(args))
  }

  // WAVs may be bundled, supplied locally, or synthesized in the cache.
  function sound(name, after) {
    var path = root.sounds.sounds ? root.sounds.sounds[name] : ""
    var command = (root.sounds.commands || {})[name] || root.sounds.play
    if (root.effects.sound === false || !command || !path) return
    Quickshell.execDetached(["sh", "-c", 'sleep "$0"; exec "$@"', String(after > 0 ? after.toFixed(2) : 0)]
      .concat(command).concat([path]))
  }

  function diceLanded(seq, fromBook, campaignAtThrow) {
    if (root.diceSoundSeq < 0 || campaignAtThrow !== root.campaign || seq !== root.diceSoundSeq || fromBook !== root.diceSoundBook) return
    root.diceSoundSeq = -1
    root.sound("dice-land")
  }

  // The player's words to the GM (none: the GM carries on from what is recorded). They go
  // in on stdin, by way of the environment, never as an argument: the process list is
  // anyone's to read, a process's environment only its owner's.
  function speak(text) {
    root.turn = { status: "thinking", player: text, text: "", doing: "reading the table" }
    speaker.command = ["sh", "-c", 'printf %s "$SOLO_SAY" | exec "$@"', "speak", root.solo, "-C", root.campaign, "gm", "turn", "--", "-"]
    speaker.environment = { SOLO_SAY: text }
    speaker.startDetached()
  }

  // New beats in the story set off the desktop. The dice rattle and land with the Book's
  // (quickly, with the Book shut), and what they bring lands with them: a Dragon floods the
  // screen gold, a Demon drains it red, a blow jolts it. Omens ripple it and notify, a
  // scene opens on a horn, a fight on a drum, a torch catches, the GM's words turn a page.
  // Dying holds a red rim, closer with each failure; death greys the screen and
  // tolls a bell. The screensaver keeps the GM's latest words while the Book is open.
  function watch() {
    if (!root.game || !root.game.story) return
    var beats = root.game.story
    var newest = beats.length ? beats[beats.length - 1].seq : 0
    var pc = root.game.pc
    var dead = !!(pc && pc.dead)
    var dying = !!(pc && pc.dying) && !dead
    var failures = dying ? pc.dying.failures || 0 : 0
    var fighting = !!root.game.combat && !dead
    if (root.fxSeen < 0) {
      root.fxSeen = newest
      root.fxDying = dying
      root.fxFailures = failures
      root.fxDead = dead
      root.fxFighting = fighting
      if (dying) root.desk(["dying", "on", String(failures)])
      return
    }
    var fresh = beats.filter(b => b.seq > root.fxSeen)
    root.fxSeen = Math.max(root.fxSeen, newest)
    var roll = fresh.filter(b => b.kind === "roll").pop()
    var land = roll ? (root.bookOpen ? root.diceLand : root.diceLandShort) : 0
    if (roll) {
      var outcome = roll.outcome || {}
      root.diceSoundSeq = root.sounds.split_dice ? roll.seq : -1
      root.diceSoundBook = root.bookOpen
      root.rolled()
      root.sound(root.sounds.split_dice ? (root.bookOpen ? "dice-roll" : "dice-roll-short") : (root.bookOpen ? "dice" : "dice-short"))
      if (outcome.dragon) {
        root.desk(["flash", "dragon"], land)
        root.sound("dragon", land)
      } else if (outcome.demon) {
        root.desk(["flash", "demon"], land)
        root.sound("demon", land)
      }
    }
    if (fresh.some(b => b.kind === "hurt" && (b.dealt || 0) > 0)) {
      root.desk(["flash", "hit"], land)
      root.sound("hit", land)
    }
    fresh.filter(b => b.kind === "omen").forEach(b => {
      root.desk(["omen", "--", b.text.replace(/^[^:]*\(\d+\):\s*/, "")])
      root.sound("omen")
    })
    if (fresh.some(b => b.kind === "scene")) root.sound("scene")
    if (fighting && !root.fxFighting) root.sound("drum", land)
    if (root.game.light && fresh.some(b => b.kind === "light")) root.sound("torch")
    if (root.bookOpen && fresh.some(b => b.kind === "gm")) root.sound("page")
    if (dead && !root.fxDead) {
      root.desk(["death"], land)
      root.sound("bell", land)
    } else if (dying !== root.fxDying || failures !== root.fxFailures) {
      root.desk(dying ? ["dying", "on", String(failures)] : ["dying", "off"], land)
      if (dying) root.sound("heartbeat", land)
    }
    root.fxDying = dying
    root.fxFailures = failures
    root.fxDead = dead
    root.fxFighting = fighting
    var said = root.game.last_said ? root.game.last_said.seq : -1
    if (root.bookOpen && said !== root.fxSaid) {
      root.fxSaid = said
      root.desk(["screensaver", "on"])
    }
  }

  onGameChanged: root.watch()
  // The game belongs to its campaign, and so does what it holds on the desktop: another one
  // picked, or this one deleted, drops the game and lets a dying hero's red go (a deleted
  // campaign's state.json is no longer watched when it goes, so nothing else would).
  onCampaignChanged: {
    root.settingsOpen = false
    if (root.fxDying) root.desk(["dying", "off"])
    root.game = null
    root.fxDying = false
    root.fxFailures = 0
    root.fxDead = false
    root.fxFighting = false
    root.fxSeen = -1
    root.fxSaid = -1
    root.diceSoundSeq = -1
    root.turn = { status: "idle" }
  }
  onBookOpenChanged: {
    if (root.bookOpen) {
      root.desk(["candle", "on"])
      root.desk(["screensaver", "on"])
    } else {
      root.desk(["candle", "off"])
      root.desk(["screensaver", "off"])
    }
  }
  // After a shell restart or a crash, nothing from an old session stays on the desktop.
  Component.onCompleted: {
    Quickshell.execDetached([root.solo, "desk", "restore"])
    root.ask("effects", ["desk", "settings"])
    root.ask("sounds", ["desk", "sound"])
    root.ask("pace", ["gm", "pace"])
  }

  function close() {
    root.settingsOpen = false
    workspacePin.hide()
  }

  function show(view) {
    root.settingsOpen = false
    root.view = view
    root.deleting = ""
    root.error = ""
    if (view !== "table") {
      root.ask("library", ["library"])
    }
  }

  function openSettings() {
    if (tableFlip.flipping) return
    root.settingsOpen = true
    root.ask("effects", ["desk", "settings"])
    root.ask("pace", ["gm", "pace"])
    if (root.campaign !== "") root.ask("agent", ["-C", root.campaign, "gm", "agent"])
  }

  function focusSettingsFace() {
    if (!root.opened || tableFlip.flipping || tableFlip.side !== (root.settingsOpen ? Flipable.Back : Flipable.Front)) return
    if (root.settingsOpen) settingsView.focusReturn()
    else settingsButton.forceActiveFocus()
  }

  function readScales(text) {
    var data = {}
    try { data = JSON.parse(text) || {} } catch (e) {}
    var valid = value => typeof value === "number" && [1, 1.25, 1.5, 1.75, 2].indexOf(value) !== -1 ? value : 1
    var legacy = valid(data.scale)
    root.bookScale = valid(data.book_scale === undefined ? legacy : data.book_scale)
    root.tableScale = valid(data.table_scale === undefined ? legacy : data.table_scale)
    root.honorHyprland = data.honor_hyprland === true
  }

  function setHonorHyprland(on) {
    if (root.scaleBusy || on === root.honorHyprland) return
    root.scaleTarget = "hyprland"
    root.scaleError = ""
    scaleAction.output = ""
    scaleAction.command = [root.solo, "ui", "--honor-hyprland=" + (on ? "on" : "off")]
    scaleAction.running = true
  }

  function setUiScale(target, value) {
    if (root.scaleBusy || ["book", "table"].indexOf(target) === -1 || typeof value !== "number"
        || [1, 1.25, 1.5, 1.75, 2].indexOf(value) === -1 || value === (target === "book" ? root.bookScale : root.tableScale)) return
    root.scaleTarget = target
    root.scaleError = ""
    scaleAction.output = ""
    scaleAction.command = [root.solo, "ui", "--" + target + "-scale=" + String(value)]
    scaleAction.running = true
  }

  function setPace(value) {
    if (!action.running && !query.running && root.agentInfo.book !== false) root.run(["gm", "pace", value], "pace")
  }

  function setEffect(name, on) {
    if (action.running || query.running) return
    root.run(["desk", "settings", name + "=" + (on ? "on" : "off")], "effects", () => {
      if (on && root.bookOpen && (name === "candle" || name === "screensaver")) root.desk([name, "on"])
    })
  }

  // Commands that change something. `done` runs after a success.
  function run(args, place, done) {
    if (!action.running) {
      root.error = ""
      root.errorAt = place
      action.done = done || null
      action.place = place
      action.output = ""
      action.command = [root.solo].concat(args)
      action.running = true
    }
  }

  function act(args, place, done) {
    if (root.campaign !== "") {
      root.run(["-C", root.campaign].concat(args), place, done)
    }
  }

  // Commands that only read (JSON on stdout). One runs at a time; the latest request
  // of each kind waits for its turn.
  function ask(kind, args) {
    if (query.running) {
      var pending = Object.assign({}, query.pending)
      pending[kind] = args
      query.pending = pending
    } else {
      query.kind = kind
      query.command = [root.solo].concat(args)
      query.running = true
    }
  }

  function received(kind, text) {
    var data = null
    try {
      data = JSON.parse(text)
    } catch (e) {
      data = null
    }
    if (kind === "library") {
      root.library = data
      if (root.view === "new") root.rollPreview()
    } else if (kind === "preview") {
      root.preview = data
    } else if (kind === "agent" && data) {
      root.agentInfo = data
    } else if (kind === "effects" && data) {
      root.effects = data
    } else if (kind === "sounds" && data) {
      root.sounds = data
    } else if (kind === "pace" && data) {
      root.pace = data.pace
    }
  }

  // New adventure ---------------------------------------------------------------------

  function creationTables() {
    var chosen = Object.keys(root.picks).map(k => root.picks[k])
    return root.system ? root.system.creation.filter(t => t.after.length === 0 || t.after.some(o => chosen.indexOf(o) !== -1)) : []
  }

  function pickWords() {
    return root.creationTables().map(t => root.picks[t.id] || "").filter(w => w !== "")
  }

  function choose(tableId, optionId) {
    var next = Object.assign({}, root.picks)
    next[tableId] = optionId
    root.picks = next
    root.rollPreview()
  }

  // A pre-made hero or a creation choice belongs to one system, so a different system starts over.
  function chooseAdventure(adventure) {
    if (!root.adventure || root.adventure.system !== adventure.system) {
      root.pickedHero = "random"
      root.picks = {}
    }
    root.pickedAdventure = adventure.id
    root.rollPreview()
  }

  function chooseHero(hero) {
    root.pickedHero = hero
    root.rollPreview()
  }

  function reroll() {
    root.seed = Math.floor(Math.random() * 1000000)
    root.rollPreview()
  }

  function rollPreview() {
    if (root.system) {
      var hero = root.pickedHero === "random" ? root.pickWords() : [root.pickedHero]
      root.ask("preview", ["character", "--system", root.system.path, "--adventure", root.adventure.path, "--seed", String(root.seed)].concat(hero))
    } else {
      root.preview = null
    }
  }

  function begin() {
    var hero = root.pickedHero === "random" ? (root.pickWords().join(" ") || "random") : root.pickedHero
    // What the player typed goes as --flag=value, so a value that starts with a dash stays a value.
    var args = ["new", root.adventure.path, "--character=" + hero, "--seed", String(root.seed), "--play"]
    var name = root.heroName.trim()
    if (name !== "") args.push("--name=" + name)
    if (root.tone.trim() !== "") args.push("--tone=" + root.tone.trim())
    root.split(root.lines).forEach(line => args.push("--line=" + line))
    root.split(root.veils).forEach(veil => args.push("--veil=" + veil))
    root.run(args, "begin", () => {
      root.heroName = ""
      nameField.text = ""
      root.show("table")
    })
  }

  function split(text) {
    return text.split(",").map(t => t.trim()).filter(t => t !== "")
  }

  // Table ------------------------------------------------------------------------------

  function roll(stat) {
    root.act(["check", stat, "--boons", String(root.boons), "--banes", String(root.banes)], "roll", () => {
      root.boons = 0
      root.banes = 0
    })
  }

  // Moves ------------------------------------------------------------------------------

  // The moves that roll dice, by the group the book puts them in.
  function moveGroups() {
    var groups = {}
    Object.keys(root.moves || {}).forEach(id => {
      var move = root.moves[id]
      if (move.kind !== "none") {
        var group = move.category || "Moves"
        groups[group] = (groups[group] || []).concat([{ id: id, name: move.name }])
      }
    })
    return Object.keys(groups).map(name => ({ name: name, moves: groups[name] }))
  }

  function toggleGroup(name) {
    var next = Object.assign({}, root.openGroups)
    next[name] = !next[name]
    root.openGroups = next
  }

  function openTracks() {
    var all = root.game && root.game.progress ? root.game.progress : ({})
    return Object.keys(all).filter(id => !all[id].ended).map(id => Object.assign({ id: id }, all[id]))
  }

  // A move with a choice to make (which stat, which track) waits for it; any other rolls at once.
  function pickMove(id) {
    var move = root.moves[id]
    var tracks = move.kind === "progress" ? root.openTracks().filter(t => t.kind === move.track) : []
    if ((move.kind === "action" && move.stats.length > 1 && !move.pick) || tracks.length > 1) {
      root.pickedMove = root.pickedMove === id ? "" : id
    } else {
      root.rollMove(id, "", "")
    }
  }

  function rollMove(id, stat, track) {
    var args = ["act", id].concat(stat !== "" ? ["--stat", stat] : []).concat(track !== "" ? ["--track", track] : [])
    if (root.moves[id].kind === "action" && root.adds !== 0) args = args.concat(["--add", String(root.adds)])
    root.act(args, "roll", () => {
      root.adds = 0
      root.pickedMove = ""
    })
  }

  // What a move waiting on a choice offers: the stats it can roll, or the open tracks it could read.
  function pickOptions() {
    var move = root.pickedMove !== "" && root.moves ? root.moves[root.pickedMove] : null
    if (!move || !root.pc) return []
    if (move.kind === "progress") return root.openTracks().filter(t => t.kind === move.track).map(t => ({ label: t.name, stat: "", track: t.id }))
    return move.stats.map(s => ({ label: s + " " + (root.pc.attributes[s] !== undefined ? root.pc.attributes[s] : root.pc.tracks[s].value), stat: s, track: "" }))
  }

  // The progress roll for a track: the move that reads its kind of track.
  function rollTrack(track) {
    var ids = Object.keys(root.moves).filter(id => root.moves[id].kind === "progress" && root.moves[id].track === track.kind)
    if (ids.length > 0) root.rollMove(ids[0], "", track.id)
  }

  function startTrack() {
    var name = trackName.text.trim()
    if (name === "") {
      root.error = "Name it first: a vow, a road or a foe."
      root.errorAt = "track"
    } else {
      root.act(["track", "add", "--kind", root.trackKind, "--rank", root.trackRank, "--", name], "track", () => trackName.text = "")
    }
  }

  function boxTicks(track, box) {
    return Math.max(0, Math.min(root.progressSpec.ticks, track.ticks - box * root.progressSpec.ticks))
  }

  function signed(value) {
    return (value > 0 ? "+" : "") + value
  }

  function skillList() {
    var skills = root.pc ? root.pc.skills : {}
    return Object.keys(skills)
      .filter(k => root.allSkills || skills[k].trained)
      .map(k => ({ id: k, name: skills[k].name, value: skills[k].value, trained: skills[k].trained,
                   marked: (root.pc.marks || []).indexOf(k) !== -1 }))
      .sort((a, b) => (b.trained - a.trained) || a.name.localeCompare(b.name))
  }

  function restUsed(id) {
    var rest = root.labels.rests[id]
    var taken = root.game && root.game.rests ? root.game.rests[id] : undefined
    return rest && rest.limit && taken !== undefined && Math.floor(taken / rest.limit) === Math.floor(root.game.time / rest.limit)
  }

  function askOracle() {
    var text = question.text.trim()
    if (text === "") {
      root.error = "Type a yes/no question first."
      root.errorAt = "oracle"
    } else {
      var kind = root.labels.fortune ? ["--kind", root.oracleKind] : []
      root.act(["ask", "--likely", root.odds].concat(kind).concat(["--", text]), "oracle", () => question.text = "")
    }
  }

  function askMeaning() {
    var text = question.text.trim()
    root.act(["ask", "--meaning"].concat(text !== "" ? ["--", text] : []), "oracle", () => question.text = "")
  }

  function lastOracle() {
    var asked = root.game ? root.game.log.filter(e => e.type === "oracle" || e.type === "meaning") : []
    return asked.length > 0 ? asked[asked.length - 1].text : ""
  }

  // Fights ---------------------------------------------------------------------------

  function standing() {
    return root.fight ? Object.keys(root.fight.foes).filter(k => !root.fight.foes[k].down) : []
  }

  function aimedAt() {
    var foes = root.standing()
    return foes.indexOf(root.target) !== -1 ? root.target : (foes[0] || "")
  }

  function attack(weapon) {
    var args = ["attack", root.aimedAt(), "--with", weapon, "--boons", String(root.boons), "--banes", String(root.banes)]
    root.act(args.concat(root.useArgs("attack", "")), "fight", () => {
      root.boons = 0
      root.banes = 0
      root.spent("attack", "")
    })
  }

  // Abilities. Those that go with a roll are switched on first (`riders`) and paid for when it is made.
  function abilityCost(ability) {
    var cost = ability.cost
    return !cost ? "" : cost === "varies" ? "varies" : Object.keys(cost).map(t => cost[t] + " " + t.toUpperCase()).join(", ")
  }

  function ridersFor(scope) {
    return (root.game && root.game.abilities ? root.game.abilities : []).filter(a => a.use === scope)
  }

  // The abilities switched on that belong to this roll (`on`: the parry or the dodge, the rest; "" for any).
  function riding(scope, on) {
    return root.ridersFor(scope).filter(a => root.riders.indexOf(a.name) !== -1 && (on === "" || a.on === null || a.on === on))
  }

  function useArgs(scope, on) {
    var args = []
    root.riding(scope, on).forEach(a => { args.push("--use"); args.push(a.name) })
    return args
  }

  function spent(scope, on) {
    var used = root.riding(scope, on).map(a => a.name)
    root.riders = root.riders.filter(name => used.indexOf(name) === -1)
  }

  function toggleRider(name) {
    root.riders = root.riders.indexOf(name) === -1 ? root.riders.concat([name]) : root.riders.filter(n => n !== name)
  }

  function useAbility(ability) {
    var cost = ability.cost === "varies" ? ["--cost", String(root.spend)] : []
    root.act(["ability"].concat(cost).concat(["--", ability.name]), "ability")
  }

  function spendMost() {
    var varies = root.ridersFor("alone").filter(a => a.cost === "varies")
    return varies.length > 0 && root.pc && root.pc.tracks[varies[0].track] ? Math.max(1, root.pc.tracks[varies[0].track].value) : 1
  }

  // Dragons: what the player may choose, a free attack once for each other foe standing.
  function dragonOptions() {
    var blow = { double: ["Double damage", "The weapon's dice, rolled twice"], pierce: ["Pierce armor", "Armor doesn't blunt the blow"],
                 attack: ["", "Another attack on a different foe, at no cost in turns"] }
    var spell = { double: ["Double the effect", "The spell's damage or healing doubled"], free: ["Cast for free", "The Dragon pays for it: the WP come back"],
                  another: ["Another spell", "Cast another at once, with a bane"] }
    var waiting = root.waiting
    var options = []
    if (waiting) {
      var words = waiting.kind === "spell" ? spell : blow
      waiting.options.forEach(o => {
        var say = words[o] || [o.charAt(0).toUpperCase() + o.slice(1).replace(/_/g, " "), ""]
        if (o === "attack" && waiting.kind !== "spell") {
          root.standing().filter(f => f !== waiting.target).forEach(f => options.push({ option: o, foe: f, tip: say[1], label: "Attack " + root.fight.foes[f].name }))
        } else {
          options.push({ option: o, foe: "", tip: say[1], label: say[0] })
        }
      })
    }
    return options
  }

  // Why the free attack isn't offered, when it is one of the choices and no other foe is standing.
  function dragonNote() {
    var asked = root.waiting && root.waiting.kind !== "spell" && root.waiting.options.indexOf("attack") !== -1
    return asked && root.dragonOptions().every(o => o.option !== "attack") ? "No other foe is standing for a free attack." : ""
  }

  // Spells: the ones ready to cast (a trick is always ready), the ones in the grimoire, and the casting.
  function ready() {
    return root.magic ? root.magic.spells.filter(s => s.trick || s.prepared) : []
  }

  function grimoire() {
    return root.magic ? root.magic.spells.filter(s => !s.trick && !s.prepared) : []
  }

  function castArgs(spell, fromGrimoire) {
    var args = ["cast", "--boons", String(root.boons), "--banes", String(root.banes)]
    if (spell.power) args = args.concat(["--power", String(root.power)])
    if (spell.damage && root.fight && root.aimedAt() !== "") args = args.concat(["--target", root.aimedAt()])
    if (root.body !== "" && !spell.heal) args = args.concat(["--body", root.body])
    return args.concat(fromGrimoire ? ["--grimoire"] : []).concat(["--", spell.name])
  }

  function cast(spell, fromGrimoire) {
    root.act(root.castArgs(spell, fromGrimoire), "magic", () => {
      root.boons = 0
      root.banes = 0
      root.power = 1
      root.body = ""
    })
  }

  // A spell asks which to put aside when the hero already holds as many as they can.
  function prepare(spell) {
    if (root.magic.ready >= root.magic.limit) {
      root.preparing = root.preparing === spell.name ? "" : spell.name
    } else {
      root.act(["prepare", "--", spell.name], "magic")
    }
  }

  function putAside(spell) {
    root.act(["prepare", "--drop", spell.name, "--", root.preparing], "magic", () => root.preparing = "")
  }

  function weaponNote(weapon) {
    return weapon.condition === "broken" ? " (broken)" : weapon.condition === "damaged" ? " (damaged)" : ""
  }

  function worn() {
    return root.kit.weapons.filter(w => w.condition)
  }

  function orderText() {
    return root.fight ? root.fight.order.map(f => f.card + " " + f.name).join(" · ") : ""
  }

  function prefsText() {
    var prefs = root.game && root.game.prefs ? root.game.prefs : { tone: "", lines: [], veils: [] }
    return [prefs.tone ? "Tone: " + prefs.tone : "",
            prefs.lines.length ? "Lines: " + prefs.lines.join(", ") : "",
            prefs.veils.length ? "Veils: " + prefs.veils.join(", ") : ""].filter(t => t !== "").join("\n")
  }

  function attitude(value) {
    return ["hostile", "unfriendly", "neutral", "friendly", "allied"][value + 2] || String(value)
  }

  function elapsed(seconds) {
    var rest = seconds % 86400
    var pad = n => (n < 10 ? "0" : "") + n
    return Math.floor(seconds / 86400) + "d " + pad(Math.floor(rest / 3600)) + ":" + pad(Math.floor(rest % 3600 / 60))
  }

  function carriesTorch() {
    return root.pc !== null && root.pc.items.some(i => /(^|\s)torch(es)?$/i.test(i))
  }

  function hours(seconds) {
    var minutes = Math.floor(seconds / 60)
    return minutes >= 60 ? Math.floor(minutes / 60) + " h " + (minutes % 60) + " min" : minutes + " min"
  }

  function values(object) {
    return object ? Object.keys(object).map(k => object[k]) : []
  }

  // The last roll in parts: its number, what was rolled, and what came of it.
  function rollFace() {
    var outcome = root.lastCheck ? root.lastCheck.outcome : null
    return !outcome ? "" : outcome.score !== undefined ? String(outcome.score) : outcome.result !== undefined ? String(outcome.result) : String(outcome.successes)
  }

  function rollHead() {
    var check = root.lastCheck
    if (!check) return ""
    var what = check.stat ? " +" + check.stat : check.track_name ? " (" + check.track_name + ")" : ""
    return (check.type === "push" ? "Pushed " : check.type === "burn" ? "Burned: " : "") + check.label + what
  }

  function rollVerdict() {
    var outcome = root.lastCheck ? root.lastCheck.outcome : null
    if (!outcome) {
      return ""
    } else if (outcome.hit !== undefined) {
      return "vs " + outcome.challenge.join(" · ") + " · " + outcome.hit.replace("_", " ") + (outcome.match ? " · a match" : "")
    } else if (outcome.result !== undefined) {
      var verdict = outcome.dragon ? "Dragon!" : outcome.demon ? "Demon!" : outcome.success ? "success" : "failure"
      return "vs " + outcome.target + " · " + verdict
    } else {
      var hits = outcome.successes === 1 ? "success" : "successes"
      return hits + (outcome.triggers.length ? " · " + outcome.triggers.join(", ") + "!" : "")
    }
  }

  function diceText() {
    var check = root.lastCheck
    var mods = check ? [check.boons ? check.boons + (check.boons === 1 ? " boon" : " boons") : "",
                        check.banes ? check.banes + (check.banes === 1 ? " bane" : " banes") : ""].filter(m => m !== "") : []
    // Dice fixed by SOLO_SEED (tests, demos) say so, here as in the Book.
    var seeded = check && check.seed !== undefined ? " · seeded " + check.seed : ""
    if (!check) {
      return ""
    } else if (check.outcome.hit !== undefined) {
      var move = check.outcome
      var sum = move.progress !== undefined ? "progress " + move.progress
        : (move.dulled ? "0 (the " + move.action + " is cancelled)" : move.action) + " + " + move.stat + (move.adds ? " + " + move.adds : "") + " = " + move.score
      return sum + (move.burned !== undefined ? " · momentum " + move.burned + " burned" : "") + seeded
    } else if (check.outcome.rolls) {
      return "dice " + check.outcome.rolls.join(", ") + (mods.length ? " (" + mods.join(", ") + ")" : "") + seeded
    } else {
      return check.outcome.groups.map(g => g.name + " " + (g.rolls.join(" ") || "none")).join(" · ") + seeded
    }
  }

  function rollColor() {
    var outcome = root.lastCheck ? root.lastCheck.outcome : null
    return outcome && outcome.dragon ? theme.gold : outcome && !outcome.success ? theme.urgentText
      : outcome && (outcome.successes > 1 || outcome.hit === "strong_hit") ? theme.accentText : root.textColor
  }

  function visibleClocks() {
    return root.game ? root.values(root.game.clocks).filter(c => !c.hidden) : []
  }

  function people() {
    return root.game ? root.values(root.game.npcs).filter(n => n.met) : []
  }

  function promises() {
    return root.game ? Object.keys(root.game.promises).map(k => {
      var promise = root.game.promises[k]
      var npc = root.game.npcs[promise.npc]
      return (npc ? npc.name : promise.npc) + ": " + promise.terms + " (" + promise.status + ")"
    }) : []
  }

  function recent() {
    return root.game ? root.game.log.filter(e => !e.hidden).slice(-14).reverse() : []
  }

  // Scales belong to the player, not a campaign. CLI edits and restarts use
  // the same saved state without recreating the Book or its draft message.
  FileView {
    id: uiFile
    path: root.stateDir + "/ui.json"
    blockLoading: true
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.readScales(text())
    onLoadFailed: root.readScales("{}")
  }

  // Which campaign is current, as recorded by `solo new`, `solo use` and `solo play`.
  // Read synchronously so open() already knows whether to show Home or the table, and
  // re-read on open and after every command: a watch set while the file didn't exist
  // yet (the very first game) never fires.
  FileView {
    id: currentFile
    path: root.stateDir + "/current"
    blockLoading: true
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.campaign = text().trim()
    onLoadFailed: root.campaign = ""
  }

  FileView {
    path: root.campaign !== "" ? root.campaign + "/state.json" : ""
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try {
        root.game = JSON.parse(text())
      } catch (e) {
        console.warn("solo-play", "Ignoring unreadable state.json", e)
      }
    }
    onLoadFailed: root.game = null
  }

  // The GM's turn in progress, written by `solo gm turn` as it streams.
  FileView {
    path: root.campaign !== "" ? root.campaign + "/.solo/turn.json" : ""
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try {
        root.turn = JSON.parse(text())
      } catch (e) {
        // Caught mid-write; the next change brings the whole file.
      }
    }
  }

  Theme { id: theme }

  // The Book: a normal window, so Hyprland tiles it beside the Table.
  FloatingWindow {
    id: bookWindow
    visible: root.bookOpen
    title: "oma-solorpg" + (root.game ? ": " + root.game.title : "")
    color: theme.background
    implicitWidth: 1100
    implicitHeight: 860
    minimumSize: Qt.size(640, 480)
    onVisibleChanged: if (!visible) root.bookOpen = false

    ScaledViewport {
      id: bookViewport
      objectName: "bookViewport"
      anchors.fill: parent
      factor: root.bookScale
    }

    BookView {
      objectName: "book"
      parent: bookViewport.canvas
      anchors.fill: parent
      theme: theme
      bookScale: root.bookScale
      scaleBusy: root.scaleBusy
      scaleError: root.scaleTarget === "book" ? root.scaleError : ""
      onScaleRequested: value => root.setUiScale("book", value)
      game: root.game
      turn: root.turn
      agent: root.agentInfo
      campaign: root.campaign
      actionError: root.errorAt === "book" ? root.error : ""
      active: bookWindow.visible
      onSend: text => root.speak(text)
      onStop: Quickshell.execDetached([root.solo, "-C", root.campaign, "gm", "stop"])
      onRetry: root.speak("")
      onDiceLanded: (seq, campaignAtThrow) => root.diceLanded(seq, true, campaignAtThrow)
      // The X-card: cut the GM's last message (a line or a veil too, if the player made it one), then the GM carries on without it.
      onCut: (note, line, veil) => root.act(["strike"].concat(note !== "" ? ["--note", note] : []).concat(line !== "" ? ["--line", line] : [])
                                              .concat(veil !== "" ? ["--veil", veil] : []), "book", () => root.speak(""))
      onAct: args => root.act(args, "book")
      onOpenTable: {
        workspacePin.show()
        root.show("table")
      }
      onOpenTerminal: root.run(["play", root.campaign, "--terminal"], "gm")
    }
  }

  Process {
    id: speaker
  }

  // Appearance writes must not borrow the campaign command slot or clear its
  // errors. The selected value changes only after the save succeeds.
  Process {
    id: scaleAction
    property string output: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: scaleAction.output = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: if (text.trim() !== "") root.scaleError = text.trim().replace(/^solo: /, "")
    }
    onExited: (exitCode, exitStatus) => {
      if (exitCode === 0) {
        root.readScales(scaleAction.output)
        root.scaleError = ""
        uiFile.reload()
      } else if (root.scaleError === "") {
        root.scaleError = root.scaleTarget === "hyprland" ? "Couldn't save Hyprland appearance. Try again."
          : "Couldn't save " + (root.scaleTarget === "book" ? "Book" : "Table") + " scale. Try again."
      }
    }
  }

  Process {
    id: action
    property var done: null
    property string place: ""
    property string output: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: action.output = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.error = text.trim().replace(/^solo: /, "")
    }
    onExited: (exitCode, exitStatus) => {
      var done = action.done
      action.done = null
      currentFile.reload()
      if (exitCode === 0) {
        if (action.place === "effects" || action.place === "pace") root.received(action.place, action.output)
        if (done) done()
      } else root.errorAt = action.place
    }
  }

  Process {
    id: query
    property string kind: ""
    property var pending: ({})
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.received(query.kind, text)
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (text.trim() !== "") {
          root.error = text.trim().replace(/^solo: /, "")
          root.errorAt = query.kind
        }
      }
    }
    onExited: {
      var kinds = Object.keys(query.pending)
      if (kinds.length > 0) {
        var args = query.pending[kinds[0]]
        var rest = Object.assign({}, query.pending)
        delete rest[kinds[0]]
        query.pending = rest
        root.ask(kinds[0], args)
      }
    }
  }

  // Text here comes from packs and from the GM's commits, so it is never read as HTML.
  component Line: Text {
    property int size: Style.font.body
    Layout.fillWidth: true
    textFormat: Text.PlainText
    color: root.textColor
    font.family: Style.font.family
    font.pixelSize: size
    wrapMode: Text.Wrap
  }

  component Heading: Text {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(10)
    textFormat: Text.PlainText
    color: root.dim
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
    font.capitalization: Font.AllUppercase
    font.letterSpacing: 1
  }

  component ErrorLine: Line {
    property string place: ""
    visible: root.error !== "" && root.errorAt === place
    color: theme.urgentText
    size: Style.font.bodySmall
    text: root.error
  }

  // A heading that folds its section away. Click it to open or close.
  component Fold: Heading {
    id: fold
    property string label: ""
    property bool open: false
    text: (open ? "▾ " : "▸ ") + label
    color: foldMouse.containsMouse ? root.textColor : root.dim

    MouseArea {
      id: foldMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: fold.open = !fold.open
    }
  }

  // A status tag (a condition held, a clue found). Clickable things are Buttons. Quiet
  // tags are dim until lit, so the conditions the hero holds stand out from the rest.
  component Tag: Rectangle {
    id: tag
    property string label: ""
    property bool lit: false
    property bool quiet: false
    implicitWidth: tagText.implicitWidth + Style.space(12)
    implicitHeight: tagText.implicitHeight + Style.space(6)
    radius: Style.cornerRadius
    color: lit ? Qt.rgba(Shell.Color.urgent.r, Shell.Color.urgent.g, Shell.Color.urgent.b, 0.25) : "transparent"
    border.width: 1
    border.color: lit ? Shell.Color.urgent : root.faint

    Text {
      id: tagText
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: tag.label
      color: tag.quiet && !tag.lit ? root.dim : root.textColor
      font.family: Style.font.family
      font.pixelSize: Style.font.caption
    }
  }

  component Choice: Button {
    foreground: root.textColor
    bordered: true
    fontSize: Style.font.bodySmall
    horizontalPadding: Style.space(8)
    verticalPadding: Style.space(3)
  }

  component HeaderChoice: Choice {
    Layout.minimumWidth: implicitWidth
    Layout.minimumHeight: Math.max(implicitHeight, Style.space(28))
    focusable: true
  }

  component Primary: Button {
    Layout.fillWidth: true
    Layout.topMargin: Style.space(8)
    foreground: root.textColor
    bordered: true
    selected: true
    verticalPadding: Style.space(8)
  }

  component Card: Rectangle {
    id: card
    property bool selected: false
    property bool clickable: true
    signal clicked()
    default property alias content: cardColumn.data
    Layout.fillWidth: true
    implicitHeight: cardColumn.implicitHeight + Style.space(16)
    radius: Style.cornerRadius
    color: card.clickable && cardMouse.containsMouse ? root.faint : "transparent"
    border.width: selected ? 2 : 1
    border.color: selected ? Shell.Color.accent : root.faint

    // Under the content, so a button inside a card takes its own clicks.
    MouseArea {
      id: cardMouse
      anchors.fill: parent
      enabled: card.clickable
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: card.clicked()
    }

    ColumnLayout {
      id: cardColumn
      anchors { left: parent.left; right: parent.right; top: parent.top; margins: Style.space(8) }
      spacing: Style.space(2)
    }
  }

  component Stepper: RowLayout {
    id: stepper
    property string label: ""
    property int value: 0
    property int from: 0
    property int to: 5
    signal stepped(int value)
    spacing: Style.space(4)

    Line { Layout.fillWidth: false; text: stepper.label; size: Style.font.bodySmall }
    Choice { text: "−"; onClicked: stepper.stepped(Math.max(stepper.from, stepper.value - 1)) }
    Line { Layout.fillWidth: false; text: String(stepper.value); font.bold: stepper.value > stepper.from }
    Choice { text: "+"; onClicked: stepper.stepped(Math.min(stepper.to, stepper.value + 1)) }
  }

  // The abilities that go with a roll: tap one to switch it on, and it is paid for with the roll.
  component Riders: Flow {
    id: riders
    property string scope: ""
    property string when: ""
    readonly property var choices: root.ridersFor(scope).filter(a => when === "" || a.on === null || a.on === when)
    Layout.fillWidth: true
    spacing: Style.space(4)
    visible: choices.length > 0 && root.pc !== null && !root.dying && !root.dead

    Line {
      Layout.fillWidth: false
      size: Style.font.caption
      color: root.dim
      text: ({ attack: "With the blow:", defend: "With a parry or dodge:", round: "For the new round:", rest: "With the rest:" })[riders.scope] || ""
    }

    Repeater {
      model: riders.choices
      delegate: Choice {
        required property var modelData
        text: modelData.name + " (" + root.abilityCost(modelData) + ")"
        tooltipText: modelData.afford ? "Add it to the next roll, and pay for it" : "Not enough to pay for it"
        selected: root.riders.indexOf(modelData.name) !== -1
        enabled: modelData.afford
        opacity: enabled ? 1 : 0.4
        onClicked: root.toggleRider(modelData.name)
      }
    }
  }

  // Momentum runs below zero and has a ceiling and a reset the hero's impacts move, so its
  // bar has a zero in it: the fill runs from there, the gold tick is the reset.
  component MomentumBar: ColumnLayout {
    id: bar
    property var track: ({ value: 0, max: 10, reset: 2 })
    property var range: ({ min: -6, max: 10 })
    readonly property real unit: rail.width / (range.max - range.min)
    Layout.fillWidth: true
    spacing: Style.space(2)

    RowLayout {
      Layout.fillWidth: true
      Line { text: "Momentum" }
      Line {
        Layout.fillWidth: false
        text: root.signed(bar.track.value) + "  (resets to " + root.signed(bar.track.reset) + ")"
      }
    }

    Rectangle {
      id: rail
      Layout.fillWidth: true
      implicitHeight: Style.space(8)
      radius: height / 2
      color: root.faint

      // Above the ceiling the hero's impacts leave: out of reach.
      Rectangle {
        x: (bar.track.max - bar.range.min) * bar.unit
        width: parent.width - x
        height: parent.height
        radius: parent.radius
        color: root.faint
      }
      Rectangle {
        x: (Math.min(0, bar.track.value) - bar.range.min) * bar.unit
        width: Math.abs(bar.track.value) * bar.unit
        height: parent.height
        color: bar.track.value < 0 ? Shell.Color.urgent : Shell.Color.accent
        Behavior on x { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
      }
      Rectangle {
        x: -bar.range.min * bar.unit - 1
        y: -2
        width: 2
        height: parent.height + 4
        color: root.dim
      }
      Rectangle {
        x: (bar.track.reset - bar.range.min) * bar.unit - 1
        y: -3
        width: 3
        height: parent.height + 6
        radius: 1
        color: theme.gold
      }
    }
  }

  // A progress track: ten boxes that fill a tick at a time.
  component Boxes: Row {
    id: boxes
    property var track: ({ ticks: 0 })
    spacing: Style.space(2)

    Repeater {
      model: root.progressSpec ? root.progressSpec.boxes : 0
      delegate: Rectangle {
        required property int index
        width: Style.space(20)
        height: Style.space(12)
        color: "transparent"
        border.width: 1
        border.color: root.dim

        Rectangle {
          anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 1 }
          height: (parent.height - 2) * root.boxTicks(boxes.track, index) / (root.progressSpec ? root.progressSpec.ticks : 4)
          color: Shell.Color.accent
        }
      }
    }
  }

  component Meter: ColumnLayout {
    id: meter
    property string label: ""
    property int value: 0
    property int maximum: 1
    readonly property real share: Math.max(0, Math.min(1, value / Math.max(1, maximum)))
    Layout.fillWidth: true
    spacing: Style.space(2)

    RowLayout {
      Layout.fillWidth: true
      Line { text: meter.label }
      Line {
        Layout.fillWidth: false
        text: meter.value + " / " + meter.maximum
      }
    }

    Rectangle {
      id: track
      Layout.fillWidth: true
      implicitHeight: Style.space(6)
      radius: height / 2
      color: root.faint

      // What was just lost lingers a moment in red, then drains away.
      Rectangle {
        width: track.width * meter.share
        height: parent.height
        radius: parent.radius
        color: Shell.Color.urgent
        opacity: 0.5
        Behavior on width {
          SequentialAnimation {
            PauseAnimation { duration: 450 }
            NumberAnimation { duration: 700; easing.type: Easing.InOutQuad }
          }
        }
      }
      // Full: the accent; under half: gold; a quarter or less: red.
      Rectangle {
        width: track.width * meter.share
        height: parent.height
        radius: parent.radius
        color: meter.share <= 0.25 ? Shell.Color.urgent : meter.share <= 0.5 ? theme.gold : Shell.Color.accent
        Behavior on width { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: 400 } }
      }
    }
  }

  PanelWindow {
    id: tableWindow
    objectName: "tableWindow"
    visible: root.opened
    onVisibleChanged: if (visible) hyprAppearance.refresh()
    anchors { top: true; right: true; bottom: true }
    implicitWidth: Style.space(340) * root.tableScale
    color: "transparent"
    exclusionMode: ExclusionMode.Auto
    WlrLayershell.namespace: "solo-play"
    // Arrange the reservation after the Top-layer bar, including a live resize.
    WlrLayershell.layer: WlrLayer.Overlay
    // Clicking the name or oracle field takes the keyboard; nothing else needs it.
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

    ScaledViewport {
      id: tableViewport
      objectName: "tableViewport"
      anchors.fill: parent
      factor: root.tableScale
    }
    // Layer surfaces have no native window shadow. Keep the Qt approximation
    // inside our existing reservation; no compositor rules are installed.
    RectangularShadow {
      parent: tableFlip
      anchors.fill: parent
      z: -1
      visible: hyprAppearance.shadowEnabled
      radius: hyprAppearance.rounding
      blur: hyprAppearance.shadowBlur
      color: hyprAppearance.shadowColor
      offset: hyprAppearance.shadowOffset
    }
    // Both faces stay mounted in the Table's scaled canvas. Flipping does not
    // change the native window, workspace pin, scroll position or game state.
    Flipable {
      id: tableFlip
      objectName: "tableFlip"
      parent: tableViewport.canvas
      anchors.fill: parent
      anchors.topMargin: hyprAppearance.gap("top")
      anchors.rightMargin: hyprAppearance.gap("right")
      anchors.bottomMargin: hyprAppearance.gap("bottom")
      anchors.leftMargin: hyprAppearance.gap("left")
      readonly property bool flipping: flipAnimation.running
      onSideChanged: Qt.callLater(root.focusSettingsFace)
      front: tableSurface
      back: settingsSurface
      transform: Rotation {
        origin.x: tableFlip.width / 2
        origin.y: tableFlip.height / 2
        axis { x: 0; y: 1; z: 0 }
        angle: root.settingsOpen ? 180 : 0
        Behavior on angle {
          NumberAnimation {
            id: flipAnimation
            duration: root.reducedMotion ? 0 : 350
            easing.type: Easing.InOutCubic
            onRunningChanged: if (!running) Qt.callLater(root.focusSettingsFace)
          }
        }
      }
    }
    BorderSurface {
      id: tableSurface
      objectName: "tableSurface"
      anchors.fill: parent
      color: Shell.Color.popups.background
      borderSpec: hyprAppearance.active ? hyprAppearance.borderSpec
        : Border.surfaceSpec("popups", "border", Shell.Color.popups.border, Math.max(1, Style.space(2)))
      radius: hyprAppearance.rounding
      visible: tableFlip.side === Flipable.Front
      Keys.onEscapePressed: root.close()

      ColumnLayout {
        id: tableHeader
        objectName: "tableHeader"
        enabled: !root.settingsOpen && !tableFlip.flipping
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: Style.space(12) }
        spacing: Style.space(8)
        RowLayout {
          id: headerControls
          objectName: "tableHeaderControls"
          readonly property real iconTarget: Math.max(Style.space(28), pinButton.implicitWidth, pinButton.implicitHeight,
                                                      settingsButton.implicitWidth, settingsButton.implicitHeight,
                                                      closeButton.implicitWidth, closeButton.implicitHeight)
          Layout.fillWidth: true
          spacing: Style.space(6)
          HeaderChoice {
            objectName: "tableCampaignsButton"
            visible: root.view === "table"
            text: "Campaigns"
            onClicked: root.show("home")
          }
          HeaderChoice {
            objectName: "tableBackButton"
            visible: root.view === "new"
            text: "Back"
            onClicked: root.show("home")
          }
          Item { Layout.fillWidth: true }
          HeaderChoice {
            id: settingsButton
            objectName: "tableSettingsButton"
            Layout.minimumWidth: headerControls.iconTarget
            Layout.minimumHeight: headerControls.iconTarget
            Layout.preferredWidth: headerControls.iconTarget
            text: String.fromCodePoint(0xF0493)
            fontFamily: "Symbols Nerd Font"
            fontSize: Style.font.title
            horizontalPadding: Style.space(4)
            Accessible.name: "Open Table settings"
            tooltipText: "Settings"
            onClicked: root.openSettings()
          }
          HeaderChoice {
            id: pinButton
            objectName: "workspacePinButton"
            Layout.minimumWidth: headerControls.iconTarget
            Layout.minimumHeight: headerControls.iconTarget
            Layout.preferredWidth: headerControls.iconTarget
            text: String.fromCodePoint(workspacePin.pinned ? 0xF0403 : 0xF0931)
            fontFamily: "Symbols Nerd Font"
            fontSize: Style.font.title
            horizontalPadding: Style.space(4)
            Accessible.name: workspacePin.pinned ? "Unpin Table from workspace" : "Pin Table to workspace"
            selected: workspacePin.pinned
            enabled: workspacePin.pinned || workspacePin.current !== null
            tooltipText: workspacePin.pinned ? "Pinned to workspace " + workspacePin.workspaceId + ". Click to unpin."
                                              : "Keep the Table on this workspace"
            onClicked: workspacePin.togglePin()
          }
          HeaderChoice {
            id: closeButton
            objectName: "tableCloseButton"
            Layout.minimumWidth: headerControls.iconTarget
            Layout.minimumHeight: headerControls.iconTarget
            Layout.preferredWidth: headerControls.iconTarget
            text: "×"
            fontSize: Style.font.title
            horizontalPadding: Style.space(4)
            Accessible.name: "Close Table"
            tooltipText: "Close (Esc)"
            onClicked: root.close()
          }
        }
        Line {
          objectName: "tableHeaderTitle"
          Layout.minimumWidth: 0
          Layout.preferredWidth: 0
          text: root.view === "new" ? "New adventure" : root.view === "table" && root.game ? root.game.title : "oma-solorpg"
          size: Style.font.heading
          font.bold: true
        }
      }
      Flickable {
        id: tableScroll
        objectName: "tableScroll"
        enabled: !root.settingsOpen && !tableFlip.flipping
        anchors { left: parent.left; right: parent.right; top: tableHeader.bottom; bottom: parent.bottom; margins: Style.space(12) }
        contentHeight: column.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        focus: true
        ColumnLayout {
          id: column
          width: parent.width
          spacing: Style.space(6)

          // Home --------------------------------------------------------------------

          ColumnLayout {
            visible: root.view === "home"
            Layout.fillWidth: true
            spacing: Style.space(6)

            Line {
              visible: root.library !== null && root.library.campaigns.length === 0
              color: root.dim
              text: "No campaigns yet. Pick an adventure and a hero, and the GM takes it from there."
            }

            Heading { text: "Continue"; visible: root.library !== null && root.library.campaigns.length > 0 }

            Repeater {
              model: root.library ? root.library.campaigns : []
              delegate: Card {
                required property var modelData
                selected: modelData.current
                clickable: root.deleting !== modelData.path
                onClicked: modelData.current ? root.show("table") : root.run(["use", modelData.path], "home", () => root.show("table"))

                Line { text: modelData.title; font.bold: true }
                Line {
                  size: Style.font.bodySmall
                  text: [modelData.hero + (modelData.info ? ", " + modelData.info : ""), modelData.scene].filter(t => t !== "").join(" · ")
                }
                Line {
                  visible: (modelData.said || "") !== ""
                  size: Style.font.bodySmall
                  color: root.dim
                  maximumLineCount: 2
                  elide: Text.ElideRight
                  text: modelData.said || ""
                }
                Line {
                  visible: (modelData.ended || "") !== ""
                  size: Style.font.bodySmall
                  font.italic: true
                  text: "Ended: " + (modelData.ended || "")
                }
                RowLayout {
                  Layout.fillWidth: true
                  visible: root.deleting !== modelData.path
                  Line {
                    size: Style.font.caption
                    color: root.dim
                    text: [modelData.current ? "current" : "", modelData.played ? "played " + modelData.played.replace("T", " ") : ""]
                      .filter(t => t !== "").join(" · ")
                  }
                  Choice {
                    text: "Delete"
                    onClicked: root.deleting = modelData.path
                  }
                }
                // Deleting can't be undone, so it takes a second click on the card itself.
                Line {
                  visible: root.deleting === modelData.path
                  Layout.topMargin: Style.space(4)
                  size: Style.font.bodySmall
                  color: theme.urgentText
                  text: "Delete this campaign for good? The story, " + (modelData.hero || "the hero") + " and the whole log go with it"
                        + (modelData.dead ? ", and " + modelData.hero + " leaves the Hall of the Fallen." : ".")
                }
                RowLayout {
                  visible: root.deleting === modelData.path
                  spacing: Style.space(4)
                  Choice {
                    text: action.running && root.errorAt === "home" ? "Deleting…" : "Delete for good"
                    foreground: theme.urgentText
                    enabled: !action.running
                    onClicked: {
                      var wasCurrent = modelData.current
                      root.run(["delete", modelData.path, "--yes"], "home", () => {
                        root.deleting = ""
                        if (wasCurrent) root.bookOpen = false
                        root.show("home")
                      })
                    }
                  }
                  Choice {
                    text: "Keep it"
                    onClicked: root.deleting = ""
                  }
                }
              }
            }

            Primary {
              text: "New adventure"
              onClicked: root.show("new")
            }

            // The Hall of the Fallen: every hero who died, with the last words the player gave them.
            Heading { text: "The Hall of the Fallen"; visible: root.library !== null && (root.library.fallen || []).length > 0 }

            Repeater {
              model: root.library ? root.library.fallen || [] : []
              delegate: Card {
                required property var modelData
                clickable: false

                RowLayout {
                  Layout.fillWidth: true
                  spacing: Style.space(8)

                  Text {
                    textFormat: Text.PlainText
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption * 0.8
                    color: root.dim
                    text: modelData.portrait.join("\n")
                  }

                  ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Style.space(2)
                    Line { text: modelData.name; font.bold: true }
                    Line { size: Style.font.caption; color: root.dim; text: modelData.info }
                    Line {
                      size: Style.font.bodySmall
                      text: "Fell in " + (modelData.scene || "the dark") + (modelData.by ? " to " + modelData.by : "") + ", " + modelData.adventure + "."
                    }
                    Line {
                      visible: modelData.epitaph !== ""
                      size: Style.font.bodySmall
                      font.italic: true
                      text: "\u201C" + modelData.epitaph + "\u201D"
                    }
                  }
                }
              }
            }

            ErrorLine { place: "home" }
            ErrorLine { place: "library" }
          }

          // New adventure -----------------------------------------------------------

          ColumnLayout {
            visible: root.view === "new"
            Layout.fillWidth: true
            spacing: Style.space(6)

            Heading { text: "1  Adventure" }

            Repeater {
              model: root.library ? root.library.adventures : []
              delegate: Card {
                required property var modelData
                selected: root.adventure !== null && root.adventure.id === modelData.id
                onClicked: root.chooseAdventure(modelData)

                Line { text: modelData.title; font.bold: true }
                Line {
                  size: Style.font.caption
                  color: root.dim
                  text: (root.library.systems.filter(s => s.id === modelData.system)[0] || { name: modelData.system || "no system named" }).name
                }
                Line { visible: modelData.summary !== ""; size: Style.font.bodySmall; text: modelData.summary }
              }
            }

            // Packs of your own that didn't load (half-built from a book, say), and why.
            Repeater {
              model: root.library ? root.library.problems || [] : []
              delegate: Line {
                required property string modelData
                size: Style.font.caption
                color: root.dim
                text: "Not loaded: " + modelData
              }
            }

            Heading { text: "2  Hero" }

            Line {
              visible: root.adventure !== null && root.system === null
              color: theme.urgentText
              size: Style.font.bodySmall
              text: "This adventure's system pack isn't installed, or its rules aren't built from your books yet (make dragonbane)."
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.system !== null

              Choice {
                text: "Random hero"
                selected: root.pickedHero === "random"
                onClicked: root.chooseHero("random")
              }

              Repeater {
                // The adventure's own heroes first (its pre-generated party), then the system's.
                model: root.system ? (root.adventure.characters || []).concat(root.system.characters) : []
                delegate: Choice {
                  required property var modelData
                  text: modelData.name + (modelData.info ? " · " + modelData.info : "")
                  selected: root.pickedHero === modelData.id
                  onClicked: root.chooseHero(modelData.id)
                }
              }
            }

            Repeater {
              model: root.pickedHero === "random" ? root.creationTables() : []
              delegate: ColumnLayout {
                id: table
                required property var modelData
                Layout.fillWidth: true
                spacing: Style.space(3)

                Line { text: table.modelData.label; size: Style.font.caption; color: root.dim }

                Flow {
                  Layout.fillWidth: true
                  spacing: Style.space(4)

                  Choice {
                    text: "Any"
                    selected: !root.picks[table.modelData.id]
                    onClicked: root.choose(table.modelData.id, "")
                  }

                  Repeater {
                    model: table.modelData.options
                    delegate: Choice {
                      required property var modelData
                      text: modelData.label
                      selected: root.picks[table.modelData.id] === modelData.id
                      onClicked: root.choose(table.modelData.id, modelData.id)
                    }
                  }
                }
              }
            }

            RowLayout {
              Layout.fillWidth: true
              visible: root.system !== null
              spacing: Style.space(6)

              TextField {
                id: nameField
                Layout.fillWidth: true
                placeholderText: root.preview ? "Name: " + root.preview.name : "Name"
                text: root.heroName
                onTextEdited: root.heroName = text
              }

              Choice {
                visible: root.pickedHero === "random"
                text: "Reroll"
                onClicked: root.reroll()
              }
            }

            Card {
              visible: root.preview !== null
              clickable: false

              Line {
                text: root.preview ? (root.heroName.trim() || root.preview.name) : ""
                size: Style.font.title
                font.bold: true
              }
              Line {
                size: Style.font.bodySmall
                color: root.dim
                text: root.preview ? root.values(root.preview.info).join(" · ") : ""
              }
              Line {
                size: Style.font.bodySmall
                text: root.preview ? Object.keys(root.preview.attributes).map(k => k.toUpperCase() + " " + root.preview.attributes[k]).join("  ") : ""
              }
              Line {
                size: Style.font.bodySmall
                text: root.preview ? Object.keys(root.preview.tracks).map(k => k.toUpperCase() + " " + (root.preview.tracks[k].min !== undefined ? root.signed(root.preview.tracks[k].value) : root.preview.tracks[k].max))
                  .concat(Object.keys(root.preview.ratings).map(k => k + " " + root.preview.ratings[k])).join(" · ") : ""
              }
              Line {
                visible: root.preview !== null && Object.keys(root.preview.skills).length > 0
                size: Style.font.bodySmall
                text: root.preview ? "Trained: " + Object.keys(root.preview.skills).filter(k => root.preview.skills[k].trained)
                  .map(k => root.preview.skills[k].name + " " + root.preview.skills[k].value).join(", ") : ""
              }
              Line {
                visible: root.preview !== null && root.preview.abilities.length > 0
                size: Style.font.bodySmall
                text: root.preview ? "Abilities: " + root.preview.abilities.join(", ") : ""
              }
              Line {
                visible: root.preview !== null && root.preview.items.length > 0
                size: Style.font.bodySmall
                color: root.dim
                text: root.preview ? "Gear: " + root.preview.items.join(", ") : ""
              }
            }

            ErrorLine { place: "preview" }

            Heading { text: "3  Table settings (optional)" }

            Line {
              size: Style.font.caption
              color: root.dim
              text: "The GM reads these every session. Lines never happen in the story; veils happen off screen. Separate them with commas."
            }

            TextField {
              Layout.fillWidth: true
              placeholderText: "Tone: grim and quiet, pulpy, heroic…"
              text: root.tone
              onTextEdited: root.tone = text
            }

            TextField {
              Layout.fillWidth: true
              placeholderText: "Lines"
              text: root.lines
              onTextEdited: root.lines = text
            }

            TextField {
              Layout.fillWidth: true
              placeholderText: "Veils"
              text: root.veils
              onTextEdited: root.veils = text
            }

            Primary {
              text: action.running && root.errorAt === "begin" ? "Starting…" : "Begin adventure"
              enabled: root.adventure !== null && root.preview !== null && !action.running
              opacity: enabled ? 1 : 0.5
              onClicked: root.begin()
            }

            Line {
              size: Style.font.caption
              color: root.dim
              text: "Begin opens the Book, and the GM tells the opening scene."
            }

            ErrorLine { place: "begin" }
            ErrorLine { place: "library" }
          }

          // Table -------------------------------------------------------------------

          ColumnLayout {
            visible: root.view === "table"
            Layout.fillWidth: true
            spacing: Style.space(6)

            Line {
              visible: root.game === null
              color: root.dim
              text: root.campaign === "" ? "No campaign is open." : "Loading the table…"
            }

            Line {
              visible: root.game !== null
              color: root.dim
              size: Style.font.bodySmall
              text: root.game ? (root.game.scene_title || "") + " · " + root.elapsed(root.game.time) + " in" : ""
            }

            RowLayout {
              Layout.fillWidth: true
              visible: root.game !== null

              Choice {
                Layout.fillWidth: true
                text: "Open the Book"
                tooltipText: "The story window, with your default agent as GM"
                onClicked: root.openBook()
              }

              Choice {
                text: "Terminal"
                tooltipText: "Open the GM in a terminal instead, or bring its window forward"
                onClicked: root.run(["play", root.campaign, "--terminal"], "gm")
              }
            }

            ErrorLine { place: "gm" }

            Card {
              visible: root.game !== null && !!root.game.ended
              clickable: false
              selected: true

              Line { text: root.dead ? "The adventure is over" : "The adventure has ended"; font.bold: true }
              Line { size: Style.font.bodySmall; text: root.game && root.game.ended ? root.game.ended.text : "" }
            }

            // Where you left off: the GM's last words exactly as recorded, so the table
            // reads the same before and after the GM window is reopened. Folded until asked for.

            Fold { id: leftOff; label: "Where you left off"; visible: root.game !== null && !!root.game.last_said }

            Card {
              visible: leftOff.open && root.game !== null && !!root.game.last_said
              clickable: false

              Line {
                size: Style.font.bodySmall
                text: root.game && root.game.last_said ? root.game.last_said.text : ""
              }
              Line {
                visible: root.game !== null && root.game.awaiting_player === true
                size: Style.font.caption
                color: root.dim
                text: "Waiting for your answer"
              }
            }

            // Character

            Heading { text: "Character"; visible: root.pc !== null }

            Line {
              visible: root.pc !== null
              size: Style.font.title
              font.bold: true
              text: root.pc ? root.pc.name : ""
            }

            Line {
              visible: root.pc !== null && Object.keys(root.pc.info).length > 0
              size: Style.font.bodySmall
              color: root.dim
              text: root.pc ? root.values(root.pc.info).join(" · ") : ""
            }

            // By count, so a reload keeps the meters and they can show what changed.
            Repeater {
              model: root.trackIds.length
              delegate: Meter {
                required property int index
                readonly property string track: root.trackIds[index] || ""
                // Momentum, which runs below zero, has its own bar (below).
                visible: !(root.pc && root.pc.tracks[track] && root.pc.tracks[track].min !== undefined)
                label: root.labels.tracks[track] || track
                value: root.pc && root.pc.tracks[track] ? root.pc.tracks[track].value : 0
                maximum: root.pc && root.pc.tracks[track] ? root.pc.tracks[track].max : 1
              }
            }

            MomentumBar {
              visible: root.momentum !== null && !!root.pc && !!root.pc.tracks.momentum
              track: root.pc && root.pc.tracks.momentum ? root.pc.tracks.momentum : ({ value: 0, max: 10, reset: 2 })
              range: root.momentum || ({ min: -6, max: 10 })
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.pc !== null && root.labels.conditions.length > 0

              Repeater {
                model: root.pc ? root.labels.conditions : []
                delegate: Tag {
                  required property string modelData
                  label: modelData
                  quiet: true
                  lit: root.pc !== null && root.pc.conditions.indexOf(modelData) !== -1
                }
              }
            }

            // At 0 HP only the death roll is left to click (or, alone, rallying and saving yourself).
            Line {
              visible: root.atZero
              color: theme.urgentText
              font.bold: true
              text: root.atZero && root.labels.dying ? root.pc.name + " is dying: " + root.pc.dying.successes + " of " + root.labels.dying.rally
                + " successes, " + root.pc.dying.failures + " of " + root.labels.dying.die + " failures. Any hit is a failure." : ""
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.atZero

              Primary {
                text: "Death roll"
                enabled: !action.running
                onClicked: root.act(["death-roll"], "dying")
              }

              Choice {
                visible: !!(root.labels.dying && root.labels.dying.self_save)
                text: "Save yourself"
                tooltipText: "A HEALING roll instead of the death roll: stop dying on a success"
                onClicked: root.act(["death-roll", "--heal"], "dying")
              }

              Choice {
                visible: !!(root.labels.dying && root.labels.dying.self_rally) && root.dying
                text: "Rally"
                tooltipText: "Rally yourself, with no bane: act again, still making death rolls"
                onClicked: root.act(["rally"], "dying")
              }
            }

            ErrorLine { place: "dying" }

            Line {
              visible: root.pc !== null && ((root.pc.abilities || []).length > 0 || Object.keys(root.pc.ratings || {}).length > 0)
              size: Style.font.bodySmall
              color: root.dim
              text: root.pc ? (root.pc.abilities || []).concat(Object.keys(root.pc.ratings || {}).map(k => k + " " + root.pc.ratings[k])).join(" · ") : ""
            }

            // Rolling

            Heading { text: "Roll"; visible: root.pc !== null && !root.dying && !root.dead }

            RowLayout {
              visible: root.pc !== null && !root.dying && !root.dead && root.moves === null
              Layout.fillWidth: true
              spacing: Style.space(12)

              Stepper { label: "Boons"; value: root.boons; onStepped: function(value) { root.boons = value } }
              Stepper { label: "Banes"; value: root.banes; onStepped: function(value) { root.banes = value } }
            }

            // Attributes in even columns: six make two rows of three, four fit on one.
            GridLayout {
              id: attributes
              readonly property var names: root.pc ? Object.keys(root.pc.attributes) : []
              Layout.fillWidth: true
              columns: names.length > 4 ? Math.ceil(names.length / 2) : Math.max(1, names.length)
              columnSpacing: Style.space(4)
              rowSpacing: Style.space(4)
              visible: root.pc !== null && !root.dying && !root.dead && root.moves === null

              Repeater {
                model: attributes.names
                delegate: Choice {
                  required property string modelData
                  Layout.fillWidth: true
                  text: modelData.toUpperCase() + " " + (root.pc && root.pc.attributes ? root.pc.attributes[modelData] : "")
                  tooltipText: "Roll " + ((root.labels.attributes || {})[modelData] || modelData)
                  onClicked: root.roll(modelData)
                }
              }
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.pc !== null && !root.dying && !root.dead && root.moves === null

              Repeater {
                model: root.skillList()
                delegate: Choice {
                  required property var modelData
                  text: modelData.name + " " + modelData.value + (modelData.marked ? " •" : "")
                  tooltipText: modelData.marked ? "Marked for advancement" : ""
                  selected: modelData.trained
                  onClicked: root.roll(modelData.id)
                }
              }

              Choice {
                text: root.allSkills ? "Fewer skills" : "Other skills…"
                bordered: false
                onClicked: root.allSkills = !root.allSkills
              }
            }

            // A game of moves (Ironsworn): the stats are what a move adds, and the hero makes moves.
            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.moves !== null && root.pc !== null && !root.dead

              Repeater {
                model: root.pc && root.moves ? Object.keys(root.pc.attributes) : []
                delegate: Tag {
                  required property string modelData
                  label: modelData + " " + (root.pc ? root.pc.attributes[modelData] : "")
                }
              }
            }

            Stepper {
              visible: root.moves !== null && root.pc !== null && !root.dead
              label: "Adds"
              value: root.adds
              onStepped: function(value) { root.adds = value }
            }

            Repeater {
              model: root.moves !== null && root.pc !== null && !root.dead ? root.moveGroups() : []
              delegate: ColumnLayout {
                id: group
                required property var modelData
                Layout.fillWidth: true
                spacing: Style.space(2)

                Heading {
                  text: (root.openGroups[group.modelData.name] ? "▾ " : "▸ ") + group.modelData.name
                  color: groupMouse.containsMouse ? root.textColor : root.dim

                  MouseArea {
                    id: groupMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.toggleGroup(group.modelData.name)
                  }
                }

                Flow {
                  Layout.fillWidth: true
                  spacing: Style.space(4)
                  visible: !!root.openGroups[group.modelData.name]

                  Repeater {
                    model: group.modelData.moves
                    delegate: Choice {
                      required property var modelData
                      text: modelData.name
                      selected: root.pickedMove === modelData.id
                      onClicked: root.pickMove(modelData.id)
                    }
                  }
                }
              }
            }

            Line {
              visible: root.pickedMove !== ""
              size: Style.font.caption
              color: root.dim
              text: root.pickedMove !== "" && root.moves && root.moves[root.pickedMove]
                ? root.moves[root.pickedMove].name + ": " + (root.moves[root.pickedMove].kind === "progress" ? "which one?" : "roll with which stat?") : ""
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.pickedMove !== ""

              Repeater {
                model: root.pickOptions()
                delegate: Choice {
                  required property var modelData
                  text: modelData.label
                  onClicked: root.rollMove(root.pickedMove, modelData.stat, modelData.track)
                }
              }
            }

            // The last roll: its number large, tumbling for a moment when a new one comes in
            // and landing with a jolt; gold for a Dragon, red for a Demon or a failure.
            RowLayout {
              id: rollCard
              visible: root.lastCheck !== null && !root.dead
              Layout.topMargin: Style.space(4)
              Layout.fillWidth: true
              spacing: Style.space(10)
              property string face: root.rollFace()
              property int ticks: 0
              property int soundSeq: -1
              property string campaignAtThrow: ""

              Connections {
                target: root
                function onRolled() {
                  rollCard.campaignAtThrow = root.campaign
                  rollCard.soundSeq = root.diceSoundSeq
                  rollCard.ticks = 0
                  tumble.interval = 40
                  tumble.restart()
                }
              }

              Timer {
                id: tumble
                repeat: true
                onTriggered: {
                  rollCard.ticks += 1
                  if (rollCard.ticks >= 9) {
                    stop()
                    rollCard.face = Qt.binding(() => root.rollFace())
                    land.restart()
                    root.diceLanded(rollCard.soundSeq, false, rollCard.campaignAtThrow)
                  } else {
                    var outcome = root.lastCheck ? root.lastCheck.outcome : {}
                    var most = outcome.score !== undefined ? 11 : outcome.result !== undefined ? 20 : Math.max(3, (outcome.successes || 0) + 2)
                    rollCard.face = String(Math.floor(Math.random() * most) + (outcome.result !== undefined ? 1 : 0))
                    interval = 40 + rollCard.ticks * rollCard.ticks * 3
                  }
                }
              }

              Text {
                id: rollNumber
                Layout.alignment: Qt.AlignVCenter
                Layout.preferredWidth: rollSizer.width
                horizontalAlignment: Text.AlignHCenter
                textFormat: Text.PlainText
                font.family: Style.font.family
                font.pixelSize: Math.round(Style.font.title * 2.1)
                font.bold: true
                color: tumble.running ? root.dim : root.rollColor()
                text: rollCard.face
                Behavior on color { ColorAnimation { duration: 250 } }
                SequentialAnimation {
                  id: land
                  NumberAnimation { target: rollNumber; property: "scale"; from: 1.45; to: 1; duration: 380; easing.type: Easing.OutBack }
                }
                // Room for the widest number, so the row doesn't jump while it tumbles.
                TextMetrics { id: rollSizer; font: rollNumber.font; text: "20" }
              }

              ColumnLayout {
                Layout.fillWidth: true
                spacing: Style.space(1)
                Line {
                  size: Style.font.body
                  font.bold: true
                  text: root.rollHead()
                }
                Line {
                  size: Style.font.body
                  font.bold: true
                  color: root.rollColor()
                  opacity: tumble.running ? 0 : 1
                  text: root.rollVerdict()
                  Behavior on opacity { NumberAnimation { duration: 200 } }
                }
                Line {
                  size: Style.font.caption
                  color: root.dim
                  opacity: tumble.running ? 0 : 1
                  text: root.diceText()
                  Behavior on opacity { NumberAnimation { duration: 200 } }
                }
              }
            }

            // A Dragon waits for what it does: nothing else is rolled until this is chosen.
            Card {
              visible: root.waiting !== null
              clickable: false
              selected: true

              Line { text: "A Dragon! What does it do?"; font.bold: true }

              Flow {
                Layout.fillWidth: true
                spacing: Style.space(4)

                Repeater {
                  model: root.dragonOptions()
                  delegate: Choice {
                    required property var modelData
                    text: modelData.label
                    tooltipText: modelData.tip
                    enabled: !action.running
                    onClicked: root.act(["dragon", modelData.option].concat(modelData.foe !== "" ? [modelData.foe] : []), "dragon")
                  }
                }
              }

              Line {
                visible: root.dragonNote() !== ""
                size: Style.font.caption
                color: root.dim
                text: root.dragonNote()
              }
            }

            ErrorLine { place: "dragon" }

            // Momentum can be burned on the roll just made, when that would change it.
            Choice {
              visible: !!(root.game && root.game.burn) && !root.dead
              Layout.fillWidth: true
              selected: true
              text: root.game && root.game.burn ? "Burn momentum " + root.signed(root.game.burn.momentum) : ""
              tooltipText: root.game && root.game.burn ? "Cancels the challenge dice under it: a " + root.game.burn.hit.replace("_", " ")
                + ". Momentum goes back to " + root.signed(root.game.burn.reset) : ""
              onClicked: root.act(["burn"], "roll")
            }

            Line {
              visible: root.canPush
              color: root.dim
              size: Style.font.caption
              text: root.pushChoices.length > 0 ? "Push the roll by taking a condition:" : "Push the roll:"
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.canPush

              Repeater {
                model: root.pushChoices
                delegate: Choice {
                  required property string modelData
                  text: modelData
                  onClicked: root.act(["push", "--condition", modelData], "roll")
                }
              }

              Choice {
                visible: root.labels.push !== "condition"
                text: "push"
                onClicked: root.act(["push"], "roll")
              }

              Choice {
                visible: !!root.labels.push_ability && !!root.pc && (root.pc.abilities || []).indexOf(root.labels.push_ability.name) >= 0
                text: root.labels.push_ability ? root.labels.push_ability.name + " (" + root.labels.push_ability.cost + ")" : ""
                tooltipText: "Push without a condition"
                onClicked: root.act(["push", "--sole-survivor"], "roll")
              }
            }

            ErrorLine { place: "roll" }

            // Magic: what the hero can cast, with the power, boons and banes above, and what is ready to cast.

            Heading { text: "Magic"; visible: root.magic !== null && !root.dying && !root.dead }

            RowLayout {
              Layout.fillWidth: true
              spacing: Style.space(12)
              visible: root.magic !== null && !root.dying && !root.dead

              Stepper {
                label: "Power"
                from: 1
                to: root.magic ? root.magic.max_power : 1
                value: root.power
                onStepped: function(value) { root.power = value }
              }

              Line {
                size: Style.font.caption
                color: root.dim
                text: root.magic ? "Ready " + root.magic.ready + " of " + root.magic.limit : ""
              }
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.magic !== null && root.magic.body.length > 0 && !root.dying && !root.dead

              Line { Layout.fillWidth: false; size: Style.font.caption; color: root.dim; text: "Power from the body:" }

              Repeater {
                model: root.magic ? root.magic.body : []
                delegate: Choice {
                  required property string modelData
                  text: modelData
                  tooltipText: "Draw that many WP from your body, and take as much harm"
                  selected: root.body === modelData
                  onClicked: root.body = root.body === modelData ? "" : modelData
                }
              }
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.magic !== null && !root.dying && !root.dead

              Repeater {
                model: root.ready()
                delegate: Choice {
                  required property var modelData
                  text: modelData.name + (modelData.cost !== null ? " · " + modelData.cost + " " + root.magic.track.toUpperCase() : "")
                  tooltipText: (modelData.trick ? "A magic trick: always ready, and it works" : "Rank " + modelData.rank + (modelData.school ? ", " + modelData.school : ""))
                    + (modelData.damage && root.fight ? ". Hits the foe you aimed at" : "") + (modelData.heal ? ". Heals you" : "")
                  selected: !modelData.trick
                  enabled: root.waiting === null && !action.running
                  opacity: enabled ? 1 : 0.5
                  onClicked: root.cast(modelData, false)
                }
              }
            }

            Fold { id: grimoireFold; label: "Grimoire"; visible: root.grimoire().length > 0 && !root.dying && !root.dead }

            Repeater {
              model: grimoireFold.open && !root.dying && !root.dead ? root.grimoire() : []
              delegate: RowLayout {
                id: spellRow
                required property var modelData
                Layout.fillWidth: true
                spacing: Style.space(4)

                Line { text: spellRow.modelData.name + (spellRow.modelData.cost !== null ? " · " + spellRow.modelData.cost + " " + root.magic.track.toUpperCase() : "") }

                Choice {
                  text: "Prepare"
                  tooltipText: "Hold it ready (it takes a stretch of study, the GM's to give)"
                  selected: root.preparing === spellRow.modelData.name
                  onClicked: root.prepare(spellRow.modelData)
                }

                Choice {
                  text: "From the grimoire"
                  tooltipText: spellRow.modelData.reaction ? "A reaction spell can't be cast from the grimoire" : "Cast it unprepared: it takes twice as long"
                  enabled: root.waiting === null && !action.running && !spellRow.modelData.reaction
                  opacity: enabled ? 1 : 0.4
                  onClicked: root.cast(spellRow.modelData, true)
                }
              }
            }

            Line {
              visible: root.preparing !== ""
              size: Style.font.caption
              color: root.dim
              text: "You hold as many as you can: put which aside for " + root.preparing + "?"
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.preparing !== ""

              Repeater {
                model: root.preparing !== "" ? root.ready().filter(s => !s.trick) : []
                delegate: Choice {
                  required property var modelData
                  text: modelData.name
                  onClicked: root.putAside(modelData)
                }
              }
            }

            ErrorLine { place: "magic" }

            // Abilities that stand alone: paid for and written down, and the GM says what they do.

            Heading { text: "Abilities"; visible: root.ridersFor("alone").length > 0 && !root.dying && !root.dead }

            Stepper {
              visible: root.ridersFor("alone").some(a => a.cost === "varies") && !root.dying && !root.dead
              label: "Spend"
              from: 1
              to: root.spendMost()
              value: root.spend
              onStepped: function(value) { root.spend = value }
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: !root.dying && !root.dead

              Repeater {
                model: root.ridersFor("alone")
                delegate: Choice {
                  required property var modelData
                  text: modelData.name + " (" + root.abilityCost(modelData) + ")"
                  tooltipText: modelData.afford ? "Pay for it; the GM reads its page" : "Not enough to pay for it"
                  enabled: modelData.afford && !action.running
                  opacity: enabled ? 1 : 0.4
                  onClicked: root.useAbility(modelData)
                }
              }
            }

            ErrorLine { place: "ability" }

            // Vows, journeys and fights (Ironsworn): ten boxes each, marked as the story earns it.

            Heading { text: "Vows and roads"; visible: root.moves !== null && root.openTracks().length > 0 && !root.dead }

            Repeater {
              model: root.moves !== null && !root.dead ? root.openTracks() : []
              delegate: Card {
                id: trackCard
                required property var modelData
                readonly property bool ranked: !!root.progressSpec && !!root.progressSpec.kinds[modelData.kind]
                clickable: false

                Line {
                  font.bold: true
                  text: trackCard.modelData.name
                }

                Line {
                  size: Style.font.caption
                  color: root.dim
                  text: (trackCard.modelData.rank ? trackCard.modelData.rank + " " : "")
                    + (root.progressSpec ? (root.progressSpec.kinds[trackCard.modelData.kind] || root.progressSpec.unranked[trackCard.modelData.kind] || "").toLowerCase() : "")
                    + " · " + Math.floor(trackCard.modelData.ticks / (root.progressSpec ? root.progressSpec.ticks : 4)) + " of " + (root.progressSpec ? root.progressSpec.boxes : 10)
                }

                Boxes { track: trackCard.modelData }

                RowLayout {
                  spacing: Style.space(4)

                  Choice {
                    text: "Mark progress"
                    tooltipText: trackCard.ranked ? "What a step of this rank is worth" : "One tick"
                    onClicked: root.act(["track", "mark", trackCard.modelData.id], "track")
                  }

                  Choice {
                    visible: trackCard.ranked
                    text: "Progress roll"
                    tooltipText: "Compare the filled boxes to the challenge dice"
                    onClicked: root.rollTrack(trackCard.modelData)
                  }
                }
              }
            }

            Fold {
              id: trackFold
              label: "Start a track"
              visible: root.moves !== null && root.pc !== null && !root.dead
            }

            ColumnLayout {
              visible: trackFold.open && root.moves !== null && root.pc !== null && !root.dead
              Layout.fillWidth: true
              spacing: Style.space(4)

              TextField {
                id: trackName
                objectName: "trackName"
                Layout.fillWidth: true
                placeholderText: "A vow, a road or a foe"
                onAccepted: root.startTrack()
              }

              Flow {
                Layout.fillWidth: true
                spacing: Style.space(4)

                Repeater {
                  model: root.progressSpec ? Object.keys(root.progressSpec.kinds) : []
                  delegate: Choice {
                    required property string modelData
                    text: root.progressSpec.kinds[modelData]
                    selected: root.trackKind === modelData
                    onClicked: root.trackKind = modelData
                  }
                }
              }

              Flow {
                Layout.fillWidth: true
                spacing: Style.space(4)

                Repeater {
                  model: root.progressSpec ? Object.keys(root.progressSpec.ranks) : []
                  delegate: Choice {
                    required property string modelData
                    text: modelData
                    selected: root.trackRank === modelData
                    onClicked: root.trackRank = modelData
                  }
                }
              }

              Choice {
                text: "Start"
                selected: true
                onClicked: root.startTrack()
              }
            }

            ErrorLine { place: "track" }

            // Advancement: marks come from Dragons and Demons and the GM's end-of-session
            // questions; rolling them is the last thing in a session.

            RowLayout {
              Layout.fillWidth: true
              visible: root.pc !== null && (root.pc.marks || []).length > 0 && !root.dead

              Line {
                size: Style.font.bodySmall
                color: root.dim
                text: root.pc ? "Marked: " + (root.pc.marks || []).map(k => root.pc.skills[k] ? root.pc.skills[k].name : k).join(", ") : ""
              }

              Choice {
                text: "Roll advancement"
                tooltipText: "At the end of a session: each marked skill may go up one"
                onClicked: root.act(["advance"], "roll")
              }
            }

            // Fight: the GM starts and ends it; the clicks here are the pure mechanics.

            Heading { text: root.fight ? "Fight · round " + root.fight.round : ""; visible: root.fight !== null }

            Line {
              visible: root.fight !== null
              size: Style.font.caption
              color: root.dim
              text: "Initiative: " + root.orderText()
            }

            Repeater {
              model: root.foeIds.length
              delegate: Card {
                id: foeCard
                required property int index
                readonly property string modelData: root.foeIds[index] || ""
                readonly property var foe: root.fight && root.fight.foes[modelData] ? root.fight.foes[modelData] : ({ name: "", hp: 0, max: 1, armor: 0, down: true })
                clickable: !foe.down
                selected: !foe.down && root.aimedAt() === modelData
                opacity: foe.down ? 0.5 : 1
                onClicked: root.target = modelData

                Meter {
                  label: foeCard.foe.name + (foeCard.foe.down ? " (down)" : foeCard.foe.armor ? " · armor " + foeCard.foe.armor : "")
                  value: foeCard.foe.hp
                  maximum: foeCard.foe.max
                }

                Choice {
                  visible: !foeCard.foe.down && !root.dead && !(root.fight && root.fight.incoming)
                  text: "Attacks you"
                  tooltipText: "Roll this foe's attack"
                  onClicked: root.act(["enemy", foeCard.modelData], "fight")
                }
              }
            }

            Line {
              visible: root.fight !== null && !root.dying && !root.dead && root.standing().length > 0 && !root.fight.incoming
              size: Style.font.caption
              color: root.dim
              text: "Attack the selected foe (boons and banes above apply):"
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.fight !== null && !root.dying && !root.dead && root.standing().length > 0 && !root.fight.incoming

              Repeater {
                model: root.kit.weapons.filter(w => w.attack)
                delegate: Choice {
                  required property var modelData
                  text: modelData.label + " " + modelData.damage + root.weaponNote(modelData)
                  tooltipText: modelData.condition === "broken" ? "Broken: mend it first" : modelData.condition === "damaged" ? "Damaged: a bane on every use until it is mended" : ""
                  enabled: modelData.condition !== "broken" && root.waiting === null
                  opacity: enabled ? 1 : 0.4
                  onClicked: root.attack(modelData.id)
                }
              }
            }

            Riders {
              visible: root.fight !== null && !root.dying && !root.dead && root.standing().length > 0 && !root.fight.incoming && choices.length > 0
              scope: "attack"
            }

            Line {
              visible: root.fight !== null && !!root.fight.incoming
              color: theme.urgentText
              font.bold: true
              text: root.fight && root.fight.incoming ? root.fight.incoming.name + " hits: " + root.fight.incoming.damage
                + " damage" + (root.kit.armor ? ", armor " + root.kit.armor : "") : ""
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.fight !== null && !!root.fight.incoming

              Choice {
                visible: !root.dying && root.fight !== null && !!root.fight.incoming && root.fight.incoming.can_defend !== false
                text: "Evade"
                onClicked: root.act(["defend", "evade"].concat(root.useArgs("defend", "dodge")), "fight", () => root.spent("defend", "dodge"))
              }

              Repeater {
                model: !root.dying && root.fight && root.fight.incoming && root.fight.incoming.can_defend !== false
                  && root.fight.incoming.can_parry !== false ? root.kit.weapons.filter(w => w.parry) : []
                delegate: Choice {
                  required property var modelData
                  text: "Parry: " + modelData.label + root.weaponNote(modelData)
                  tooltipText: modelData.condition === "broken" ? "Broken: mend it first" : ""
                  enabled: modelData.condition !== "broken"
                  opacity: enabled ? 1 : 0.4
                  onClicked: root.act(["defend", "parry", "--with", modelData.id].concat(root.useArgs("defend", "parry")), "fight", () => root.spent("defend", "parry"))
                }
              }

              Choice {
                text: "Take it"
                onClicked: root.act(["defend", "take"], "fight")
              }
            }

            Riders {
              visible: root.fight !== null && !root.dying && !root.dead && choices.length > 0
              scope: "defend"
            }

            Riders {
              visible: root.fight !== null && !root.dying && !root.dead && choices.length > 0
              scope: "round"
            }

            Choice {
              visible: root.fight !== null && !root.dead
              text: "Next round"
              tooltipText: "Deal new initiative cards"
              onClicked: root.act(["fight", "--round"].concat(root.useArgs("round", "")), "fight", () => root.spent("round", ""))
            }

            ErrorLine { place: "fight" }

            // Rest

            Heading { text: "Rest"; visible: root.pc !== null && !root.dead && Object.keys(root.labels.rests).length > 0 }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.pc !== null && !root.dead

              Repeater {
                model: root.pc ? Object.keys(root.labels.rests) : []
                delegate: Choice {
                  required property string modelData
                  readonly property bool used: root.restUsed(modelData)
                  readonly property bool blocked: used || root.fight !== null || root.dying || root.dead
                  text: root.labels.rests[modelData].label
                  tooltipText: used ? "Already taken this shift" : root.fight ? "Not during a fight" : "Recover and let time pass"
                  enabled: !blocked
                  opacity: blocked ? 0.4 : 1
                  onClicked: root.act(["rest", modelData].concat(root.tend && root.labels.rests[modelData].tend ? ["--tend"] : []).concat(root.useArgs("rest", modelData)),
                                      "rest", () => root.spent("rest", modelData))
                }
              }

              Choice {
                visible: !root.dead && Object.keys(root.labels.rests).some(k => root.labels.rests[k].tend)
                text: "Tend my wounds"
                tooltipText: "At a stretch rest: a HEALING roll for more HP"
                selected: root.tend
                onClicked: root.tend = !root.tend
              }
            }

            Riders {
              visible: root.fight === null && !root.dying && !root.dead && choices.length > 0
              scope: "rest"
            }

            ErrorLine { place: "rest" }

            // Light: a torch burns down as game time passes.

            RowLayout {
              Layout.fillWidth: true
              visible: root.pc !== null && !root.dead && (!!(root.game && root.game.light) || root.carriesTorch())

              Line {
                size: Style.font.bodySmall
                color: root.game && root.game.dark && !root.game.light ? theme.urgentText : root.textColor
                text: root.game && root.game.light ? root.game.light.label + ": " + root.hours(root.game.light.left) + " left"
                  : root.game && root.game.dark ? "It is dark here." : "No light burning."
              }

              Choice {
                text: root.game && root.game.light ? "Put it out" : "Light a torch"
                onClicked: root.act(root.game && root.game.light ? ["light", "--out"] : ["light", "torch"], "light")
              }
            }

            ErrorLine { place: "light" }
            ErrorLine { place: "book" }

            // Oracle

            Heading { text: "Oracle"; visible: root.pc !== null && !root.dead }

            TextField {
              id: question
              objectName: "question"
              visible: root.pc !== null && !root.dead
              Layout.fillWidth: true
              placeholderText: "Ask a question"
              onAccepted: root.askOracle()
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.pc !== null && !root.dead && !!root.labels.fortune

              Repeater {
                model: root.labels.fortune || []
                delegate: Choice {
                  required property string modelData
                  text: modelData.replace("_", "/")
                  tooltipText: ({ yes_no: "Yes or no?", number: "How many?", scale: "How big?", power: "How strong?",
                                  quality: "How fine?", reaction: "How do they react?" })[modelData] || ""
                  selected: root.oracleKind === modelData
                  onClicked: root.oracleKind = modelData
                }
              }
            }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)
              visible: root.pc !== null && !root.dead

              Repeater {
                model: root.labels.likelihood
                delegate: Choice {
                  required property string modelData
                  text: modelData
                  selected: root.odds === modelData || (root.odds === "even" && modelData === "50/50")
                  onClicked: root.odds = modelData
                }
              }
            }

            RowLayout {
              Layout.fillWidth: true
              visible: root.pc !== null && !root.dead

              Choice {
                Layout.fillWidth: true
                text: "Ask"
                tooltipText: "Or press Enter in the question"
                selected: true
                onClicked: root.askOracle()
              }

              Choice {
                text: "Meaning"
                tooltipText: "Words to read for a question a yes or no can't answer"
                onClicked: root.askMeaning()
              }
            }

            Line {
              visible: root.lastOracle() !== "" && !root.dead
              size: Style.font.bodySmall
              text: root.lastOracle()
            }

            ErrorLine { place: "oracle" }

            // The world

            Heading { text: "Clocks"; visible: root.visibleClocks().length > 0 }

            Repeater {
              model: root.visibleClocks()
              delegate: ColumnLayout {
                id: clockRow
                required property var modelData
                Layout.fillWidth: true
                spacing: Style.space(2)

                Line { text: clockRow.modelData.label + "  " + clockRow.modelData.value + "/" + clockRow.modelData.segments }

                Row {
                  spacing: Style.space(3)

                  Repeater {
                    model: clockRow.modelData.segments
                    delegate: Rectangle {
                      required property int index
                      width: Style.space(14)
                      height: Style.space(6)
                      radius: 2
                      color: index < clockRow.modelData.value ? Shell.Color.urgent : root.faint
                    }
                  }
                }
              }
            }

            Heading { text: "People"; visible: root.people().length > 0 }

            Repeater {
              model: root.people()
              delegate: Line {
                required property var modelData
                text: modelData.name + ": " + root.attitude(modelData.attitude) + (modelData.fate !== "alive" ? ", " + modelData.fate : "")
              }
            }

            Heading { text: "Promises"; visible: root.promises().length > 0 }

            Repeater {
              model: root.promises()
              delegate: Line {
                required property string modelData
                text: modelData
              }
            }

            Heading { text: "Clues"; visible: root.game !== null && root.game.clues.length > 0 }

            Flow {
              Layout.fillWidth: true
              spacing: Style.space(4)

              Repeater {
                model: root.game ? root.game.clues : []
                delegate: Tag {
                  required property string modelData
                  label: modelData.replace(/_/g, " ")
                }
              }
            }

            Heading { text: "Gear"; visible: root.pc !== null && (root.pc.items.length > 0 || root.worn().length > 0) }

            Line {
              visible: root.pc !== null && root.pc.items.length > 0
              size: Style.font.bodySmall
              text: root.pc ? root.pc.items.join(", ") : ""
            }

            Line {
              visible: root.game !== null && !!root.game.load
              size: Style.font.bodySmall
              color: root.game && root.game.load && root.game.load.over ? theme.urgentText : root.dim
              text: root.game && root.game.load ? "Carrying " + root.game.load.carried + " of " + root.game.load.capacity + (root.game.load.over ? ": over the load" : "") : ""
            }

            Repeater {
              model: root.pc && !root.dead ? root.worn() : []
              delegate: RowLayout {
                id: mending
                required property var modelData
                Layout.fillWidth: true
                spacing: Style.space(4)

                Line { text: "The " + mending.modelData.label.toLowerCase() + " is " + mending.modelData.condition; size: Style.font.bodySmall }

                Choice {
                  text: "Mend"
                  tooltipText: "A roll to mend it"
                  enabled: !action.running
                  onClicked: root.act(["repair", mending.modelData.id], "gear")
                }

                Choice {
                  text: "Artisan"
                  tooltipText: "An artisan mends it, with no roll"
                  enabled: !action.running
                  onClicked: root.act(["repair", mending.modelData.id, "--artisan"], "gear")
                }
              }
            }

            ErrorLine { place: "gear" }

            Heading { text: "Table settings"; visible: root.prefsText() !== "" }

            Line {
              visible: root.prefsText() !== ""
              size: Style.font.bodySmall
              color: root.dim
              text: root.prefsText()
            }

            Heading { text: "Log"; visible: root.game !== null }

            Repeater {
              model: root.recent()
              delegate: Line {
                required property var modelData
                size: Style.font.bodySmall
                color: modelData.type === "check" || modelData.type === "push" ? root.textColor : root.dim
                text: modelData.text
              }
            }

          }
        }
      }
    }
    BorderSurface {
      id: settingsSurface
      objectName: "settingsSurface"
      anchors.fill: parent
      color: Shell.Color.popups.background
      borderSpec: hyprAppearance.active ? hyprAppearance.borderSpec : Border.flat(Shell.Color.popups.border, 1)
      radius: hyprAppearance.rounding
      visible: tableFlip.side === Flipable.Back
      SettingsView {
        id: settingsView
        anchors.fill: parent
        anchors.margins: Style.space(12)
        enabled: root.settingsOpen && !tableFlip.flipping
        theme: theme
        bookScale: root.bookScale
        tableScale: root.tableScale
        scaleBusy: root.scaleBusy
        scaleTarget: root.scaleTarget
        scaleError: root.scaleError
        onScaleRequested: (target, value) => root.setUiScale(target, value)
        honorHyprland: root.honorHyprland
        hyprlandError: hyprAppearance.error
        onHonorHyprlandRequested: on => root.setHonorHyprland(on)
        pace: root.pace
        effects: root.effects
        bookSupported: root.agentInfo.book !== false
        busy: action.running || query.running
        errorPlace: root.errorAt
        errorText: root.error
        onDismissed: root.settingsOpen = false
        onPaceRequested: value => root.setPace(value)
        onEffectRequested: (name, on) => root.setEffect(name, on)
      }
    }
  }
}
