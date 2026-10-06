import json
import shutil
import unittest

from helpers import CampaignTest, Dice, LikelihoodTest

from solo import SoloError, campaign, cli, packs


class CheckTest(CampaignTest):
    def test_a_condition_on_the_rolled_attribute_adds_a_bane(self):
        with self.session() as c:
            c.commit({"pc": {"conditions": {"add": ["dazed"]}}})
            event = c.check("sneaking", rng=Dice(4, 12))
        self.assertEqual((event["banes"], event["condition_banes"]), (1, ["dazed"]))
        self.assertEqual(event["outcome"]["result"], 12)
        self.assertFalse(event["outcome"]["success"])

    def test_attribute_checks_and_untrained_base_chance(self):
        with self.session() as c:
            attribute = c.check("Strength", rng=Dice(15))
            untrained = c.check("bushcraft", rng=Dice(5))
        self.assertEqual(attribute["outcome"]["target"], 15)
        self.assertTrue(attribute["outcome"]["success"])
        self.assertEqual(untrained["outcome"]["target"], 4)

    def test_unknown_names_get_suggestions(self):
        with self.session() as c, self.assertRaisesRegex(SoloError, "did you mean sneaking"):
            c.check("sneakin")


class PushTest(CampaignTest):
    def test_push_takes_the_chosen_condition_and_rerolls_once(self):
        with self.session() as c:
            c.check("sneaking", rng=Dice(12))
            with self.assertRaisesRegex(SoloError, "choose the condition"):
                c.push()
            pushed = c.push("scared", rng=Dice(3))
            with self.assertRaisesRegex(SoloError, "already pushed"):
                c.push("angry")
            conditions = c.state["pc"]["conditions"]
        self.assertTrue(pushed["outcome"]["success"])
        self.assertEqual(conditions, ["scared"])
        self.assertTrue(campaign.describe(pushed).endswith("; took scared"))  # the log says what it cost

    def test_successes_and_demons_cannot_be_pushed(self):
        with self.session() as c:
            c.check("swords", rng=Dice(3))
            with self.assertRaisesRegex(SoloError, "can't be pushed"):
                c.push("scared")
            c.check("swords", rng=Dice(20, 2, 1))  # the Demon rolls its effect and ticks the ritual clock: one omen
            with self.assertRaisesRegex(SoloError, "can't be pushed"):
                c.push("scared")


class CommitTest(CampaignTest):
    def test_attitude_moves_one_step_unless_overridden(self):
        with self.session() as c:
            with self.assertRaisesRegex(SoloError, "one step"):
                c.commit({"npc": {"orc_leader": {"attitude": "friendly"}}})
            c.commit({"npc": {"orc_leader": {"attitude": "friendly"}}, "override": "the adventure says so"})
            self.assertEqual(c.state["npcs"]["orc_leader"]["attitude"], 1)

    def test_dead_stays_dead_and_new_npcs_need_a_name(self):
        with self.session() as c:
            c.commit({"npc": {"orc_leader": {"fate": "dead"}}})
            with self.assertRaisesRegex(SoloError, "is dead"):
                c.commit({"npc": {"orc_leader": {"fate": "alive"}}})
            with self.assertRaisesRegex(SoloError, "give it a name"):
                c.commit({"npc": {"scout": {"attitude": "hostile"}}})
            c.commit({"npc": {"scout": {"name": "Orc scout", "attitude": "hostile"}}})
            scout = c.state["npcs"]["scout"]
        self.assertEqual((scout["attitude"], scout["met"]), (-2, True))

    def test_tracks_are_clamped_with_a_warning(self):
        with self.session() as c:
            event = c.commit({"pc": {"hp": "-20", "wp": "+3"}})
            tracks = c.state["pc"]["tracks"]
        self.assertEqual((tracks["hp"]["value"], tracks["wp"]["value"]), (0, 11))
        self.assertEqual(len(event["warnings"]), 2)

    def test_a_commit_that_gets_a_shape_wrong_is_told_what_it_holds_and_a_null_says_nothing(self):
        with self.session() as c:
            for payload, message in (({"time": "until dawn"}, r'time is a JSON object, like \{"stretch": 1\}, or words like "10 minutes"'),
                                     ({"facts": 3}, "facts is a JSON object, like"), ({"facts": [{"hall.alarm": True}]}, "facts is a JSON object, like"),
                                     ({"pc": "hp -2"}, "pc is a JSON object")):
                with self.subTest(payload=payload), self.assertRaisesRegex(SoloError, message):
                    c.commit(payload)
            c.commit({"clue": "a seen thing", "learn": None, "facts": None, "time": None})
            self.assertEqual(c.state["clues"], ["a_seen_thing"])

    def test_a_commits_time_can_be_in_the_systems_units_plural_or_in_the_clocks(self):
        with self.session() as c:
            before = c.state["time"]
            for spent, seconds in (({"rounds": 2}, 20), ({"stretch": 1}, 900), ({"minutes": 10}, 600), ({"hour": 1, "minute": 30}, 5400), ({"days": 1}, 86400)):
                c.commit({"time": spent})
                before += seconds
                self.assertEqual(c.state["time"], before, spent)
            with self.assertRaisesRegex(SoloError, "unknown time unit fortnights; the system has round, stretch, shift, and seconds, minutes, hours and days will do"):
                c.commit({"time": {"fortnights": 1}})

    def test_rejected_commits_write_nothing(self):
        with self.session() as c:
            for payload, message in (
                ({"mood": "grim"}, "unknown commit keys"),
                ({"pc": {"conditions": {"add": ["sleepy"]}}}, "unknown conditions"),
                ({"promise": {"id": "help"}}, "needs npc and terms"),
                ({"facts": {"Hall Alarm": True}}, "lowercase"),
                ({"time": {"fortnight": 1}}, "unknown time unit"),
                ({"faction": {"elves": "+1"}}, "isn't in the adventure"),
            ):
                with self.subTest(payload=payload), self.assertRaisesRegex(SoloError, message):
                    c.commit(payload)
            self.assertEqual(len(c.events), 1)


