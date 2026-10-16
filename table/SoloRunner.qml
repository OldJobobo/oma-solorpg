import QtQuick
import Quickshell.Io

// What runs the plugin's own bin/solo for the Table and the Book, and keeps what came of it.
// Commands that change something run one at a time, in the order asked for, and while any
// runs or waits the Table is busy; reads (JSON on stdout) run one at a time too. What went
// wrong is kept for each source, with the place to say it. The Panel makes one: its run, ask
// and errorsAt, and act (a command in the current campaign), go through it, and what a read
// printed goes back to the Panel's received().
QtObject {
  id: runner

  // The plugin's bin/solo, and which campaign is current (book/CurrentCampaign.qml): read again
  // when a command ends, so a game begun or picked is followed at once.
  required property string solo
  required property var currentFile

  // What went wrong and where to say it, {text, place}, one for each source: the commands
  // that change something (and a click refused before one ran), and the ones that only
  // read. A read that fails never covers what a command said, nor the other way round.
  property var error: ({ text: "", place: "" })
  property var queryError: ({ text: "", place: "" })
  // What a command said it did, for the few whose words are for the player (opening the GM).
  property var notice: ({ text: "", place: "" })
  // Commands that change something, waiting for the one running to end. While any runs or
  // waits the Table is busy, and its buttons that run one wait too.
  property var queue: []
  readonly property bool busy: action.job !== null || queue.length > 0

  // What a read printed on stdout, for the Panel to take in by its kind.
  signal received(string kind, string text)

  // Commands that change something, one at a time and in the order asked for: one asked for
  // while another runs (from the Book, or Enter in a field) waits its turn, never lost.
  // `done` runs after a success, with what the command printed; `failed` after anything else.
  function run(args, place, done, failed) {
    runner.error = { text: "", place: "" }
    runner.notice = { text: "", place: "" }
    runner.queue = runner.queue.concat([{ args: [runner.solo].concat(args), place: place, done: done || null, failed: failed || null }])
    runner.next()
  }

  function next() {
    if (action.job === null && runner.queue.length > 0) {
      action.job = runner.queue[0]
      runner.queue = runner.queue.slice(1)
      action.said = ""
      action.out = ""
      action.command = action.job.args
      action.running = true
    }
  }

  // A command has ended: `said` is what to tell the player ("" for nothing), `ok` whether it went through.
  // `done` and `failed` are made on the Panel's root, never in a delegate: state.json is read again before the
  // exit comes, and a delegate whose model changed is gone, and its functions with it. Whatever they do,
  // the next command waiting runs.
  function ran(said, ok) {
    var job = action.job
    action.job = null
    currentFile.reload()
    if (said !== "") runner.error = { text: said, place: job.place }
    try {
      if (ok && job.done) job.done(action.out)
      else if (!ok && job.failed) job.failed()
    } finally {
      runner.next()
    }
  }

  // Commands that only read (JSON on stdout). One runs at a time; the latest request
  // of each kind waits for its turn. What goes wrong shows at `place`, the kind unless said.
  function ask(kind, args, place) {
    if (query.job !== null) {
      var pending = Object.assign({}, query.pending)
      pending[kind] = { args: args, place: place || kind }
      query.pending = pending
    } else {
      query.out = ""
      query.said = ""
      query.job = { kind: kind, place: place || kind }
      query.command = [runner.solo].concat(args)
      query.running = true
    }
  }

  // A read has ended (`said` as for ran()), and the next one waiting starts.
  function answered(said) {
    var job = query.job
    query.job = null
    if (said !== "") runner.queryError = { text: said, place: job.place }
    else if (runner.queryError.place === job.place) runner.queryError = { text: "", place: "" }
    runner.received(job.kind, query.out)
    var kinds = Object.keys(query.pending)
    if (kinds.length > 0) {
      var next = query.pending[kinds[0]]
      var rest = Object.assign({}, query.pending)
      delete rest[kinds[0]]
      query.pending = rest
      runner.ask(kinds[0], next.args, next.place)
    }
  }

  // What solo said on stderr, as the player reads it; with nothing said, a failing exit code.
  function trouble(said, code) {
    var text = said.trim().replace(/^solo: /, "")
    return text !== "" ? text : code !== 0 ? "solo stopped without saying why (exit code " + code + ")." : ""
  }

  // A process that never started has no exit: Quickshell only lets `running` go false.
  function unstarted() {
    return "The plugin couldn't run " + runner.solo + ". Is the plugin's folder complete?"
  }

  // What went wrong at a place, from either source.
  function errorsAt(place) {
    return [runner.error, runner.queryError].filter(e => e.place === place && e.text !== "").map(e => e.text).join("\n")
  }

  // The command running now ({place, done}) and what it says on stdout and stderr. The
  // streams end before the exit does, so the exit has all of it.
  property Process action: Process {
    id: action
    property var job: null
    property string out: ""
    property string said: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: action.out = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: action.said = text
    }
    onExited: (exitCode, exitStatus) => runner.ran(runner.trouble(action.said, exitCode), exitCode === 0)
    onRunningChanged: if (!running && action.job !== null) runner.ran(runner.unstarted(), false)
  }

  property Process query: Process {
    id: query
    property var job: null          // {kind, place}
    property var pending: ({})      // kind: {args, place}
    property string out: ""
    property string said: ""
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: query.out = text
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: query.said = text
    }
    onExited: (exitCode, exitStatus) => runner.answered(runner.trouble(query.said, exitCode))
    onRunningChanged: if (!running && query.job !== null) runner.answered(runner.unstarted())
  }
}
