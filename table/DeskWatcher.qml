import QtQuick
import Quickshell

// The watcher: while a game is on, the desktop joins in (solo desk). What is new in the game
// the Panel reads from state.json sets off the desktop's effects and the table's sounds, timed
// to the Book's dice, and what the watcher has already reacted to is kept, so a reload never
// replays old rolls. It keeps which effects the player has on, too. The Panel gives it the
// game, its campaign and whether the Book is open; it runs with both windows closed.
QtObject {
  id: watcher

  // The plugin's bin/solo, the current campaign, its game and whether the Book is open: the Panel's.
  required property string solo
  property string campaign: ""
  property var game: null
  property bool bookOpen: false

  // Which effects the player has on (solo desk settings), as the Table's Desktop effects show them.
  property var effects: ({ borders: true, screen: true, sound: true, candle: true, omens: true, screensaver: true })
  // The table's sounds and what plays them ({play, sounds}, from solo desk sound).
  property var sounds: ({})
  // When the dice land, in seconds: the Book's tumble (book/DiceMoment.qml), or a quick
  // throw with the Book shut. The sounds are cut to match.
  readonly property real diceLand: 1.94
  readonly property real diceLandShort: 0.5
  // What the watcher has already reacted to, so a reload never replays old rolls.
  property int fxSeen: -1
  property bool fxDying: false
  property int fxFailures: 0
  property bool fxDead: false
  property bool fxFighting: false
  property int fxSaid: -1
  // A roll just came in (not one already there when the game loaded): the Table's number tumbles.
  signal rolled()

  // The desktop effects (solo desk). Detached: they must never hold up the table. `after`
  // (seconds) holds one back to land with the Book's dice.
  function desk(args, after) {
    Quickshell.execDetached([watcher.solo].concat(watcher.campaign !== "" ? ["-C", watcher.campaign] : []).concat(["desk"])
      .concat(after > 0 ? ["--after", after.toFixed(2)] : []).concat(args))
  }

  // The table's sounds, played straight from the cache (solo desk sound made them), so
  // they keep time with the Book to the millisecond.
  function sound(name, after) {
    var path = watcher.sounds.sounds ? watcher.sounds.sounds[name] : ""
    if (watcher.effects.sound === false || !watcher.sounds.play || !path) return
    Quickshell.execDetached(["sh", "-c", 'sleep "$0"; exec "$@"', String(after > 0 ? after.toFixed(2) : 0)]
      .concat(watcher.sounds.play).concat([path]))
  }

  // New beats in the story set off the desktop. The dice rattle and land with the Book's
  // (quickly, with the Book shut), and what they bring lands with them: a Dragon floods the
  // screen gold, a Demon drains it red, a blow jolts it. Omens ripple it and notify, a
  // scene opens on a horn, a fight on a drum, a torch catches, the GM's words turn a page.
  // Dying holds a red rim, closer with each failure; death greys the screen and
  // tolls a bell. The screensaver keeps the GM's latest words while the Book is open.
  function watch() {
    if (!watcher.game || !watcher.game.story) return
    var beats = watcher.game.story
    var newest = beats.length ? beats[beats.length - 1].seq : 0
    var pc = watcher.game.pc
    var dead = !!(pc && pc.dead)
    var dying = !!(pc && pc.dying) && !dead
    var failures = dying ? pc.dying.failures || 0 : 0
    var fighting = !!watcher.game.combat && !dead
    if (watcher.fxSeen < 0) {
      watcher.fxSeen = newest
      watcher.fxDying = dying
      watcher.fxFailures = failures
      watcher.fxDead = dead
      watcher.fxFighting = fighting
      if (dying) watcher.desk(["dying", "on", String(failures)])
      return
    }
    var fresh = beats.filter(b => b.seq > watcher.fxSeen)
    watcher.fxSeen = Math.max(watcher.fxSeen, newest)
    var roll = fresh.filter(b => b.kind === "roll").pop()
    var land = roll ? (watcher.bookOpen ? watcher.diceLand : watcher.diceLandShort) : 0
    if (roll) {
      var outcome = roll.outcome || {}
      watcher.rolled()
      watcher.sound(watcher.bookOpen ? "dice" : "dice-short")
      if (outcome.dragon) {
        watcher.desk(["flash", "dragon"], land)
        watcher.sound("dragon", land)
      } else if (outcome.demon) {
        watcher.desk(["flash", "demon"], land)
        watcher.sound("demon", land)
      }
    }
    if (fresh.some(b => b.kind === "hurt" && (b.dealt || 0) > 0)) {
      watcher.desk(["flash", "hit"], land)
      watcher.sound("hit", land)
    }
    fresh.filter(b => b.kind === "omen").forEach(b => {
      watcher.desk(["omen", "--", b.text.replace(/^[^:]*\(\d+\):\s*/, "")])
      watcher.sound("omen")
    })
    if (fresh.some(b => b.kind === "scene")) watcher.sound("scene")
    if (fighting && !watcher.fxFighting) watcher.sound("drum", land)
    if (watcher.game.light && fresh.some(b => b.kind === "light")) watcher.sound("torch")
    if (watcher.bookOpen && fresh.some(b => b.kind === "gm")) watcher.sound("page")
    if (dead && !watcher.fxDead) {
      watcher.desk(["death"], land)
      watcher.sound("bell", land)
    } else if (dying !== watcher.fxDying || failures !== watcher.fxFailures) {
      watcher.desk(dying ? ["dying", "on", String(failures)] : ["dying", "off"], land)
      if (dying) watcher.sound("heartbeat", land)
    }
    watcher.fxDying = dying
    watcher.fxFailures = failures
    watcher.fxDead = dead
    watcher.fxFighting = fighting
    var said = watcher.game.last_said ? watcher.game.last_said.seq : -1
    if (watcher.bookOpen && said !== watcher.fxSaid) {
      watcher.fxSaid = said
      watcher.desk(["screensaver", "on"])
    }
  }

  onGameChanged: watcher.watch()
  // What the game holds on the desktop belongs to its campaign too: another one picked, or this
  // one deleted, lets a dying hero's red go (a deleted campaign's state.json is no longer watched
  // when it goes, so nothing else would), and the watcher starts over.
  onCampaignChanged: {
    if (watcher.fxDying) watcher.desk(["dying", "off"])
    watcher.fxDying = false
    watcher.fxFailures = 0
    watcher.fxDead = false
    watcher.fxFighting = false
    watcher.fxSeen = -1
    watcher.fxSaid = -1
  }
  onBookOpenChanged: {
    if (watcher.bookOpen) {
      watcher.desk(["candle", "on"])
      watcher.desk(["screensaver", "on"])
    } else {
      watcher.desk(["candle", "off"])
      watcher.desk(["screensaver", "off"])
    }
  }
}