class ClockTest(CampaignTest):
    def test_time_and_facts_advance_clocks_and_roll_their_table(self):
        with self.session() as c:
            c.commit({"time": {"shift": 2}}, rng=Dice(3, 6))
            c.commit({"facts": {"hall.alarm": True}}, rng=Dice(1))
            clock = c.state["clocks"]["dark_ritual"]
            omens = [e["text"] for e in c.events if e["type"] == "table"]
        self.assertEqual(clock["value"], 3)
        self.assertEqual(len(omens), 3)

    def test_a_hidden_clock_stays_off_the_players_log_but_its_omens_are_felt(self):
        with self.session() as c:
            c.commit({"note": "the horn sounds", "facts": {"hall.alarm": True}}, rng=Dice(4))
            visible = [e["text"] for e in c.state["log"] if not e.get("hidden")]
            hidden = [e["type"] for e in c.state["log"] if e.get("hidden")]
            story = c.state["story"]
        self.assertEqual(hidden, ["clock"])
        self.assertEqual(visible[-2:], ["the horn sounds", "Omens of the ritual (4): A low chant rises from somewhere under your feet."])
        self.assertEqual(story[-1]["kind"], "omen")
        self.assertNotIn("ritual below", json.dumps(story))

    def test_a_full_clock_stops_ticking(self):
        with self.session() as c:
            c.commit({"clock": {"dark_ritual": "+6"}}, rng=Dice(*[2] * 6))
            c.commit({"clock": {"dark_ritual": "+1"}}, rng=Dice())
            clock = c.state["clocks"]["dark_ritual"]
            ticks = [e for e in c.events if e["type"] == "clock"]
        self.assertTrue(clock["full"])
        self.assertEqual(len(ticks), 6)


