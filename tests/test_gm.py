"""The Book's GM: headless turns through fake agents that print what the real ones do."""

import json
import os
import stat
import subprocess
import textwrap
import time
import unittest.mock

from helpers import CampaignTest, Dice

from solo import SoloError, cli, gm

CLAUDE_STREAM = [
    {"type": "system", "subtype": "init", "session_id": "sess-1"},
    {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}},
    {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Let me look."}}},
    {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Bash"}}},
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "input": {"command": "solo check sneaking"}}]}},
    {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "The guards "}}},
    {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "never look down. What now?"}}},
    {"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-1", "result": "The guards never look down. What now?"},
]
CODEX_STREAM = [
    {"type": "thread.started", "thread_id": "thread-9"},
    {"type": "item.started", "item": {"type": "command_execution", "command": "bash -lc 'solo scene'"}},
    {"type": "item.completed", "item": {"type": "agent_message", "text": "Mud and drums. What do you do?"}},
    {"type": "turn.completed"},
]


class GmTest(CampaignTest):
    def setUp(self):
        super().setUp()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        patch = unittest.mock.patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}", "SOLO_AGENT": "claude"})
        patch.start()
        self.addCleanup(patch.stop)

    def agent(self, name, events, fail_resume=False, code=0):
        """A stand-in agent: records its arguments and then its prompt (stdin), prints the events as JSON lines."""
        lines = "\n".join(json.dumps(e) for e in events)
        script = self.bin / name
        script.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import json, sys
            with open({str(self.tmp / (name + '.calls'))!r}, "a") as f:
                f.write(json.dumps(sys.argv[1:] + [sys.stdin.read()]) + "\\n")
            if {fail_resume!r} and ("--resume" in sys.argv or "resume" in sys.argv):
                print("No conversation found with session ID", file=sys.stderr)
                sys.exit(1)
            print({lines!r})
            sys.exit({code})
            """))
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

    def calls(self, name):
        return [json.loads(line) for line in (self.tmp / (name + ".calls")).read_text().splitlines()]

    def said(self):
        with self.session() as c:
            return [(e["by"], e["text"]) for e in c.events if e["type"] == "said"]

    def test_a_claude_turn_records_both_sides_and_keeps_the_session(self):
        self.agent("claude", CLAUDE_STREAM)
        result = gm.turn(self.root, "I sneak past the gate.")
        self.assertEqual(result["status"], "done")
        self.assertEqual(self.said(), [("player", "I sneak past the gate."), ("gm", "The guards never look down. What now?")])
        first = self.calls("claude")[0]
        self.assertNotIn("--", first)  # the prompt comes on stdin, out of the process list
        self.assertTrue(first[-1].startswith(gm.BOOK_PROMPT))  # no session yet: catch up from the campaign
        self.assertIn("Bash(solo check:*)", first)
        self.assertNotIn("--resume", first)
        self.assertEqual(json.loads((self.root / ".solo" / "agent.json").read_text()), {"agent": "claude", "session": "sess-1"})
        gm.turn(self.root, "I climb the palisade.")
        second = self.calls("claude")[1]
        self.assertEqual(second[-1], "I climb the palisade.")
        self.assertEqual(second[second.index("--resume") + 1], "sess-1")

    def test_the_players_words_go_on_stdin_never_in_the_process_list(self):
        # Arguments are any local user's to read in /proc; and `claude -p "-x ..."` would take them for an option.
        self.agent("claude", CLAUDE_STREAM)
        gm.turn(self.root, "Hi")
        gm.turn(self.root, "--help me, I'm falling")
        *argv, prompt = self.calls("claude")[1]
        self.assertEqual(prompt, "--help me, I'm falling")
        self.assertFalse(any("falling" in a for a in argv))
        self.agent("codex", CODEX_STREAM)
        gm.turn(self.root, None, agent="codex")
        gm.turn(self.root, "-- then I run", agent="codex")
        *argv, prompt = self.calls("codex")[1]
        self.assertEqual((argv[-1], prompt), ("-", "-- then I run"))

    def test_a_new_campaign_waits_idle_for_its_first_turn(self):
        # The Book watches turn.json, and a watch set on a missing file never fires.
        self.assertEqual(json.loads((self.root / ".solo" / "turn.json").read_text()), {"status": "idle"})
        self.assertEqual(gm.status(self.root)["status"], "idle")

    def test_an_agent_that_goes_quiet_is_ended_and_the_table_freed(self):
        script = self.bin / "claude"
        script.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        with unittest.mock.patch.dict(os.environ, {"SOLO_GM_TIMEOUT": "1"}):
            began = time.monotonic()
            result = gm.turn(self.root, "Hello?")
        self.assertLess(time.monotonic() - began, 15)
        self.assertEqual(result["status"], "error")
        self.assertIn("said nothing for 1 seconds", result["error"])
        self.agent("claude", CLAUDE_STREAM)
        self.assertEqual(gm.turn(self.root, "Hello again?")["status"], "done")

    def test_what_a_turn_cost_is_kept_with_it(self):
        usage = {"input_tokens": 12, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 3000, "output_tokens": 80}
        self.agent("claude", [*CLAUDE_STREAM[:-1], {**CLAUDE_STREAM[-1], "num_turns": 3, "total_cost_usd": 0.04, "usage": usage}])
        gm.turn(self.root, "I sneak past the gate.")
        self.assertEqual(gm.status(self.root)["usage"], {"model_calls": 3, "input_tokens": 3112, "cached_input_tokens": 3000,
                                                         "output_tokens": 80, "cost_usd": 0.04})

    def test_a_lost_session_starts_over_from_the_campaign(self):
        (self.root / ".solo").mkdir(exist_ok=True)
        (self.root / ".solo" / "agent.json").write_text(json.dumps({"agent": "claude", "session": "gone"}))
        self.agent("claude", CLAUDE_STREAM, fail_resume=True)
        result = gm.turn(self.root, "Hello?")
        self.assertEqual(result["status"], "done")
        calls = self.calls("claude")
        self.assertIn("--resume", calls[0])
        self.assertNotIn("--resume", calls[1])
        self.assertTrue(calls[1][-1].startswith(gm.BOOK_PROMPT))  # the new session reads the table

    def test_codex_turns_resume_by_thread(self):
        self.agent("codex", CODEX_STREAM)
        gm.turn(self.root, None, agent="codex")
        gm.turn(self.root, "I wait.", agent="codex")
        first, second = self.calls("codex")
        self.assertTrue(first[-1].startswith(gm.BOOK_PROMPT))
        self.assertEqual(second[-4:], ["resume", "thread-9", "-", "I wait."])
        self.assertEqual(self.said()[-1], ("gm", "Mud and drums. What do you do?"))
        self.assertEqual(gm.status(self.root)["doing"], "")

    def test_the_pace_sets_how_hard_the_agent_thinks(self):
        self.agent("claude", CLAUDE_STREAM)
        self.agent("codex", CODEX_STREAM)
        gm.turn(self.root, "Hi")
        gm.set_pace("quick")
        gm.turn(self.root, "Faster.")
        gm.turn(self.root, "Hi", agent="codex")
        with unittest.mock.patch.dict(os.environ, {"SOLO_GM_EFFORT": "xhigh"}):  # a play test's own level
            gm.turn(self.root, "Harder.")
        self.assertEqual([call[call.index("--effort") + 1] for call in self.calls("claude")], ["medium", "low", "xhigh"])
        self.assertIn('model_reasoning_effort="low"', self.calls("codex")[0])

    def test_a_claude_turn_carries_its_limits(self):
        self.agent("claude", CLAUDE_STREAM)
        gm.turn(self.root, "Hi")
        first = self.calls("claude")[0]
        # Nothing on the web and no file written, whatever the allowed list says.
        denied = first[first.index("--disallowedTools") + 1:][:5]
        self.assertEqual(denied, ["WebFetch", "WebSearch", "Edit", "Write", "NotebookEdit"])
        self.assertEqual(first[first.index("--max-turns") + 1], "40")
        self.assertEqual(first[first.index("--max-budget-usd") + 1], "10.00")
        # None of the player's own MCP servers or browser, and of Claude Code's tools only Bash and Read.
        self.assertTrue({"--strict-mcp-config", "--no-chrome"} <= set(first))
        self.assertEqual(first[first.index("--tools") + 1], "Bash,Read")
        self.assertEqual(first[first.index("--add-dir") + 1], str(cli.REPO / "skills" / "solo-gm"))
        with unittest.mock.patch.dict(os.environ, {"SOLO_GM_MAX_TURNS": "7"}):
            gm.turn(self.root, "Again")
        self.assertEqual(self.calls("claude")[1][self.calls("claude")[1].index("--max-turns") + 1], "7")

    def test_the_gm_cannot_run_the_players_own_settings(self):
        self.assertNotIn("gm", cli.GM_COMMANDS)

    def test_a_turn_that_never_goes_quiet_is_ended_on_the_clock(self):
        script = self.bin / "claude"
        script.write_text("#!/usr/bin/env python3\nimport json, time\nwhile True:\n    print(json.dumps({'type': 'noise'}), flush=True)\n    time.sleep(0.2)\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        with unittest.mock.patch.dict(os.environ, {"SOLO_GM_MAX_SECONDS": "2"}):
            began = time.monotonic()
            result = gm.turn(self.root, "Go on and on.")
        self.assertLess(time.monotonic() - began, 15)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "The GM's turn ran past 2 seconds, so it was ended. Try again.")

    def test_a_turn_that_ran_out_of_model_calls_says_so_in_a_sentence(self):
        self.agent("claude", [{"type": "system", "subtype": "init", "session_id": "s"},
                              {"type": "result", "subtype": "error_max_turns", "is_error": False, "session_id": "s", "num_turns": 40}])
        result = gm.turn(self.root, "Hi")
        self.assertEqual(result["status"], "error")
        self.assertIn("used all the model calls a turn is allowed", result["error"])

    def spend(self, cost):
        return [*CLAUDE_STREAM[:-1], {**CLAUDE_STREAM[-1], "num_turns": 3, "total_cost_usd": cost, "usage": {"output_tokens": 80}}]

    def test_a_session_that_has_spent_its_budget_stops_and_says_how_to_raise_it(self):
        self.agent("claude", self.spend(6.0))
        self.assertEqual(gm.turn(self.root, "One.")["status"], "done")
        self.assertEqual(gm.turn(self.root, "Two.")["status"], "done")
        # What is left of the budget is a ceiling on the next turn too: 10 - 6.
        self.assertEqual(self.calls("claude")[1][self.calls("claude")[1].index("--max-budget-usd") + 1], "4.00")
        stopped = gm.turn(self.root, "Three.")
        self.assertEqual(stopped["status"], "error")
        self.assertEqual(stopped["error"], "This session has spent $12.00 of its $10.00 limit, so the GM stops here. Raise the limit with: solo gm budget 20")
        self.assertEqual(len(self.calls("claude")), 2)  # it never started
        self.assertEqual([t for t in self.said() if t[0] == "player"][-1], ("player", "Three."))  # the player's words stay
        gm.set_budget(usd=30)
        self.assertEqual(gm.turn(self.root, "Three.")["status"], "done")

    def test_a_new_session_starts_at_zero(self):
        self.agent("claude", self.spend(9.0))
        gm.turn(self.root, "One.")
        (self.root / ".solo" / "agent.json").unlink()  # the agent's session is gone: a fresh one starts
        self.assertEqual(gm.turn(self.root, "Two.")["status"], "done")

    def test_an_agent_that_cant_say_what_a_turn_costs_is_held_to_turns(self):
        self.agent("codex", CODEX_STREAM)
        with unittest.mock.patch.dict(os.environ, {"SOLO_GM_BUDGET_TURNS": "2"}):
            gm.turn(self.root, None, agent="codex")
            gm.turn(self.root, "I wait.", agent="codex")
            stopped = gm.turn(self.root, "And wait.", agent="codex")
        self.assertEqual(stopped["error"], "This session has run 2 GM turns, its limit, so the GM stops here. Raise the limit with: solo gm budget --turns 4")

    def test_the_players_limits_are_kept_and_the_pace_keeps_them(self):
        self.assertEqual(gm.budget(), {"usd": 10.0, "turns": 200})
        gm.set_budget(usd=25, turns=500)
        gm.set_pace("quick")
        self.assertEqual((gm.budget(), gm.pace()), ({"usd": 25.0, "turns": 500}, "quick"))
        with self.assertRaises(SoloError):
            gm.set_budget(usd=0)
        with unittest.mock.patch.dict(os.environ, {"SOLO_GM_BUDGET_USD": "3"}):
            self.assertEqual(gm.budget()["usd"], 3.0)

    def test_errors_are_one_plain_sentence_in_turn_json(self):
        self.agent("claude", [{"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "Credit balance is too low\nmore"}])
        result = gm.turn(self.root, "Hi")
        self.assertEqual((result["status"], result["error"]), ("error", "Credit balance is too low"))
        self.assertEqual(gm.status(self.root)["status"], "error")
        self.assertEqual(self.said(), [("player", "Hi")])  # the player's words stay; the next turn answers them

    def test_unsupported_agents_and_busy_turns_are_refused(self):
        result = gm.turn(self.root, "Hi", agent="pi")
        self.assertIn("can't write in the Book", result["error"])
        (self.root / ".solo").mkdir(exist_ok=True)
        import fcntl
        with open(self.root / ".solo" / "turn.lock", "w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaisesRegex(SoloError, "still writing"):
                gm.turn(self.root, "Hi")

    def test_a_campaign_that_cant_be_read_fails_the_turn_where_the_book_sees_it(self):
        self.agent("claude", CLAUDE_STREAM)
        with open(self.root / "events.jsonl", "a") as log:
            log.write("{damaged\n")
        result = gm.turn(self.root, "Hi")
        self.assertEqual(result["status"], "error")
        self.assertIn("is damaged", result["error"])
        self.assertEqual(gm.status(self.root)["status"], "error")  # not "thinking" for good

    def test_what_the_gm_is_doing_in_words(self):
        self.assertEqual(gm.doing("solo check sneaking --boons 1"), "rolling the dice")
        self.assertEqual(gm.doing("bash -lc 'solo commit {}'"), "writing it down")
        self.assertEqual(gm.doing("ls"), "thinking")

    def test_the_hook_never_records_a_gm_prompt_as_the_player(self):
        hook = {"hook_event_name": "UserPromptSubmit", "cwd": str(self.root), "prompt": gm.BOOK_PROMPT}
        cli._say_from_hook(json.dumps(hook))
        self.assertEqual(self.said(), [])

    def test_a_new_session_starts_on_the_table_without_reading_it_first(self):
        # The first prompt holds what `solo resume --book` and `solo scene` say: no model call spent on either.
        with self.session() as c:
            opening = gm.book_prompt(c)
            c.say("The gate is shut. What do you do?")
            c.say("I knock.", by="player")
            resumed = gm.book_prompt(c)
            with unittest.mock.patch.object(gm, "_PROMPT_BYTES", 100):
                too_long = gm.book_prompt(c)
        self.assertIn("Open the adventure from the scene below: describe the first scene", opening)
        self.assertTrue(resumed.startswith(gm.BOOK_PROMPT))
        self.assertIn("Read the scene below, then:", resumed)
        self.assertIn("## Player since\nI knock.", resumed)
        self.assertIn("## Exits", resumed)  # the scene digest
        self.assertNotIn("solo scene` for yourself", resumed)
        self.assertEqual(too_long, f"{gm.BOOK_PROMPT} Run `solo resume --book` and do exactly what it says.")

    def test_resume_for_the_book_doesnt_repeat_the_last_words(self):
        with self.session() as c:
            c.say("The gate is shut. What do you do?")
            c.say("I knock.", by="player")
            digest = cli.resume_digest(c, book=True)
        self.assertIn("Don't repeat or recap it", digest)
        self.assertNotIn("word for word", digest)
        self.assertIn("carry on from their words", digest)

    def test_a_lost_session_claude_reports_as_an_error_event_starts_over(self):
        # What Claude Code really prints for a session it no longer has: an error result
        # on stdout as well as the line on stderr.
        (self.root / ".solo").mkdir(exist_ok=True)
        (self.root / ".solo" / "agent.json").write_text(json.dumps({"agent": "claude", "session": "gone"}))
        lost = {"type": "result", "subtype": "error_during_execution", "is_error": True,
                "errors": ["No conversation found with session ID: gone"]}
        script = self.bin / "claude"
        script.write_text(textwrap.dedent(f"""\
            #!/usr/bin/env python3
            import json, sys
            if "--resume" in sys.argv:
                print("No conversation found with session ID: gone", file=sys.stderr)
                print(json.dumps({lost!r}))
                sys.exit(1)
            print({chr(10).join(json.dumps(e) for e in CLAUDE_STREAM)!r})
            """))
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        result = gm.turn(self.root, "Hello?")
        self.assertEqual(result["status"], "done")
        self.assertEqual(json.loads((self.root / ".solo" / "agent.json").read_text())["session"], "sess-1")

    def test_an_error_event_says_what_went_wrong(self):
        self.agent("claude", [{"type": "result", "subtype": "error_during_execution", "is_error": True, "errors": ["Rate limited"]}], code=1)
        self.assertEqual(gm.turn(self.root, "Hi")["error"], "Rate limited")

    def test_an_error_on_stderr_is_its_last_line_not_a_warning_before_it(self):
        script = self.bin / "claude"
        script.write_text("#!/bin/sh\necho 'Ignoring 26 permissions.allow entries' >&2\necho 'API key revoked' >&2\nexit 1\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        self.assertEqual(gm.turn(self.root, "Hi")["error"], "API key revoked")

    def test_a_stopped_turn_says_stopped_even_when_the_agent_exits_with_an_error(self):
        # Claude Code catches SIGTERM and exits 1: without the stop marker that reads as a failure.
        script = self.bin / "claude"
        script.write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import signal, sys, time
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
            print('{"type": "system", "subtype": "init", "session_id": "sess-1"}', flush=True)
            time.sleep(30)
            """))
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        import threading
        done = {}
        worker = threading.Thread(target=lambda: done.update(gm.turn(self.root, "Hi")))
        worker.start()
        for _ in range(100):
            if gm.status(self.root).get("agent_pid"):
                break
            time.sleep(0.05)
        gm.stop(self.root)
        worker.join(10)
        self.assertEqual((done["status"], done["error"]), ("stopped", ""))

    def test_a_turn_killed_with_the_machine_isnt_thinking_forever(self):
        (self.root / ".solo").mkdir(exist_ok=True)
        turn = self.root / ".solo" / "turn.json"
        # After a reboot the dead turn's pid can belong to anything: its start time gives it away.
        turn.write_text(json.dumps({"status": "thinking", "pid": os.getpid(), "started": 1}))
        self.assertEqual(gm.status(self.root)["status"], "stopped")
        turn.write_text(json.dumps({"status": "thinking", "pid": os.getpid(), "started": gm._started(os.getpid())}))
        self.assertEqual(gm.status(self.root)["status"], "thinking")

    def test_a_dead_turn_is_written_down_as_stopped_for_the_book(self):
        # The Book reads turn.json itself: left at "thinking", it would never let the player write again.
        (self.root / ".solo").mkdir(exist_ok=True)
        turn = self.root / ".solo" / "turn.json"
        dead = subprocess.Popen(["true"])
        dead.wait()
        turn.write_text(json.dumps({"id": "t1", "status": "writing", "pid": dead.pid, "text": "half a sen", "agent_pid": 9}))
        import fcntl
        with open(self.root / ".solo" / "turn.lock", "w") as held:  # a new turn starting: hands off
            fcntl.flock(held, fcntl.LOCK_EX)
            self.assertEqual(gm.status(self.root)["status"], "stopped")
            self.assertEqual(json.loads(turn.read_text())["status"], "writing")
        self.assertEqual(gm.status(self.root)["status"], "stopped")
        self.assertEqual((json.loads(turn.read_text())["status"], json.loads(turn.read_text())["agent_pid"]), ("stopped", None))

    def test_a_new_turn_ends_the_agent_a_killed_turn_left_behind(self):
        (self.root / ".solo").mkdir(exist_ok=True)
        sleeper = ["python3", "-c", "import time; time.sleep(30)"]
        orphan = subprocess.Popen(sleeper, env={**os.environ, "SOLO_GM": str(self.root)}, start_new_session=True)
        stranger = subprocess.Popen(sleeper, start_new_session=True)
        for process in (stranger, orphan):
            self.addCleanup(process.wait)
            self.addCleanup(process.kill)
        dead = subprocess.Popen(["true"])
        dead.wait()
        for pid in (orphan.pid, stranger.pid):
            (self.root / ".solo" / "turn.json").write_text(json.dumps({"status": "thinking", "pid": dead.pid, "agent_pid": pid}))
            self.agent("claude", CLAUDE_STREAM)
            gm.turn(self.root, "Hello again")
        self.assertIsNotNone(orphan.wait(5))  # this campaign's agent: ended
        self.assertIsNone(stranger.poll())    # anything else with that pid: left alone

    def test_a_resumed_turn_tells_the_gm_what_the_player_did_at_the_table(self):
        self.agent("claude", CLAUDE_STREAM)
        gm.turn(self.root, "I look around.")
        with self.session() as c:
            c.check("awareness", rng=Dice(3))
        gm.turn(self.root, "What do I see?")
        prompt = self.calls("claude")[1][-1]
        self.assertTrue(prompt.startswith(gm.PREAMBLE))  # so the hook never records it as the player
        self.assertIn("Awareness: 3 vs", prompt)
        self.assertTrue(prompt.endswith("What do I see?"))
        self.assertEqual(self.said()[-2], ("player", "What do I see?"))
        gm.turn(self.root, "And then?")  # nothing happened at the table: just their words
        self.assertEqual(self.calls("claude")[2][-1], "And then?")


class Notes(unittest.TestCase):
    def test_a_leading_note_to_itself_is_dropped_before_the_book(self):
        from solo.gm import drop_notes
        text = "Library exit is now open. Time to narrate the sequence.\n\nYou step onto the disc. What now?"
        self.assertEqual(drop_notes(text), "You step onto the disc. What now?")
        self.assertEqual(drop_notes("I commit my blade to the fight. What now?"), "I commit my blade to the fight. What now?")
        story = "The door opens.\n\nBeyond it, the player of the harp stops. What do you do?"
        self.assertEqual(drop_notes(story), story)  # a note only ever leads

    def test_a_gm_block_copied_into_the_reply_never_reaches_the_book(self):
        from solo.gm import drop_notes
        text = ("He comes for you.\n\n::: gm (for you only, not the player)\nWeapons pass through him: "
                "solo wound librarian 2d6.\n:::\n\nWhat do you do?")
        self.assertEqual(drop_notes(text), "He comes for you.\n\nWhat do you do?")
        self.assertEqual(drop_notes("It moves.\n\n::: gm\nunclosed secret"), "It moves.")
