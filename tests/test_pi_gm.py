"""Pi's JSON protocol and its campaign-only tool, without model calls."""

import json
import os
import shutil
import subprocess
import unittest
import unittest.mock

from helpers import CampaignTest
from test_gm import Agents
from solo import gm


def message(reason, text, cost=0.01):
    return {"type": "message_end", "message": {
        "role": "assistant", "model": "stand-in-pi-model", "stopReason": reason,
        "content": [{"type": "text", "text": text}],
        "usage": {"input": 10, "cacheRead": 20, "cacheWrite": 5, "output": 3, "cost": {"total": cost}},
    }}


PI_STREAM = [
    {"type": "session", "version": 3, "id": "pi-session-1"},
    {"type": "message_start", "message": {"role": "assistant"}},
    {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Let me check the table."}},
    message("toolUse", "Let me check the table."),
    {"type": "tool_execution_start", "toolName": "solo", "args": {"args": ["scene"]}},
    {"type": "message_start", "message": {"role": "assistant"}},
    {"type": "message_update", "assistantMessageEvent": {"type": "thinking_delta", "delta": "Private notes."}},
    {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Rain falls. "}},
    message("stop", "Rain falls. Where do you go?", cost=0.02),
    {"type": "agent_end", "messages": []},
    {"type": "agent_settled", "aborted": False},
]


class PiTest(Agents):
    def test_pi_turns_record_both_sides_resume_and_keep_usage(self):
        self.agent("pi", PI_STREAM)
        first = gm.turn(self.root, "I look around.", agent="pi")
        self.assertEqual(first["status"], "done")
        self.assertEqual(self.said(), [("player", "I look around."), ("gm", "Rain falls. Where do you go?")])
        self.assertEqual(first["model"], "stand-in-pi-model")
        self.assertEqual(first["usage"], {"model_calls": 2, "input_tokens": 70, "cached_input_tokens": 40,
                                         "output_tokens": 6, "cost_usd": 0.03})
        self.assertEqual(gm.spent(self.root, "pi-session-1")["cost_usd"], 0.03)
        gm.turn(self.root, "-- /help @private.txt", agent="pi")
        initial, resumed = self.calls("pi")
        self.assertNotIn("--session", initial)
        self.assertTrue(initial[-1].startswith(gm.BOOK_PROMPT))
        self.assertEqual(resumed[resumed.index("--session") + 1], "pi-session-1")
        self.assertEqual(resumed[-1], "-- /help @private.txt")
        self.assertFalse(any("private.txt" in arg for arg in resumed[:-1]))

    def test_pi_uses_only_its_explicit_engine_tool_and_the_players_pace(self):
        self.agent("pi", PI_STREAM)
        gm.set_pace("quick")
        gm.turn(self.root, "Hi", agent="pi")
        argv = self.calls("pi")[0][:-1]
        for flag in ("--no-extensions", "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-context-files", "--no-approve"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "solo")
        self.assertEqual(argv[argv.index("--thinking") + 1], "low")
        self.assertEqual(argv[argv.index("--session-dir") + 1], ".solo/pi-sessions")
        self.assertEqual(json.loads(gm.Pi().environment(self.root)["SOLO_GM_COMMANDS"]), list(gm.campaign_commands()))
        with unittest.mock.patch.dict(os.environ, {"SOLO_GM_MODEL": "a-test-provider/a-test-model"}):
            self.assertIn("a-test-provider/a-test-model", gm.Pi().command(None))

    def test_pi_deltas_do_not_publish_thinking_or_a_tool_preamble(self):
        live = gm.Live(self.root / ".solo" / "turn.json", None)
        result = {"session": None, "text": "", "error": ""}
        adapter = gm.Pi()
        for event in PI_STREAM[:3]:
            adapter.read(event, result, live)
        self.assertEqual(live.data["text"], "Let me check the table.")
        for event in PI_STREAM[3:7]:
            adapter.read(event, result, live)
        self.assertEqual(live.data["text"], "")
        self.assertEqual(live.data["doing"], "reading the scene")
        for event in PI_STREAM[7:]:
            adapter.read(event, result, live)
        self.assertEqual(live.data["text"], "Rain falls. Where do you go?")
        self.assertEqual(result["text"], live.data["text"])

    def test_pi_errors_aborts_and_truncation_never_commit_partial_narration(self):
        for reason, status in (("error", "error"), ("length", "error"), ("aborted", "stopped")):
            with self.subTest(reason=reason):
                event = message(reason, "This must not enter the transcript.")
                event["message"]["errorMessage"] = "Provider unavailable"
                self.agent("pi", [PI_STREAM[0], event])
                self.assertEqual(gm.turn(self.root, "Hello?", agent="pi")["status"], status)
                self.assertFalse(any(by == "gm" for by, text in self.said()))

    def test_pi_can_recover_after_a_provider_retry(self):
        failed = message("error", "")
        failed["message"]["errorMessage"] = "Please retry"
        self.agent("pi", [PI_STREAM[0], failed, {"type": "auto_retry_start"}, *PI_STREAM[5:]])
        self.assertEqual(gm.turn(self.root, "Hello?", agent="pi")["status"], "done")

    def test_a_missing_pi_session_starts_from_the_campaign_again(self):
        (self.root / ".solo" / "agent.json").write_text(json.dumps({"agent": "pi", "session": "missing"}))
        self.agent("pi", PI_STREAM, fail_resume=True)
        self.assertEqual(gm.turn(self.root, "Hello?", agent="pi")["status"], "done")
        first, second = self.calls("pi")
        self.assertIn("--session", first)
        self.assertNotIn("--session", second)
        self.assertTrue(second[-1].startswith(gm.BOOK_PROMPT))
        self.assertTrue(gm.Pi().lost("Session not found: missing"))
        self.assertFalse(gm.Pi().lost("Network request failed"))

    def test_pi_stops_at_the_model_call_limit(self):
        self.agent("pi", PI_STREAM)
        with unittest.mock.patch.dict(os.environ, {"SOLO_GM_MAX_TURNS": "1"}):
            result = gm.turn(self.root, "Hello?", agent="pi")
        self.assertEqual(result["status"], "error")
        self.assertIn("used all the model calls", result["error"])
        self.assertFalse(any(by == "gm" for by, text in self.said()))


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class PiToolTest(CampaignTest):
    def tool(self, requests):
        script = f"""
            import extension from {json.dumps((gm.REPO / 'solo' / 'pi-gm.mjs').as_uri())};
            let tool;
            extension({{ registerTool(value) {{ tool = value; }} }});
            const results = [];
            for (const args of {json.dumps(requests)}) {{
                try {{ results.push(await tool.execute('test', args, undefined, undefined, {{cwd: {json.dumps(str(self.root))}}})); }}
                catch (error) {{ results.push({{error: error.message}}); }}
            }}
            console.log(JSON.stringify(results));
        """
        done = subprocess.run(["node", "--input-type=module", "-"], input=script, text=True, capture_output=True,
                              env=gm.Pi().environment(self.root))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_pi_tool_runs_commits_directly_and_supports_stdin(self):
        marker = self.tmp / "must-not-exist"
        text = f"$(touch {marker}); `touch {marker}` > {marker}"
        results = self.tool([{"args": ["commit", json.dumps({"facts": {"gate.note": text}})]},
                             {"args": ["commit", "-"], "input": json.dumps({"facts": {"gate.second": "A lantern"}})}])
        self.assertTrue(all(not r["isError"] for r in results), results)
        self.assertFalse(marker.exists())
        with self.session() as c:
            self.assertEqual(c.state["facts"]["gate.note"], text)
            self.assertEqual(c.state["facts"]["gate.second"], "A lantern")

    def test_the_pi_tool_refuses_settings_other_campaigns_and_other_programs(self):
        requests = [{"args": [name]} for name in ("setup", "new", "gm", "desk", "prefs", "strike", "bash", "read", "import")]
        requests += [{"args": ["state", flag, str(self.tmp)]} for flag in ("-C", "-Celsewhere", "--campaign", "--camp", "--campaign=elsewhere")]
        self.assertTrue(all("error" in result for result in self.tool(requests)))
        self.assertFalse((self.tmp / "state" / "solo" / "gm.json").exists())