class RestTest(CampaignTest):
    def test_a_stretch_rest_recovers_heals_one_condition_and_takes_time(self):
        with self.session() as c:
            c.commit({"pc": {"hp": "-6", "wp": "-4", "conditions": {"add": ["scared", "angry"]}}})
            event = c.rest("stretch", rng=Dice(5, 2))
            pc = c.state["pc"]
        self.assertEqual((pc["tracks"]["hp"]["value"], pc["tracks"]["wp"]["value"]), (13, 9))
        self.assertEqual(pc["conditions"], ["angry"])
        self.assertEqual(event["rolls"], {"hp": 5, "wp": 2})
        self.assertEqual(c.state["time"], 900)
        self.assertEqual(campaign.describe(event), "Stretch rest; hp 8 -> 13; wp 7 -> 9; -scared; 15 min pass")

    def test_the_player_chooses_which_condition_heals(self):
        with self.session() as c:
            c.commit({"pc": {"conditions": {"add": ["scared", "angry"]}}})
            c.rest("stretch", heal="angry", rng=Dice(1, 1))
            with self.assertRaisesRegex(SoloError, "you don't have dazed"):
                c.rest("shift", heal="dazed")
        self.assertEqual(c.state["pc"]["conditions"], ["scared"])

    def test_a_rest_that_heals_nothing_says_which_does(self):
        with self.session() as c:
            c.commit({"pc": {"conditions": {"add": ["angry"]}}})
            with self.assertRaisesRegex(SoloError, "a round rest heals no conditions; a stretch rest or a shift rest does"):
                c.rest("round", heal="angry")
            self.assertEqual(c.state["pc"]["conditions"], ["angry"])

    def test_round_and_stretch_rests_are_once_per_shift(self):
        with self.session() as c:
            c.rest("round", rng=Dice(3))
            with self.assertRaisesRegex(SoloError, "already taken a round rest this shift"):
                c.rest("round", rng=Dice(3))
            c.commit({"time": {"shift": 1}}, rng=Dice(4))  # a new shift (and the ritual ticks)
            c.rest("round", rng=Dice(3))

    def test_a_shift_rest_restores_everything_and_the_ritual_moves_on(self):
        with self.session() as c:
            c.commit({"pc": {"hp": "-10", "conditions": {"add": ["dazed", "sickly"]}}})
            c.rest("shift", rng=Dice(6))  # the omen rolled when the hidden clock ticks
            pc, clock = c.state["pc"], c.state["clocks"]["dark_ritual"]
        self.assertEqual((pc["tracks"]["hp"]["value"], pc["conditions"]), (14, []))
        self.assertEqual(clock["value"], 1)

    def test_skills_that_need_training_cant_be_rolled_without_it(self):
        with self.session() as c, self.assertRaisesRegex(SoloError, "Animism can't be used without training"):
            c.check("animism")

    def test_the_panel_gets_the_rests_and_the_odds(self):
        with self.session() as c:
            labels = c.state["labels"]
        self.assertEqual(labels["rests"]["stretch"], {"label": "Stretch rest", "limit": 21600, "tend": True})
        self.assertEqual(labels["push_ability"], {"name": "Sole Survivor", "cost": "3 WP"})
        self.assertTrue(labels["dying"]["self_rally"] and labels["dying"]["self_save"])
        self.assertEqual(labels["rests"]["shift"]["limit"], None)
        self.assertEqual(labels["likelihood"], ["unlikely", "even", "likely"])  # the fortune chart's tilts
        self.assertEqual(labels["fortune"], ["yes_no", "number", "scale", "power", "quality", "reaction"])


class OracleAndMoveTest(LikelihoodTest):
    def test_npc_odds_follow_attitude_and_promises(self):
        with self.session() as c:
            self.assertEqual(c._odds_for("orc_leader"), "unlikely")
            c.commit({"promise": {"id": "warband_joins", "npc": "orc_leader", "terms": "joins the fight"}})
            self.assertEqual(c._odds_for("orc_leader"), "even")
            answer = c.ask("Does he come?", npc="orc_leader", rng=Dice(10))
        self.assertEqual((answer["chance"], answer["answer"]), (50, "yes, and"))

    def test_exits_by_id_or_label_and_forced_jumps(self):
        with self.session() as c:
            c.move("gate")
            c.move("Into the hall")
            with self.assertRaisesRegex(SoloError, "no exit"):
                c.move("final_battle")
            c.move("final_battle", force="the tunnel behind the throne")
            state = c.state
        self.assertEqual(state["scene"], "final_battle")
        self.assertEqual(state["visited"], ["road", "gate", "hall", "final_battle"])
        self.assertTrue(state["npcs"]["orc_leader"]["met"])

    def test_a_stop_trigger_ends_a_clock_for_good(self):
        with self.session() as c:
            c.commit({"time": {"shift": 1}}, rng=Dice(3))
            c.commit({"npc": {"priest": {"fate": "dead"}}})  # the ritual dies with its priest
            c.commit({"time": {"shift": 6}}, rng=Dice())  # no ticks, so no omens: Dice() has no faces
            with self.assertRaisesRegex(SoloError, "stopped for good"):
                c.commit({"clock": {"dark_ritual": "+1"}})
            clock = c.state["clocks"]["dark_ritual"]
            line = cli._clock_line(c, "dark_ritual")
            hidden = [e["text"] for e in c.state["log"] if e.get("hidden")]
        self.assertEqual((clock["value"], clock["full"], clock["stopped"]), (1, False, True))
        self.assertIn("stopped for good", line)
        self.assertNotIn("FULL", line)
        self.assertIn("The ritual below stops at 1/6", hidden)


