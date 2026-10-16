import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
// Qualified: from Qt 6.12 QtQuick has a Color of its own, which a bare Color would mean.
import qs.Commons as Commons
import qs.Ui
import "book"
import "book/Common.js" as Common
import "table" as Table

// oma-solorpg on the desktop: two windows and a watcher.
//
// - The Book (book/BookView.qml): where the story is read and told. The default agent
//   writes in it as GM, run headless one turn at a time by `solo gm turn`.
// - The Table: a sidebar docked on the right. Home (your campaigns and the Hall of the
//   Fallen), New adventure (pick an adventure and a hero, then begin) and Table (sheet,
//   rolls, spells and abilities, fights and a Dragon's choice, death rolls, rests, light,
//   gear and what is broken, oracle, clocks, log). Its widgets are in table/.
// - The watcher: while a game is on, the desktop joins in (solo desk): a Dragon flashes
//   the window borders and the screen gold, a Demon red, a blow jolts the screen, dying
//   holds a red rim round it and death greys it, omens ripple it and arrive as
//   notifications, the table has sounds, and the screen warms like candlelight while the
//   Book is open (table/DeskWatcher.qml).
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
  property bool opened: false

  readonly property string solo: decodeURIComponent(Qt.resolvedUrl("bin/solo").toString().replace(/^file:\/\//, ""))
  readonly property string campaign: currentFile.campaign
  // The current campaign, when it can't be opened: its folder was moved or deleted, or (lostWhy, in the engine's
  // words) its state.json is missing and solo couldn't make it again from the log.
  property string lost: ""
  property string lostWhy: ""
  property var game: null
  property var library: null
  // The campaign whose card is asking "delete for good?", by folder.
  property string deleting: ""
  property string view: "home"
  // What went wrong and where, what a command said it did, the commands waiting and whether the
  // Table is busy. The runner keeps them (table/SoloRunner.qml says how); the Table and the Book
  // read them here.
  property alias error: runner.error
  property alias queryError: runner.queryError
  property alias notice: runner.notice
  property alias queue: runner.queue
  property alias busy: runner.busy

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
  property string pace: "normal"  // how long the GM thinks before it answers (solo gm pace)
  // Which desktop effects are on, and the table's sounds: the watcher's (table/DeskWatcher.qml).
  property alias effects: watcher.effects
  property alias sounds: watcher.sounds

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
  // The push ability (Sole Survivor), when the hero has it: a push paid with willpower instead of a condition.
  readonly property bool pushAbility: pc !== null && !!labels.push_ability && (pc.abilities || []).indexOf(labels.push_ability.name) >= 0
  // A failed roll that can still be pushed, and something to pay for it: a condition not taken yet where that is the
  // cost (the engine refuses a push with every one taken), or the push ability.
  readonly property bool canPush: !dead && !dying && pc !== null && lastCheck !== null && lastCheck.type === "check" && lastCheck.outcome.pushable === true
    && (labels.push !== "condition" || labels.conditions.some(c => pc.conditions.indexOf(c) === -1) || pushAbility)
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
  // The system pack the engine plays the adventure on (system_id): it finds one by its slug, so an adventure may name it
  // in other capitals ("Ironsworn" for ironsworn).
  readonly property var system: adventure ? library.systems.filter(s => s.id === adventure.system_id)[0] || null : null

  readonly property color textColor: Commons.Color.popups.text
  // Captions and asides: as quiet as WCAG AA lets small text be (4.5:1), on light themes as on dark. Measured
  // on the Book's panels and the Table's hovered cards (theme.surface, a shade toward the text), where it reads
  // least; on the page it reads more.
  readonly property color dim: Common.fade(Commons.Color.popups.text, theme.surface, 4.6, 0.5)
  readonly property color faint: Qt.rgba(textColor.r, textColor.g, textColor.b, 0.15)
  // The panels' shade (theme.surface) as a fill over the Table, for what holds text: a hovered card. Faint is for
  // rails and borders only; on it dim would read under 4:1.
  readonly property color shade: Qt.rgba(textColor.r, textColor.g, textColor.b, 0.05)

  function open(payloadJson) {
    var payload = {}
    try {
      payload = JSON.parse(payloadJson || "{}")
    } catch (e) {
      payload = {}
    }
    currentFile.reload()
    root.opened = true
    root.show(payload.view || (root.campaign !== "" && root.lost === "" ? "table" : "home"))
    if (payload.book) root.openBook()
  }

  function openBook() {
    if (root.campaign !== "") {
      root.ask("agent", ["-C", root.campaign, "gm", "agent"], "book")
      // A turn that died unfinished (the machine went down) is written down as stopped,
      // so the Book doesn't wait on it; turn.json brings the news.
      root.ask("turn", ["-C", root.campaign, "gm", "status"], "book")
      root.bookOpen = true
    }
  }

  // The player's words to the GM (none: the GM carries on from what is recorded). They go
  // in on stdin, by way of the environment, never as an argument: the process list is
  // anyone's to read, a process's environment only its owner's.
  function speak(text) {
    // A campaign whose folder went has no GM to hear them: said at once, not after waiting on a turn that can't start.
    if (root.lost !== "") {
      root.turn = { status: "error", gone: true, error: root.gone(root.lost) }
      return
    }
    root.turn = { status: "thinking", player: text, text: "", doing: "reading the table" }
    speaker.command = ["sh", "-c", 'printf %s "$SOLO_SAY" | exec "$@"', "speak", root.solo, "-C", root.campaign, "gm", "turn", "--", "-"]
    speaker.environment = { SOLO_SAY: text }
    speaker.startDetached()
    watchdog.said = text
    watchdog.waiting = true
    watchdog.restart()
  }

  // The X-card: cut the GM's last message (a line or a veil too, if the player made it one), then the GM carries on without it.
  // What the player typed goes as --flag=value, so words that start with a dash stay words. The cut is in the campaign it
  // was asked in; when another is current by the time it is done (one picked while the cut waited, or from a terminal),
  // that one's GM isn't asked to carry on from a cut it never had.
  function cut(note, line, veil) {
    var asked = root.campaign
    root.act(["strike"].concat(note !== "" ? ["--note=" + note] : []).concat(line !== "" ? ["--line=" + line] : [])
               .concat(veil !== "" ? ["--veil=" + veil] : []), "cut",
             () => {
               bookView.cutDone(true)
               if (root.campaign === asked) root.speak("")
             }, () => bookView.cutDone(false))
  }

  // A turn writes turn.json as soon as it starts, and the Book waits on it. One that never
  // got that far (another turn holds the lock, words too long for the environment, a
  // campaign folder gone) is sent with nobody to hear: if turn.json hasn't changed a while
  // after a send, `solo gm status` says what is going on, and the Book stops waiting. A
  // healthy turn can take five seconds to begin, ending an agent an earlier turn left
  // running (gm.py's _reap), so the wait is twice that.
  Timer {
    id: watchdog
    objectName: "watchdog"
    property string said: ""
    // Words sent, and turn.json not changed since. Once it has, it is newer than any status asked for before.
    property bool waiting: false
    interval: 10000
    onTriggered: root.ask("watchdog", ["-C", root.campaign, "gm", "status"], "watchdog")
  }

  // The desktop joins in while a game is on (table/DeskWatcher.qml).
  Table.DeskWatcher {
    id: watcher
    solo: root.solo
    campaign: root.campaign
    game: root.game
    bookOpen: root.bookOpen
  }

  // The game belongs to its campaign: another one picked, or this one deleted, drops the game
  // (and the watcher lets go of what it held on the desktop).
  onCampaignChanged: {
    root.game = null
    root.lost = ""
    root.lostWhy = ""
    root.turn = { status: "idle" }
    watchdog.stop()
    watchdog.waiting = false
  }
  // After a shell restart or a crash, nothing from an old session stays on the desktop.
  Component.onCompleted: {
    Quickshell.execDetached([root.solo, "desk", "restore"])
    root.ask("effects", ["desk", "settings"])
    root.ask("sounds", ["desk", "sound"], "effects")
    root.ask("pace", ["gm", "pace"])
  }

  function close() {
    root.opened = false
  }

  function show(view) {
    root.view = view
    root.deleting = ""
    root.error = { text: "", place: "" }
    root.queryError = { text: "", place: "" }
    root.notice = { text: "", place: "" }
    if (view !== "table") {
      root.ask("library", ["library"])
    }
  }

  // Commands that change something: the runner runs them one at a time, in the order asked for
  // (table/SoloRunner.qml).
  function run(args, place, done, failed) {
    runner.run(args, place, done, failed)
  }

  function setPace(pace) {
    root.run(["gm", "pace", pace], "pace", () => root.ask("pace", ["gm", "pace"]))
  }

  // The GM in a terminal of its own (or its window brought forward): what solo did about it is said where it was asked.
  // That is its last line; the ones before it are for a terminal (each link `solo play` made for solo and the skills).
  function openTerminal(place) {
    root.run(["play", root.campaign, "--terminal"], place, said => root.notice = { text: said.trim().split("\n").pop(), place: place })
  }

  function act(args, place, done, failed) {
    if (root.campaign !== "") {
      root.run(["-C", root.campaign].concat(args), place, done, failed)
    } else {
      root.error = { text: "No campaign is open.", place: place }
      if (failed) failed()
    }
  }

  // Commands that only read: the runner runs them one at a time too, the latest of each kind
  // waiting its turn (table/SoloRunner.qml).
  function ask(kind, args, place) {
    runner.ask(kind, args, place)
  }

  // What went wrong at a place, from the commands or the reads.
  function errorsAt(place) {
    return runner.errorsAt(place)
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
    } else if (kind === "watchdog") {
      root.unheard(data)
    } else if (kind.indexOf("mend:") === 0) {
      root.mended(kind.slice(5), data !== null)
    }
  }

  // The current campaign's state.json can't be read. With its campaign.toml there, the folder is a campaign, and every
  // solo command makes state.json again from the log: one that only reads is run, and the file's watch brings the game
  // when it is written. Otherwise, or when that command fails too, the campaign is lost and Home says why. The ask is
  // the campaign's own kind, so one asked for another campaign meanwhile doesn't take its place.
  function mend() {
    root.game = null
    if (root.campaign === "") return
    campaignFile.reload()
    if (campaignFile.there) root.ask("mend:" + root.campaign, ["-C", root.campaign, "state"])
    else root.lose("")
  }

  function mended(campaign, ok) {
    var why = root.queryError.place === "mend:" + campaign ? root.queryError.text : ""
    if (why !== "") root.queryError = { text: "", place: "" }
    // Another campaign was picked meanwhile, or the game came back: what was asked is old news.
    if (!ok && campaign === root.campaign && root.game === null) root.lose(why)
  }

  // `why` is the engine's sentence, or "" for a folder that is gone.
  function lose(why) {
    root.lost = root.campaign
    root.lostWhy = why
    if (root.view === "table") root.show("home")
  }

  // The current campaign's card: its table, with state.json read again when it was lost (put back by hand, say).
  function reopen() {
    root.show("table")
    if (root.lost !== "") {
      root.lost = ""
      root.lostWhy = ""
      stateFile.reload()
    }
  }

  // What `solo gm status` said when a turn didn't start. One running after all (another
  // turn, say) is the Book's to show; otherwise the words were never heard, and "try again"
  // sends them again.
  function unheard(status) {
    var why = root.queryError.place === "watchdog" ? root.queryError.text : ""
    if (why !== "") root.queryError = { text: "", place: "" }
    // The turn began while `solo gm status` ran (or another campaign was picked): what it
    // said is older than turn.json, and a turn under way would be called unsent.
    if (!watchdog.waiting) return
    watchdog.waiting = false
    if (status && (status.status === "thinking" || status.status === "writing")) {
      root.turn = status
    } else if (root.turn.status === "thinking" && root.lost !== "") {
      // The campaign's folder went after the words were sent: trying again would never get them heard.
      root.turn = { status: "error", gone: true, error: root.gone(root.lost) }
    } else if (root.turn.status === "thinking") {
      root.turn = { status: "error", unsent: watchdog.said,
                    error: (why !== "" ? (/[.?!]$/.test(why) ? why : why + ".") + " " : "") + "The GM didn't start, and your words weren't recorded: try again to send them." }
    }
  }

  // Why a campaign whose folder was moved or deleted (its state.json can't be read) can't be played: Home and the Book say it.
  function gone(folder) {
    return "The campaign in " + folder + " can't be read: its folder was moved or deleted. Pick another, or begin a new one."
  }

  // Home: another campaign picked, or one deleted for good.
  function useCampaign(path) {
    root.run(["use", path], "home", () => root.show("table"))
  }

  function deleteCampaign(path, wasCurrent) {
    root.run(["delete", path, "--yes"], "home", () => {
      root.deleting = ""
      if (wasCurrent) root.bookOpen = false
      root.show("home")
    })
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
    if (!root.adventure || root.adventure.system_id !== adventure.system_id) {
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
    // `solo new --play` brings the Book up itself when the GM writes in it; with no agent set up, or one in a
    // terminal, it doesn't, and the Book opened here says why and how to set one up.
    root.run(args, "begin", () => {
      root.heroName = ""
      root.show("table")
      root.openBook()
    })
  }

  function split(text) {
    return text.split(",").map(t => t.trim()).filter(t => t !== "")
  }

  // The engine's words for a terminal mark a command `like this`; the panel shows them as plain text.
  function plain(text) {
    return (text || "").replace(/`/g, "")
  }

  // Packs that didn't load, but for a system an adventure on the list already says why it can't begin
  // (under its card): that is said once, there.
  function notLoaded() {
    if (!root.library) return []
    var told = root.library.adventures.filter(a => a.ready === false && (a.why || "") !== "").map(a => "system " + a.system + ":")
    return (root.library.problems || []).filter(p => !told.some(t => p.startsWith(t)))
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
      root.error = { text: "Name it first: a vow, a road or a foe.", place: "track" }
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
      root.error = { text: "Type a yes/no question first.", place: "oracle" }
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

  function parry(weapon) {
    root.act(["defend", "parry", "--with", weapon].concat(root.useArgs("defend", "parry")), "fight", () => root.spent("defend", "parry"))
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
    root.act(["prepare", "--drop=" + spell.name, "--", root.preparing], "magic", () => root.preparing = "")
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
    // A move says the stat it added; a skill roll's label is the skill already.
    var what = check.stat && check.outcome.hit !== undefined ? " +" + check.stat : check.track_name ? " (" + check.track_name + ")" : ""
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
    return outcome && outcome.dragon ? theme.gold : outcome && !outcome.success ? Commons.Color.urgent
      : outcome && (outcome.successes > 1 || outcome.hit === "strong_hit") ? Commons.Color.accent : root.textColor
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

  // Which campaign is current (book/CurrentCampaign.qml). Read synchronously so open()
  // already knows whether to show Home or the table, and re-read on open and after every
  // command, so a game begun here is followed at once.
  CurrentCampaign {
    id: currentFile
    blockLoading: true
  }

  FileView {
    id: stateFile
    path: root.campaign !== "" ? root.campaign + "/state.json" : ""
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      root.lost = ""
      root.lostWhy = ""
      try {
        root.game = JSON.parse(text())
      } catch (e) {
        console.warn("solo-play", "Ignoring unreadable state.json", e)
      }
    }
    // Gone, or never written: `solo use` makes a campaign current without opening it. solo makes it again, or
    // Home says why it can't, rather than the table loading for good.
    onLoadFailed: root.mend()
  }

  // The current campaign's campaign.toml, read only to tell a folder that is gone from a state.json that is.
  FileView {
    id: campaignFile
    property bool there: false
    path: root.campaign !== "" ? root.campaign + "/campaign.toml" : ""
    blockLoading: true
    printErrors: false
    onLoaded: there = true
    onLoadFailed: there = false
  }

  // The GM's turn in progress, written by `solo gm turn` as it streams.
  FileView {
    path: root.campaign !== "" ? root.campaign + "/.solo/turn.json" : ""
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      watchdog.stop()  // the turn has started
      watchdog.waiting = false
      try {
        root.turn = JSON.parse(text())
      } catch (e) {
        // Caught mid-write; the next change brings the whole file.
      }
    }
  }

  // Omarchy's theme, in the words the Book uses. The Book is plain QtQuick and reads only this.
  QtObject {
    id: theme
    readonly property color text: Commons.Color.popups.text
    readonly property color dim: root.dim
    // Rules, borders, blanks and what can't be clicked: quieter still, at 3:1, what WCAG asks of lines and controls,
    // on the panels as on the page.
    readonly property color faint: Common.fade(text, surface, 3, 0.65)
    readonly property color background: Commons.Color.popups.background
    readonly property color surface: Qt.tint(Commons.Color.popups.background, Qt.rgba(text.r, text.g, text.b, 0.05))
    readonly property color accent: Commons.Color.accent
    readonly property color urgent: Commons.Color.urgent
    // Dragons and candlelight: one warm gold that reads on dark and light themes alike.
    readonly property color gold: "#d9a441"
    readonly property string mono: Commons.Style.font.family
    readonly property string serif: "serif"
    readonly property real small: Commons.Style.font.bodySmall
    readonly property real body: Commons.Style.font.body
    readonly property real prose: Math.round(Commons.Style.font.body * 1.5)
    readonly property real title: Commons.Style.font.title
    readonly property real heading: Math.round(Commons.Style.font.heading * 1.2)
    readonly property real display: Commons.Style.font.display
    readonly property real radius: Commons.Style.cornerRadius
  }

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

    BookView {
      id: bookView
      objectName: "book"
      anchors.fill: parent
      theme: theme
      game: root.game
      turn: root.turn
      agent: root.agentInfo
      campaign: root.campaign
      actionError: root.errorsAt("book")
      cutError: root.errorsAt("cut")
      actionNote: root.notice.place === "book" ? root.notice.text : ""
      active: bookWindow.visible
      onSend: text => root.speak(text)
      onStop: Quickshell.execDetached([root.solo, "-C", root.campaign, "gm", "stop"])
      onRetry: root.speak(root.turn.unsent || "")
      onCut: (note, line, veil) => root.cut(note, line, veil)
      onAct: args => root.act(args, "book")
      // The Table, or Home when the campaign's folder went (where it says so, and another is picked).
      onOpenTable: {
        root.opened = true
        root.show(root.lost !== "" ? "home" : "table")
      }
      onOpenTerminal: root.openTerminal("book")
    }
  }

  Process {
    id: speaker
  }

  // What runs solo for the Table and the Book (table/SoloRunner.qml). When a command ends, which
  // campaign is current is read again; what a read printed comes back here, to received().
  Table.SoloRunner {
    id: runner
    solo: root.solo
    currentFile: currentFile
    onReceived: (kind, text) => root.received(kind, text)
  }

  // The Table's widgets are in table/, a file each, and what they read from the Panel is given
  // them here, once for every use: the Table's colours, and to an ErrorLine what went wrong at
  // its place.
  component Line: Table.Line { color: root.textColor }
  component Heading: Table.Heading { color: root.dim }
  component ErrorLine: Table.ErrorLine { text: root.errorsAt(place) }
  component Fold: Table.Fold { textColor: root.textColor; dim: root.dim }
  component Tag: Table.Tag { textColor: root.textColor; dim: root.dim; faint: root.faint }
  component Choice: Table.Choice { foreground: root.textColor }

  // A button that runs a command. It waits, greyed, while one runs, so a double click can't do
  // the same thing twice.
  component Act: Choice {
    enabled: !root.busy
    opacity: enabled ? 1 : 0.5
  }

  component Primary: Table.Primary { foreground: root.textColor }
  component Card: Table.Card { textColor: root.textColor; faint: root.faint; shade: root.shade }

  component Stepper: RowLayout {
    id: stepper
    property string label: ""
    property int value: 0
    property int from: 0
    property int to: 5
    signal stepped(int value)
    spacing: Commons.Style.space(4)

    Line { Layout.fillWidth: false; text: stepper.label; size: Commons.Style.font.bodySmall }
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
    spacing: Commons.Style.space(4)
    visible: choices.length > 0 && root.pc !== null && !root.dying && !root.dead

    Line {
      Layout.fillWidth: false
      size: Commons.Style.font.caption
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
    spacing: Commons.Style.space(2)

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
      implicitHeight: Commons.Style.space(8)
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
        color: bar.track.value < 0 ? Commons.Color.urgent : Commons.Color.accent
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
    spacing: Commons.Style.space(2)

    Repeater {
      model: root.progressSpec ? root.progressSpec.boxes : 0
      delegate: Rectangle {
        required property int index
        width: Commons.Style.space(20)
        height: Commons.Style.space(12)
        color: "transparent"
        border.width: 1
        border.color: root.dim

        Rectangle {
          anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 1 }
          height: (parent.height - 2) * root.boxTicks(boxes.track, index) / (root.progressSpec ? root.progressSpec.ticks : 4)
          color: Commons.Color.accent
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
    spacing: Commons.Style.space(2)

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
      implicitHeight: Commons.Style.space(6)
      radius: height / 2
      color: root.faint

      // What was just lost lingers a moment in red, then drains away.
      Rectangle {
        width: track.width * meter.share
        height: parent.height
        radius: parent.radius
        color: Commons.Color.urgent
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
        color: meter.share <= 0.25 ? Commons.Color.urgent : meter.share <= 0.5 ? theme.gold : Commons.Color.accent
        Behavior on width { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: 400 } }
      }
    }
  }

  PanelWindow {
    visible: root.opened
    anchors { top: true; right: true; bottom: true }
    implicitWidth: Commons.Style.space(340)
    color: "transparent"
    exclusionMode: ExclusionMode.Auto
    WlrLayershell.namespace: "solo-play"
    WlrLayershell.layer: WlrLayer.Top
    // Clicking the name or oracle field takes the keyboard; nothing else needs it.
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

    Rectangle {
      anchors.fill: parent
      anchors.margins: Commons.Style.gapsOut
      color: Commons.Color.popups.background
      border.width: 1
      border.color: Commons.Color.popups.border
      radius: Commons.Style.cornerRadius

      Flickable {
        anchors.fill: parent
        anchors.margins: Commons.Style.space(12)
        contentHeight: column.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        focus: true
        Keys.onEscapePressed: root.close()

        // What Tab reaches on the Table (a fold, a card, a field) is scrolled into view, so Enter or Space never
        // acts out of sight on a screen too short for all of it.
        readonly property Item focused: Window.activeFocusItem
        onFocusedChanged: {
          var up = focused
          while (up && up !== contentItem) up = up.parent
          if (!up) return
          var top = focused.mapToItem(contentItem, 0, 0).y
          if (top + focused.height > contentY + height) contentY = Math.max(0, Math.min(top + focused.height - height, contentHeight - height))
          if (top < contentY) contentY = Math.max(0, top)
        }

        ColumnLayout {
          id: column
          width: parent.width
          spacing: Commons.Style.space(6)

          // Header ------------------------------------------------------------------

          RowLayout {
            Layout.fillWidth: true
            spacing: Commons.Style.space(4)

            Line {
              text: root.view === "new" ? "New adventure" : root.view === "table" && root.game ? root.game.title : "oma-solorpg"
              size: Commons.Style.font.heading
              font.bold: true
              elide: Text.ElideRight
              wrapMode: Text.NoWrap
            }

            Choice {
              visible: root.view === "table"
              text: "Campaigns"
              onClicked: root.show("home")
            }

            Choice {
              visible: root.view === "new"
              text: "Back"
              onClicked: root.show("home")
            }

            Choice {
              text: "×"
              tooltipText: "Close (Esc)"
              onClicked: root.close()
            }
          }

          // Home --------------------------------------------------------------------

          ColumnLayout {
            visible: root.view === "home"
            Layout.fillWidth: true
            spacing: Commons.Style.space(6)

            Line {
              objectName: "lost"
              visible: root.lost !== ""
              color: Commons.Color.urgent
              size: Commons.Style.font.bodySmall
              text: root.lostWhy !== "" ? root.lostWhy : root.gone(root.lost)
            }

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
                name: modelData.title
                selected: modelData.current
                clickable: root.deleting !== modelData.path
                onClicked: modelData.current ? root.reopen() : root.useCampaign(modelData.path)

                Line { text: modelData.title; font.bold: true }
                Line {
                  size: Commons.Style.font.bodySmall
                  text: [modelData.hero + (modelData.info ? ", " + modelData.info : ""), modelData.scene].filter(t => t !== "").join(" · ")
                }
                Line {
                  visible: (modelData.said || "") !== ""
                  size: Commons.Style.font.bodySmall
                  color: root.dim
                  maximumLineCount: 2
                  elide: Text.ElideRight
                  text: modelData.said || ""
                }
                Line {
                  visible: (modelData.ended || "") !== ""
                  size: Commons.Style.font.bodySmall
                  font.italic: true
                  text: "Ended: " + (modelData.ended || "")
                }
                RowLayout {
                  Layout.fillWidth: true
                  visible: root.deleting !== modelData.path
                  Line {
                    size: Commons.Style.font.caption
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
                  Layout.topMargin: Commons.Style.space(4)
                  size: Commons.Style.font.bodySmall
                  color: Commons.Color.urgent
                  text: "Delete this campaign for good? The story, " + (modelData.hero || "the hero") + " and the whole log go with it"
                        + (modelData.dead ? ", and " + modelData.hero + " leaves the Hall of the Fallen." : ".")
                }
                RowLayout {
                  visible: root.deleting === modelData.path
                  spacing: Commons.Style.space(4)
                  Act {
                    text: runner.action.job !== null && runner.action.job.place === "home" ? "Deleting…" : "Delete for good"
                    foreground: Commons.Color.urgent
                    onClicked: root.deleteCampaign(modelData.path, modelData.current)
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
                name: modelData.name
                clickable: false

                RowLayout {
                  Layout.fillWidth: true
                  spacing: Commons.Style.space(8)

                  Text {
                    textFormat: Text.PlainText
                    font.family: Commons.Style.font.family
                    font.pixelSize: Commons.Style.font.caption * 0.8
                    color: root.dim
                    text: modelData.portrait.join("\n")
                  }

                  ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Commons.Style.space(2)
                    Line { text: modelData.name; font.bold: true }
                    Line { size: Commons.Style.font.caption; color: root.dim; text: modelData.info }
                    Line {
                      size: Commons.Style.font.bodySmall
                      text: "Fell in " + (modelData.scene || "the dark") + (modelData.by ? " to " + modelData.by : "") + ", " + modelData.adventure + "."
                    }
                    Line {
                      visible: modelData.epitaph !== ""
                      size: Commons.Style.font.bodySmall
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
            spacing: Commons.Style.space(6)

            Heading { text: "1  Adventure" }

            Repeater {
              model: root.library ? root.library.adventures : []
              delegate: Card {
                required property var modelData
                name: modelData.title
                selected: root.adventure !== null && root.adventure.id === modelData.id
                onClicked: root.chooseAdventure(modelData)

                Line { text: modelData.title; font.bold: true }
                // The system by name (the engine gives it; from the systems that loaded, before it did), and what
                // the adventure waits for when it can't be played yet (picked, that is said under Hero instead).
                Line {
                  size: Commons.Style.font.caption
                  color: root.dim
                  text: modelData.system_name
                    || (root.library.systems.filter(s => s.id === modelData.system_id)[0] || { name: modelData.system || "no system named" }).name
                }
                Line {
                  visible: modelData.ready === false && (modelData.why || "") !== "" && (root.adventure === null || root.adventure.id !== modelData.id)
                  size: Commons.Style.font.caption
                  color: root.dim
                  text: root.plain(modelData.why)
                }
                Line { visible: modelData.summary !== ""; size: Commons.Style.font.bodySmall; text: modelData.summary }
              }
            }

            // Packs of your own that didn't load (half-built from a book, say), and why.
            Repeater {
              model: root.notLoaded()
              delegate: Line {
                required property string modelData
                size: Commons.Style.font.caption
                color: root.dim
                text: "Not loaded: " + root.plain(modelData)
              }
            }

            Heading { text: "2  Hero" }

            Line {
              visible: root.adventure !== null && root.system === null
              color: Commons.Color.urgent
              size: Commons.Style.font.bodySmall
              text: root.adventure && root.adventure.why
                ? root.plain(root.adventure.why) : "This adventure's system pack isn't installed, or its rules aren't built from your books yet."
            }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
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
                spacing: Commons.Style.space(3)

                Line { text: table.modelData.label; size: Commons.Style.font.caption; color: root.dim }

                Flow {
                  Layout.fillWidth: true
                  spacing: Commons.Style.space(4)

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
              spacing: Commons.Style.space(6)

              TextField {
                id: nameField
                Layout.fillWidth: true
                placeholderText: root.preview ? "Name: " + root.preview.name : "Name"
                text: root.heroName
                onTextEdited: root.heroName = text
                onAccepted: if (beginButton.enabled) root.begin()  // Enter: the hero is named, begin
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
                size: Commons.Style.font.title
                font.bold: true
              }
              Line {
                size: Commons.Style.font.bodySmall
                color: root.dim
                text: root.preview ? root.values(root.preview.info).join(" · ") : ""
              }
              Line {
                size: Commons.Style.font.bodySmall
                text: root.preview ? Object.keys(root.preview.attributes).map(k => k.toUpperCase() + " " + root.preview.attributes[k]).join("  ") : ""
              }
              Line {
                size: Commons.Style.font.bodySmall
                text: root.preview ? Object.keys(root.preview.tracks).map(k => k.toUpperCase() + " " + (root.preview.tracks[k].min !== undefined ? root.signed(root.preview.tracks[k].value) : root.preview.tracks[k].max))
                  .concat(Object.keys(root.preview.ratings).map(k => k + " " + root.preview.ratings[k])).join(" · ") : ""
              }
              Line {
                visible: root.preview !== null && Object.keys(root.preview.skills).length > 0
                size: Commons.Style.font.bodySmall
                text: root.preview ? "Trained: " + Object.keys(root.preview.skills).filter(k => root.preview.skills[k].trained)
                  .map(k => root.preview.skills[k].name + " " + root.preview.skills[k].value).join(", ") : ""
              }
              Line {
                visible: root.preview !== null && root.preview.abilities.length > 0
                size: Commons.Style.font.bodySmall
                text: root.preview ? "Abilities: " + root.preview.abilities.join(", ") : ""
              }
              Line {
                visible: root.preview !== null && root.preview.items.length > 0
                size: Commons.Style.font.bodySmall
                color: root.dim
                text: root.preview ? "Gear: " + root.preview.items.join(", ") : ""
              }
            }

            ErrorLine { place: "preview" }

            Heading { text: "3  Table settings (optional)" }

            Line {
              size: Commons.Style.font.caption
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
              id: beginButton
              text: runner.action.job !== null && runner.action.job.place === "begin" ? "Starting…" : "Begin adventure"
              enabled: root.adventure !== null && root.preview !== null && !root.busy
              opacity: enabled ? 1 : 0.5
              onClicked: root.begin()
            }

            Line {
              size: Commons.Style.font.caption
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
            spacing: Commons.Style.space(6)

            Line {
              visible: root.game === null
              color: root.dim
              text: root.campaign === "" ? "No campaign is open." : "Loading the table…"
            }

            Line {
              visible: root.game !== null
              color: root.dim
              size: Commons.Style.font.bodySmall
              text: root.game ? (root.game.scene_title || "") + " · " + Common.elapsed(root.game.time) : ""
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

              Act {
                text: "Terminal"
                tooltipText: "Open the GM in a terminal instead, or bring its window forward"
                onClicked: root.openTerminal("gm")
              }
            }

            ErrorLine { place: "gm" }

            Line {
              visible: root.notice.place === "gm" && root.notice.text !== ""
              size: Commons.Style.font.bodySmall
              color: root.dim
              text: root.notice.place === "gm" ? root.notice.text : ""
            }

            Card {
              visible: root.game !== null && !!root.game.ended
              clickable: false
              selected: true

              Line { text: root.dead ? "The adventure is over" : "The adventure has ended"; font.bold: true }
              Line { size: Commons.Style.font.bodySmall; text: root.game && root.game.ended ? root.game.ended.text : "" }
            }

            // Where you left off: the GM's last words exactly as recorded, so the table
            // reads the same before and after the GM window is reopened. Folded until asked for.

            Fold { id: leftOff; label: "Where you left off"; visible: root.game !== null && !!root.game.last_said }

            Card {
              visible: leftOff.open && root.game !== null && !!root.game.last_said
              clickable: false

              Line {
                size: Commons.Style.font.bodySmall
                text: root.game && root.game.last_said ? root.game.last_said.text : ""
              }
              Line {
                visible: root.game !== null && root.game.awaiting_player === true
                size: Commons.Style.font.caption
                color: root.dim
                text: "Waiting for your answer"
              }
            }

            // Character

            Heading { text: "Character"; visible: root.pc !== null }

            Line {
              visible: root.pc !== null
              size: Commons.Style.font.title
              font.bold: true
              text: root.pc ? root.pc.name : ""
            }

            Line {
              visible: root.pc !== null && Object.keys(root.pc.info).length > 0
              size: Commons.Style.font.bodySmall
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
              spacing: Commons.Style.space(4)
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
              color: Commons.Color.urgent
              font.bold: true
              text: root.atZero && root.labels.dying ? root.pc.name + " is dying: " + root.pc.dying.successes + " of " + root.labels.dying.rally
                + " successes, " + root.pc.dying.failures + " of " + root.labels.dying.die + " failures. Any hit is a failure." : ""
            }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: root.atZero

              Primary {
                text: "Death roll"
                enabled: !root.busy
                opacity: enabled ? 1 : 0.5
                onClicked: root.act(["death-roll"], "dying")
              }

              Act {
                visible: !!(root.labels.dying && root.labels.dying.self_save)
                text: "Save yourself"
                tooltipText: "A HEALING roll instead of the death roll: stop dying on a success"
                onClicked: root.act(["death-roll", "--heal"], "dying")
              }

              Act {
                visible: !!(root.labels.dying && root.labels.dying.self_rally) && root.dying
                text: "Rally"
                tooltipText: "Rally yourself, with no bane: act again, still making death rolls"
                onClicked: root.act(["rally"], "dying")
              }
            }

            ErrorLine { place: "dying" }

            Line {
              visible: root.pc !== null && ((root.pc.abilities || []).length > 0 || Object.keys(root.pc.ratings || {}).length > 0)
              size: Commons.Style.font.bodySmall
              color: root.dim
              text: root.pc ? (root.pc.abilities || []).concat(Object.keys(root.pc.ratings || {}).map(k => k + " " + root.pc.ratings[k])).join(" · ") : ""
            }

            // Rolling

            Heading { text: "Roll"; visible: root.pc !== null && !root.dying && !root.dead }

            RowLayout {
              visible: root.pc !== null && !root.dying && !root.dead && root.moves === null
              Layout.fillWidth: true
              spacing: Commons.Style.space(12)

              Stepper { label: "Boons"; value: root.boons; onStepped: function(value) { root.boons = value } }
              Stepper { label: "Banes"; value: root.banes; onStepped: function(value) { root.banes = value } }
            }

            // Attributes in even columns: six make two rows of three, four fit on one.
            GridLayout {
              id: attributes
              readonly property var names: root.pc ? Object.keys(root.pc.attributes) : []
              Layout.fillWidth: true
              columns: names.length > 4 ? Math.ceil(names.length / 2) : Math.max(1, names.length)
              columnSpacing: Commons.Style.space(4)
              rowSpacing: Commons.Style.space(4)
              visible: root.pc !== null && !root.dying && !root.dead && root.moves === null

              Repeater {
                model: attributes.names
                delegate: Act {
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
              spacing: Commons.Style.space(4)
              visible: root.pc !== null && !root.dying && !root.dead && root.moves === null

              Repeater {
                model: root.skillList()
                delegate: Act {
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
              spacing: Commons.Style.space(4)
              visible: root.moves !== null && root.pc !== null && !root.dying && !root.dead

              Repeater {
                model: root.pc && root.moves ? Object.keys(root.pc.attributes) : []
                delegate: Tag {
                  required property string modelData
                  label: modelData + " " + (root.pc ? root.pc.attributes[modelData] : "")
                }
              }
            }

            Stepper {
              visible: root.moves !== null && root.pc !== null && !root.dying && !root.dead
              label: "Adds"
              value: root.adds
              onStepped: function(value) { root.adds = value }
            }

            Repeater {
              model: root.moves !== null && root.pc !== null && !root.dying && !root.dead ? root.moveGroups() : []
              delegate: ColumnLayout {
                id: group
                required property var modelData
                Layout.fillWidth: true
                spacing: Commons.Style.space(2)

                Fold {
                  label: group.modelData.name
                  open: !!root.openGroups[group.modelData.name]
                  toggle: () => root.toggleGroup(group.modelData.name)
                }

                Flow {
                  Layout.fillWidth: true
                  spacing: Commons.Style.space(4)
                  visible: !!root.openGroups[group.modelData.name]

                  Repeater {
                    model: group.modelData.moves
                    delegate: Act {
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
              size: Commons.Style.font.caption
              color: root.dim
              text: root.pickedMove !== "" && root.moves && root.moves[root.pickedMove]
                ? root.moves[root.pickedMove].name + ": " + (root.moves[root.pickedMove].kind === "progress" ? "which one?" : "roll with which stat?") : ""
            }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: root.pickedMove !== ""

              Repeater {
                model: root.pickOptions()
                delegate: Act {
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
              Layout.topMargin: Commons.Style.space(4)
              Layout.fillWidth: true
              spacing: Commons.Style.space(10)
              property string face: root.rollFace()
              property int ticks: 0

              Connections {
                target: watcher
                function onRolled() {
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
                font.family: Commons.Style.font.family
                font.pixelSize: Math.round(Commons.Style.font.title * 2.1)
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
                spacing: Commons.Style.space(1)
                Line {
                  size: Commons.Style.font.body
                  font.bold: true
                  text: root.rollHead()
                }
                Line {
                  size: Commons.Style.font.body
                  font.bold: true
                  color: root.rollColor()
                  opacity: tumble.running ? 0 : 1
                  text: root.rollVerdict()
                  Behavior on opacity { NumberAnimation { duration: 200 } }
                }
                Line {
                  size: Commons.Style.font.caption
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
                spacing: Commons.Style.space(4)

                Repeater {
                  model: root.dragonOptions()
                  delegate: Act {
                    required property var modelData
                    text: modelData.label
                    tooltipText: modelData.tip
                    onClicked: root.act(["dragon", modelData.option].concat(modelData.foe !== "" ? [modelData.foe] : []), "dragon")
                  }
                }
              }

              Line {
                visible: root.dragonNote() !== ""
                size: Commons.Style.font.caption
                color: root.dim
                text: root.dragonNote()
              }
            }

            ErrorLine { place: "dragon" }

            // Momentum can be burned on the roll just made, when that would change it.
            Act {
              visible: !!(root.game && root.game.burn) && !root.dying && !root.dead
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
              size: Commons.Style.font.caption
              text: root.pushChoices.length > 0 ? "Push the roll by taking a condition:" : "Push the roll:"
            }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: root.canPush

              Repeater {
                model: root.pushChoices
                delegate: Act {
                  required property string modelData
                  text: modelData
                  onClicked: root.act(["push", "--condition", modelData], "roll")
                }
              }

              Act {
                visible: root.labels.push !== "condition"
                text: "push"
                onClicked: root.act(["push"], "roll")
              }

              Act {
                visible: root.pushAbility
                text: root.labels.push_ability ? root.labels.push_ability.name + " (" + root.labels.push_ability.cost + ")" : ""
                tooltipText: "Push without a condition"
                onClicked: root.act(["push", "--sole-survivor"], "roll")
              }
            }

            ErrorLine { place: "roll" }

            // Fight: the GM starts and ends it; the clicks here are the pure mechanics. Right under
            // the last roll, so a fight's weapons aren't below the spells and the abilities.

            Heading { text: root.fight ? "Fight · round " + root.fight.round : ""; visible: root.fight !== null }

            Line {
              visible: root.fight !== null
              size: Commons.Style.font.caption
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
                name: foe.name
                clickable: !foe.down
                selected: !foe.down && root.aimedAt() === modelData
                opacity: foe.down ? 0.5 : 1
                onClicked: root.target = modelData

                Meter {
                  label: foeCard.foe.name + (foeCard.foe.down ? " (down)" : foeCard.foe.armor ? " · armor " + foeCard.foe.armor : "")
                  value: foeCard.foe.hp
                  maximum: foeCard.foe.max
                }

                Act {
                  visible: !foeCard.foe.down && !root.dead && !(root.fight && root.fight.incoming)
                  text: "Attacks you"
                  tooltipText: "Roll this foe's attack"
                  onClicked: root.act(["enemy", foeCard.modelData], "fight")
                }
              }
            }

            Line {
              visible: root.fight !== null && !root.dying && !root.dead && root.standing().length > 0 && !root.fight.incoming
              size: Commons.Style.font.caption
              color: root.dim
              text: "Attack the selected foe (boons and banes above apply):"
            }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: root.fight !== null && !root.dying && !root.dead && root.standing().length > 0 && !root.fight.incoming

              Repeater {
                model: root.kit.weapons.filter(w => w.attack)
                delegate: Choice {
                  required property var modelData
                  text: modelData.label + " " + modelData.damage + root.weaponNote(modelData)
                  tooltipText: modelData.condition === "broken" ? "Broken: mend it first" : modelData.condition === "damaged" ? "Damaged: a bane on every use until it is mended" : ""
                  enabled: modelData.condition !== "broken" && root.waiting === null && !root.busy
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
              color: Commons.Color.urgent
              font.bold: true
              text: root.fight && root.fight.incoming ? root.fight.incoming.name + " hits: " + root.fight.incoming.damage
                + " damage" + (root.kit.armor ? ", armor " + root.kit.armor : "") : ""
            }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: root.fight !== null && !!root.fight.incoming

              Act {
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
                  enabled: modelData.condition !== "broken" && !root.busy
                  opacity: enabled ? 1 : 0.4
                  onClicked: root.parry(modelData.id)
                }
              }

              Act {
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

            Act {
              visible: root.fight !== null && !root.dead
              text: "Next round"
              tooltipText: "Deal new initiative cards"
              onClicked: root.act(["fight", "--round"].concat(root.useArgs("round", "")), "fight", () => root.spent("round", ""))
            }

            ErrorLine { place: "fight" }

            // Magic: what the hero can cast, with the power, boons and banes above, and what is ready to cast.

            Heading { text: "Magic"; visible: root.magic !== null && !root.dying && !root.dead }

            RowLayout {
              Layout.fillWidth: true
              spacing: Commons.Style.space(12)
              visible: root.magic !== null && !root.dying && !root.dead

              Stepper {
                label: "Power"
                from: 1
                to: root.magic ? root.magic.max_power : 1
                value: root.power
                onStepped: function(value) { root.power = value }
              }

              Line {
                size: Commons.Style.font.caption
                color: root.dim
                text: root.magic ? "Ready " + root.magic.ready + " of " + root.magic.limit : ""
              }
            }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: root.magic !== null && root.magic.body.length > 0 && !root.dying && !root.dead

              Line { Layout.fillWidth: false; size: Commons.Style.font.caption; color: root.dim; text: "Power from the body:" }

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
              spacing: Commons.Style.space(4)
              visible: root.magic !== null && !root.dying && !root.dead

              Repeater {
                model: root.ready()
                delegate: Choice {
                  required property var modelData
                  text: modelData.name + (modelData.cost !== null ? " · " + modelData.cost + " " + root.magic.track.toUpperCase() : "")
                  tooltipText: (modelData.trick ? "A magic trick: always ready, and it works" : "Rank " + modelData.rank + (modelData.school ? ", " + modelData.school : ""))
                    + (modelData.damage && root.fight ? ". Hits the foe you aimed at" : "") + (modelData.heal ? ". Heals you" : "")
                  selected: !modelData.trick
                  enabled: root.waiting === null && !root.busy
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
                spacing: Commons.Style.space(4)

                Line { text: spellRow.modelData.name + (spellRow.modelData.cost !== null ? " · " + spellRow.modelData.cost + " " + root.magic.track.toUpperCase() : "") }

                Act {
                  text: "Prepare"
                  tooltipText: "Hold it ready (it takes a stretch of study, the GM's to give)"
                  selected: root.preparing === spellRow.modelData.name
                  onClicked: root.prepare(spellRow.modelData)
                }

                Choice {
                  text: "From the grimoire"
                  tooltipText: spellRow.modelData.reaction ? "A reaction spell can't be cast from the grimoire" : "Cast it unprepared: it takes twice as long"
                  enabled: root.waiting === null && !root.busy && !spellRow.modelData.reaction
                  opacity: enabled ? 1 : 0.4
                  onClicked: root.cast(spellRow.modelData, true)
                }
              }
            }

            Line {
              visible: root.preparing !== ""
              size: Commons.Style.font.caption
              color: root.dim
              text: "You hold as many as you can: put which aside for " + root.preparing + "?"
            }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: root.preparing !== ""

              Repeater {
                model: root.preparing !== "" ? root.ready().filter(s => !s.trick) : []
                delegate: Act {
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
              spacing: Commons.Style.space(4)
              visible: root.ridersFor("alone").length > 0 && !root.dying && !root.dead

              Repeater {
                model: root.ridersFor("alone")
                delegate: Choice {
                  required property var modelData
                  text: modelData.name + " (" + root.abilityCost(modelData) + ")"
                  tooltipText: modelData.afford ? "Pay for it; the GM reads its page" : "Not enough to pay for it"
                  enabled: modelData.afford && !root.busy
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
                name: modelData.name
                clickable: false

                Line {
                  font.bold: true
                  text: trackCard.modelData.name
                }

                Line {
                  size: Commons.Style.font.caption
                  color: root.dim
                  text: (trackCard.modelData.rank ? trackCard.modelData.rank + " " : "")
                    + (root.progressSpec ? (root.progressSpec.kinds[trackCard.modelData.kind] || root.progressSpec.unranked[trackCard.modelData.kind] || "").toLowerCase() : "")
                    + " · " + Math.floor(trackCard.modelData.ticks / (root.progressSpec ? root.progressSpec.ticks : 4)) + " of " + (root.progressSpec ? root.progressSpec.boxes : 10)
                }

                Boxes { track: trackCard.modelData }

                RowLayout {
                  spacing: Commons.Style.space(4)

                  Act {
                    text: "Mark progress"
                    tooltipText: trackCard.ranked ? "What a step of this rank is worth" : "One tick"
                    onClicked: root.act(["track", "mark", trackCard.modelData.id], "track")
                  }

                  Act {
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
              spacing: Commons.Style.space(4)

              TextField {
                id: trackName
                objectName: "trackName"
                Layout.fillWidth: true
                placeholderText: "A vow, a road or a foe"
                onAccepted: root.startTrack()
              }

              Flow {
                Layout.fillWidth: true
                spacing: Commons.Style.space(4)

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
                spacing: Commons.Style.space(4)

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

              Act {
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
              visible: root.pc !== null && (root.pc.marks || []).length > 0 && !root.dying && !root.dead

              Line {
                size: Commons.Style.font.bodySmall
                color: root.dim
                text: root.pc ? "Marked: " + (root.pc.marks || []).map(k => root.pc.skills[k] ? root.pc.skills[k].name : k).join(", ") : ""
              }

              Act {
                text: "Roll advancement"
                tooltipText: "At the end of a session: each marked skill may go up one"
                onClicked: root.act(["advance"], "roll")
              }
            }

            // Rest

            Heading { text: "Rest"; visible: root.pc !== null && !root.dying && !root.dead && Object.keys(root.labels.rests).length > 0 }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: root.pc !== null && !root.dying && !root.dead && Object.keys(root.labels.rests).length > 0

              Repeater {
                model: root.pc ? Object.keys(root.labels.rests) : []
                delegate: Choice {
                  required property string modelData
                  readonly property bool used: root.restUsed(modelData)
                  readonly property bool blocked: used || root.fight !== null || root.dying || root.dead
                  text: root.labels.rests[modelData].label
                  tooltipText: used ? "Already taken this shift" : root.fight ? "Not during a fight" : "Recover and let time pass"
                  enabled: !blocked && !root.busy
                  opacity: enabled ? 1 : 0.4
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
              visible: root.pc !== null && !root.dying && !root.dead && (!!(root.game && root.game.light) || root.carriesTorch())

              Line {
                size: Commons.Style.font.bodySmall
                color: root.game && root.game.dark && !root.game.light ? Commons.Color.urgent : root.textColor
                text: root.game && root.game.light ? root.game.light.label + ": " + root.hours(root.game.light.left) + " left"
                  : root.game && root.game.dark ? "It is dark here." : "No light burning."
              }

              Act {
                text: root.game && root.game.light ? "Put it out" : "Light a torch"
                onClicked: root.act(root.game && root.game.light ? ["light", "--out"] : ["light", "torch"], "light")
              }
            }

            ErrorLine { place: "light" }
            ErrorLine { place: "book" }

            // Oracle

            Heading { text: "Oracle"; visible: root.pc !== null && !root.dying && !root.dead }

            TextField {
              id: question
              objectName: "question"
              visible: root.pc !== null && !root.dying && !root.dead
              Layout.fillWidth: true
              placeholderText: "Ask a question"
              onAccepted: root.askOracle()
            }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: root.pc !== null && !root.dying && !root.dead && !!root.labels.fortune

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
              spacing: Commons.Style.space(4)
              visible: root.pc !== null && !root.dying && !root.dead

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
              visible: root.pc !== null && !root.dying && !root.dead

              Act {
                Layout.fillWidth: true
                text: "Ask"
                tooltipText: "Or press Enter in the question"
                selected: true
                onClicked: root.askOracle()
              }

              Act {
                text: "Meaning"
                tooltipText: "Words to read for a question a yes or no can't answer"
                onClicked: root.askMeaning()
              }
            }

            Line {
              visible: root.lastOracle() !== "" && !root.dying && !root.dead
              size: Commons.Style.font.bodySmall
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
                spacing: Commons.Style.space(2)

                Line { text: clockRow.modelData.label + "  " + clockRow.modelData.value + "/" + clockRow.modelData.segments }

                Row {
                  spacing: Commons.Style.space(3)

                  Repeater {
                    model: clockRow.modelData.segments
                    delegate: Rectangle {
                      required property int index
                      width: Commons.Style.space(14)
                      height: Commons.Style.space(6)
                      radius: 2
                      color: index < clockRow.modelData.value ? Commons.Color.urgent : root.faint
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

            // An empty Flow has no height but still takes its spacing: each one shows only with something in it.
            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: root.game !== null && root.game.clues.length > 0

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
              size: Commons.Style.font.bodySmall
              text: root.pc ? root.pc.items.join(", ") : ""
            }

            Line {
              visible: root.game !== null && !!root.game.load
              size: Commons.Style.font.bodySmall
              color: root.game && root.game.load && root.game.load.over ? Commons.Color.urgent : root.dim
              text: root.game && root.game.load ? "Carrying " + root.game.load.carried + " of " + root.game.load.capacity + (root.game.load.over ? ": over the load" : "") : ""
            }

            Repeater {
              model: root.pc && !root.dying && !root.dead ? root.worn() : []
              delegate: RowLayout {
                id: mending
                required property var modelData
                Layout.fillWidth: true
                spacing: Commons.Style.space(4)

                Line { text: "The " + mending.modelData.label.toLowerCase() + " is " + mending.modelData.condition; size: Commons.Style.font.bodySmall }

                Act {
                  text: "Mend"
                  tooltipText: "A roll to mend it"
                  onClicked: root.act(["repair", mending.modelData.id], "gear")
                }

                Act {
                  text: "Artisan"
                  tooltipText: "An artisan mends it, with no roll"
                  onClicked: root.act(["repair", mending.modelData.id, "--artisan"], "gear")
                }
              }
            }

            ErrorLine { place: "gear" }

            Heading { text: "Table settings"; visible: root.prefsText() !== "" }

            Line {
              visible: root.prefsText() !== ""
              size: Commons.Style.font.bodySmall
              color: root.dim
              text: root.prefsText()
            }

            Heading { text: "Log"; visible: root.game !== null }

            Repeater {
              model: root.recent()
              delegate: Line {
                required property var modelData
                size: Commons.Style.font.bodySmall
                color: modelData.type === "check" || modelData.type === "push" ? root.textColor : root.dim
                text: modelData.text
              }
            }

            // Settings, not play: last, and folded.

            // Only the Book's GM runs at a pace; an agent in a terminal keeps its own settings.
            Fold { id: paceFold; label: "GM pace"; visible: root.agentInfo.book !== false }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: paceFold.visible && paceFold.open

              Repeater {
                model: [["quick", "Quick"], ["normal", "Normal"], ["careful", "Careful"]]
                delegate: Act {
                  required property var modelData
                  text: modelData[1]
                  selected: root.pace === modelData[0]
                  tooltipText: ({
                    quick: "The GM answers sooner and spends fewer tokens",
                    normal: "The GM thinks a little before it answers",
                    careful: "The GM thinks longer about the rules: slower, and more tokens",
                  })[modelData[0]]
                  onClicked: root.setPace(modelData[0])
                }
              }
            }

            ErrorLine { place: "pace" }

            Fold { id: effectsFold; label: "Desktop effects" }

            Flow {
              Layout.fillWidth: true
              spacing: Commons.Style.space(4)
              visible: effectsFold.open

              Repeater {
                model: [["borders", "Borders"], ["screen", "Screen"], ["sound", "Sound"], ["candle", "Candlelight"], ["omens", "Omens"], ["screensaver", "Screensaver"]]
                delegate: Act {
                  required property var modelData
                  text: modelData[1]
                  selected: root.effects[modelData[0]] !== false
                  tooltipText: ({
                    borders: "Dragons flash the window borders gold, Demons red; dying holds them red",
                    screen: "The whole screen answers: gold for a Dragon, red for a Demon or a blow, a red rim while dying, grey at death",
                    sound: "Dice, bells, drums and heartbeats, in time with the Book",
                    candle: "The screen warms while the Book is open",
                    omens: "What the hidden clocks stir up arrives as a notification",
                    screensaver: "The screensaver shows your hero while the Book is open",
                  })[modelData[0]]
                  onClicked: root.run(["desk", "settings", modelData[0] + "=" + (selected ? "off" : "on")], "effects",
                                      () => root.ask("effects", ["desk", "settings"]))
                }
              }
            }

            ErrorLine { place: "effects" }
          }
        }
      }
    }
  }
}