class TornLogTest(CampaignTest):
    """A crash or a power cut in the middle of writing an event."""

    def log(self):
        return self.root / "events.jsonl"

    def test_a_half_written_last_event_is_set_aside_and_play_goes_on(self):
        count = len(self.log().read_text().splitlines())
        with open(self.log(), "a") as log:
            log.write('{"seq": 99, "type": "check", "stat": "swo')
        with self.session() as c:
            c.check("swords", rng=Dice(3))
            self.assertEqual(len(c.events), count + 1)
        self.assertEqual(len(self.log().read_text().splitlines()), count + 1)
        self.assertIn('"stat": "swo', (self.root / "events.jsonl.torn").read_text())

    def test_a_whole_last_event_without_its_newline_keeps_its_own_line(self):
        self.log().write_text(self.log().read_text().rstrip("\n"))
        with self.session() as c:
            count = len(c.events)
            c.check("swords", rng=Dice(3))
        with self.session() as c:
            self.assertEqual(len(c.events), count + 1)

    def test_damage_before_the_last_line_is_still_an_error(self):
        lines = self.log().read_text().splitlines()
        self.log().write_text("\n".join([lines[0][:20], *lines[1:]]) + "\n")
        with self.assertRaisesRegex(SoloError, "line 1 is damaged"):
            self.session().__enter__()

    def test_a_line_separator_in_a_message_stays_inside_its_event(self):
        # JSON keeps U+2028 and U+0085 as they are, and str.splitlines cuts at both: a pasted line read the whole log as damaged.
        text = "The bell tolls.\u2028Silence.\x85 What do you do?"
        with self.session() as c:
            c.say(text, "player")
        with self.session() as c:
            self.assertEqual(c.events[-1]["text"], text)


class ReplayTest(CampaignTest):
    """The log stays readable: an event the state can't take never reaches it, and packs
    edited after a campaign began don't lock the player out of it."""

    def test_an_event_the_state_cant_take_is_never_written(self):
        log = self.root / "events.jsonl"
        before = log.read_text()
        with self.assertRaises(KeyError):
            with self.session() as c:
                c.append("clock", clock="nowhere", value=1, full=False)
        self.assertEqual(log.read_text(), before)
        with self.session() as c:
            self.assertEqual(c.state["problems"], [])

    def test_a_command_that_fails_half_way_keeps_its_roll_and_a_true_state(self):
        with self.assertRaises(KeyError):
            with self.session() as c:
                c.check("sneaking", rng=Dice(15))
                c.append("clock", clock="nowhere", value=1, full=False)
        saved = json.loads((self.root / "state.json").read_text())
        with self.session() as c:
            self.assertEqual(c.events[-1]["type"], "check")  # a roll is never taken back
            rebuilt = campaign.snapshot(c.system, campaign.fold(c.system, c.adventure, c.events), c.adventure)
        self.assertEqual(saved, json.loads(json.dumps(rebuilt)))

    def test_an_adventure_edited_since_still_opens_and_says_what_broke(self):
        adventure = self.tmp / "red-tusk"
        shutil.copytree(self.adventure, adventure)
        root = campaign.create(self.tmp / "edited", self.system, adventure, self.character)
        with campaign.session(root) as c:
            c.commit({"clock": {"dark_ritual": "+1"}})
        spec = adventure / "adventure.toml"
        spec.write_text(spec.read_text().replace("[clocks.dark_ritual]", "[clocks.old_ritual]"))
        with campaign.session(root) as c:
            self.assertTrue(any("'dark_ritual'" in p for p in c.state["problems"]))
            self.assertIn("## Pack problems", cli.resume_digest(c))
            self.assertIn("## Pack problems", cli.scene_digest(c))
            c.save()
        self.assertGreater(json.loads((root / "state.json").read_text())["pack_problems"], 0)

    def test_a_broken_pack_is_reported_where_the_gm_reads(self):
        adventure = self.tmp / "red-tusk"
        shutil.copytree(self.adventure, adventure)
        root = campaign.create(self.tmp / "edited", self.system, adventure, self.character)
        spec = adventure / "adventure.toml"
        spec.write_text(spec.read_text() + '\n[clocks.broken]\nsegments = 4\nadvance = ["time:fortnight"]\n')
        with campaign.session(root) as c:
            self.assertTrue(c.problems)
            self.assertEqual(c.state["problems"], [])
            self.assertIn(c.problems[0], cli.scene_digest(c))

    def test_the_log_says_which_format_it_was_written_in(self):
        with self.session() as c:
            self.assertEqual(c.events[0]["format"], campaign.FORMAT)


class FoldTest(CampaignTest):
    def test_state_json_is_the_fold_of_the_log(self):
        with self.session() as c:
            c.move("gate")
            c.check("sneaking", rng=Dice(15))
            c.push("scared", rng=Dice(2))
            c.commit({"npc": {"orc_leader": {"attitude": "+1"}}, "time": {"stretch": 1}})
            c.say("The guard squints at you. What do you say?")
        saved = json.loads((self.root / "state.json").read_text())
        with self.session() as c:
            rebuilt = campaign.snapshot(c.system, campaign.fold(c.system, c.adventure, c.events), c.adventure)
        self.assertEqual(saved, json.loads(json.dumps(rebuilt)))


class TranscriptTest(CampaignTest):
    def test_what_was_said_is_kept_word_for_word(self):
        opening = "Rain on the road.\n\nThe hall's gate is shut. What do you do?"
        with self.session() as c:
            said = c.say(opening)
            self.assertEqual(c.state["last_said"], {"seq": said["seq"], "at": said["at"], "scene": "road", "text": opening})
            self.assertTrue(c.state["awaiting_player"])
            c.say("I knock.", "player")
            self.assertFalse(c.state["awaiting_player"])
            self.assertEqual(c.state["last_said"]["text"], opening)
        saved = json.loads((self.root / "state.json").read_text())
        self.assertEqual((saved["last_said"]["text"], saved["awaiting_player"]), (opening, False))

    def test_speech_stays_out_of_the_dice_log(self):
        with self.session() as c:
            c.say("What do you do?")
            c.check("sneaking", rng=Dice(3))
            self.assertEqual([e["type"] for e in c.state["log"]], ["created", "check"])
            self.assertEqual(campaign.describe(c.events[1]), 'GM: "What do you do?"')

    def test_the_same_words_twice_are_recorded_once(self):
        with self.session() as c:
            self.assertIsNotNone(c.say("What do you do?"))
            self.assertIsNone(c.say("  What do you do?\n"))
            self.assertIsNotNone(c.say("What do you do?", "player"))
            self.assertEqual(sum(e["type"] == "said" for e in c.events), 2)

    def test_empty_text_and_unknown_speakers_are_refused(self):
        with self.session() as c:
            with self.assertRaises(SoloError):
                c.say("   ")
            with self.assertRaises(SoloError):
                c.say("hello", "narrator")
            self.assertEqual(len(c.events), 1)


class OrcLeaderTest(CampaignTest):
    """The scenario from the design discussion: talk or fight, and what the finale makes of it."""

    def finale(self, c):
        scene = c.adventure["scenes"]["final_battle"]
        return [b["text"] for b in scene["branches"] if packs.evaluate(b["when"], c.state)]

    def test_a_kept_promise_brings_the_warband(self):
        with self.session() as c:
            c.move("gate")
            c.move("hall")
            self.assertTrue(c.check("persuasion", boons=1, rng=Dice(15, 6))["outcome"]["success"])
            c.commit({
                "npc": {"orc_leader": {"attitude": "+1", "memory": "Ragna returned his son's axe"}},
                "faction": {"orcs": "+1"},
                "promise": {"id": "warband_joins", "npc": "orc_leader", "terms": "joins the fight if his warriors are freed"},
            })
            c.move("cellar")
            c.commit({"note": "Ragna frees the three warriors", "promise": {"id": "warband_joins", "status": "kept"}})
            c.move("final_battle")
            self.assertEqual(self.finale(c), ["Grukk and the Red Tusk warband charge in behind you, as he promised."])

    def test_killing_him_turns_the_orcs(self):
        with self.session() as c:
            c.move("gate")
            c.move("hall")
            c.commit({"npc": {"orc_leader": {"fate": "dead"}}, "faction": {"orcs": "-1"}})
            c.move("cellar")
            c.move("final_battle")
            self.assertIn("they stand with the cult", self.finale(c)[0].lower())
            self.assertEqual(c.state["factions"]["orcs"]["standing"], -2)


if __name__ == "__main__":
    unittest.main()
