"""The action-roll family (Ironsworn): the roll, momentum and burning it, progress tracks, the
odds oracle, and a hero built from the stat array. They play on the bundled Ironsworn pack
(its rules are CC BY and live in the repository) and a small made-up adventure."""

import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from helpers import HRAFNA, IRONSWORN, OATH, CampaignTest, Dice
from test_cli import CliCase

from solo import SoloError, campaign, creation, generate, mechanics, packs


class ActionRollTest(unittest.TestCase):
    """The dice alone: an action die, a stat and adds against two challenge dice."""

    def roll(self, action, first, second, stat=2, adds=0, momentum=0):
        return mechanics.action_roll(stat, adds, momentum, Dice(action, first, second))

    def test_the_score_has_to_beat_a_die_and_ties_go_to_the_dice(self):
        self.assertEqual(self.roll(3, 4, 4)["hit"], "strong_hit")  # 3 + 2 = 5 beats 4 and 4
        self.assertEqual(self.roll(3, 5, 4)["hit"], "weak_hit")  # 5 doesn't beat 5
        self.assertEqual(self.roll(3, 5, 5)["hit"], "miss")
        self.assertEqual(self.roll(3, 9, 2)["hit"], "weak_hit")
        self.assertEqual((self.roll(3, 9, 2)["success"], self.roll(3, 5, 5)["success"]), (True, False))

    def test_the_score_never_passes_ten(self):
        rolled = self.roll(6, 10, 10, stat=3, adds=3)  # 12 on paper: 10 on the sheet, and 10 doesn't beat 10
        self.assertEqual((rolled["score"], rolled["hit"]), (10, "miss"))

    def test_matched_challenge_dice_are_a_twist_on_a_hit_or_a_miss(self):
        self.assertTrue(self.roll(6, 3, 3)["match"])
        self.assertEqual(self.roll(6, 3, 3)["hit"], "strong_hit")
        self.assertTrue(self.roll(1, 9, 9)["match"])
        self.assertFalse(self.roll(6, 3, 4)["match"])

    def test_negative_momentum_that_matches_the_action_die_cancels_it(self):
        dulled = self.roll(3, 4, 6, stat=2, adds=1, momentum=-3)  # the 3 counts for nothing: 2 + 1
        self.assertEqual((dulled["dulled"], dulled["score"], dulled["hit"]), (True, 3, "miss"))
        for momentum in (-2, 0, 3, 6):  # another number, none, or positive momentum that matches: no effect
            with self.subTest(momentum=momentum):
                self.assertEqual((self.roll(3, 4, 6, momentum=momentum)["dulled"], self.roll(3, 4, 6, momentum=momentum)["score"]), (False, 5))

    def test_a_progress_roll_has_no_action_die(self):
        rolled = mechanics.progress_roll(6, Dice(4, 6))
        self.assertEqual((rolled["score"], rolled["hit"], "action" in rolled), (6, "weak_hit", False))
        self.assertEqual(mechanics.progress_roll(0, Dice(1, 1))["hit"], "miss")

    def test_burning_cancels_the_dice_under_the_momentum(self):
        missed = self.roll(2, 5, 8, stat=2)  # a score of 4 against 5 and 8
        weak = mechanics.burn(missed, 6)  # 5 is under 6, 8 isn't
        self.assertEqual((weak["hit"], weak["cancelled"], weak["burned"]), ("weak_hit", [0], 6))
        self.assertEqual(mechanics.burn(missed, 9)["hit"], "strong_hit")
        self.assertEqual(mechanics.burn(self.roll(2, 5, 8), 8)["hit"], "weak_hit")  # 8 is not under 8

    def test_burning_that_changes_nothing_is_no_burn(self):
        self.assertIsNone(mechanics.burn(self.roll(2, 8, 9), 5))  # nothing under the momentum
        self.assertIsNone(mechanics.burn(self.roll(5, 1, 2), 9))  # a strong hit already
        self.assertIsNone(mechanics.burn(self.roll(3, 5, 9), 3))  # the die under it is one the score beats

    def test_impacts_lower_the_ceiling_and_the_reset(self):
        spec = {"min": -6, "max": 10, "reset": 2}
        self.assertEqual([mechanics.momentum_limits(spec, n) for n in range(4)],
                         [{"max": 10, "reset": 2}, {"max": 9, "reset": 1}, {"max": 8, "reset": 0}, {"max": 7, "reset": 0}])


class IronswornCampaignTest(CampaignTest):
    system, adventure, character = IRONSWORN, OATH, HRAFNA

    def hero(self, c):
        return c.state["pc"]

    def momentum(self, c):
        return c.state["pc"]["tracks"]["momentum"]


class MoveTest(IronswornCampaignTest):
    def test_a_move_rolls_the_stat_it_names(self):
        with self.session() as c:
            event = c.act("Face Danger", stat="edge", rng=Dice(4, 3, 9))  # 4 + 3 = 7 against 3 and 9
        self.assertEqual((event["move"], event["label"], event["stat"]), ("face_danger", "Face Danger", "edge"))
        self.assertEqual((event["outcome"]["score"], event["outcome"]["hit"]), (7, "weak_hit"))
        self.assertEqual(campaign.describe(event), "Face Danger +edge: 4 + 3 = 7 against 3 and 9: a weak hit")

    def test_adds_count_and_a_move_with_one_stat_needs_no_flag(self):
        with self.session() as c:
            event = c.act("gather information", adds=1, rng=Dice(2, 5, 5))  # +wits 2: 2 + 2 + 1 = 5, which doesn't beat 5
        self.assertEqual((event["stat"], event["outcome"]["adds"], event["outcome"]["score"], event["outcome"]["hit"]), ("wits", 1, 5, "miss"))
        self.assertTrue(event["outcome"]["match"])
        self.assertTrue(campaign.describe(event).endswith("a miss, and the dice match: a twist"))

    def test_a_move_needs_a_stat_it_lists(self):
        with self.session() as c:
            with self.assertRaisesRegex(SoloError, "Face Danger rolls .* say which with --stat"):
                c.act("face_danger")
            with self.assertRaisesRegex(SoloError, "Gather Information rolls \\+wits"):
                c.act("gather_information", stat="edge")
            with self.assertRaisesRegex(SoloError, "did you mean face_danger"):
                c.act("face dangr", stat="edge")
            self.assertEqual(len(c.events), 1)  # nothing was rolled: only the hero's arrival is in the log

    def test_the_book_says_highest_and_the_move_takes_the_highest(self):
        with self.session() as c:
            harm = c.act("endure harm", rng=Dice(1, 9, 9))  # iron 1, health 5: +health
            c.commit({"pc": {"health": "-3"}})
            again = c.act("endure harm", rng=Dice(1, 9, 9))  # health 2 now, iron 1
            lowest = c.act("heal", stat="lowest", rng=Dice(1, 9, 9))  # iron 1, wits 2
            highest = c.act("heal", stat="highest", rng=Dice(1, 9, 9))
        self.assertEqual((harm["stat"], harm["outcome"]["stat"]), ("health", 5))
        self.assertEqual((again["stat"], again["outcome"]["stat"]), ("health", 2))
        self.assertEqual((lowest["stat"], highest["stat"]), ("iron", "wits"))

    def test_a_move_with_no_roll_says_so(self):
        with self.session() as c, self.assertRaisesRegex(SoloError, "Face a Setback has no roll"):
            c.act("face a setback")

    def test_negative_momentum_dulls_the_action_die_in_the_move(self):
        with self.session() as c:
            c.commit({"pc": {"momentum": "-5"}})  # +2 -> -3
            event = c.act("face_danger", stat="edge", rng=Dice(3, 4, 6))
        self.assertEqual((event["outcome"]["dulled"], event["outcome"]["score"]), (True, 3))
        self.assertIn("(cancelled by negative momentum)", campaign.describe(event))

    def test_a_missed_roll_ticks_the_clock_that_listens_for_it(self):
        with self.session() as c:
            c.act("face_danger", stat="edge", rng=Dice(1, 9, 9))
            self.assertEqual(c.state["clocks"]["doom"]["value"], 1)
            c.act("face_danger", stat="edge", rng=Dice(6, 1, 2))  # a strong hit: the clock waits
            self.assertEqual(c.state["clocks"]["doom"]["value"], 1)
            c.act("face_danger", stat="edge", rng=Dice(1, 9, 9))
            self.assertEqual((c.state["clocks"]["doom"]["full"], c.state["facts"]["doom.here"]), (True, True))

    def test_a_scene_that_lists_voices_is_entered_without_rolling_them(self):
        with self.session() as c:
            c.adventure["scenes"]["road"]["voices"] = [{"skill": "edge", "text": "A loose stone."}]
            c.move("road")
            self.assertEqual([e for e in c.events if e["type"] == "voice"], [])
            self.assertEqual(c.state["scene"], "road")

    def test_skills_and_pushing_have_no_place_here(self):
        with self.session() as c:
            with self.assertRaisesRegex(SoloError, "rolls moves, not skills"):
                c.check("edge")
            with self.assertRaisesRegex(SoloError, "can't be pushed"):
                c.push("scared")

    def test_every_roll_lands_in_the_story_for_the_book(self):
        with self.session() as c:
            c.act("face_danger", stat="iron", rng=Dice(2, 8, 9))
        entry = [beat for beat in c.state["story"] if beat["kind"] == "roll"][-1]
        self.assertEqual((entry["label"], entry["purpose"], entry["outcome"]["hit"], entry["burned"]), ("Face Danger", "+iron", "miss", False))


class BurnTest(IronswornCampaignTest):
    def with_momentum(self, c, value):
        c.commit({"pc": {"momentum": f"{value - 2:+d}"}})

    def test_burning_turns_a_miss_into_a_weak_hit_and_resets_momentum(self):
        with self.session() as c:
            self.with_momentum(c, 6)
            missed = c.act("face_danger", stat="edge", rng=Dice(1, 5, 8))  # 4 against 5 and 8
            burned = c.burn()
            self.assertEqual(self.momentum(c)["value"], 2)
            state_after = campaign.fold(c.system, c.adventure, c.events)
        self.assertEqual((missed["outcome"]["hit"], burned["outcome"]["hit"], burned["outcome"]["cancelled"]), ("miss", "weak_hit", [0]))
        self.assertEqual((burned["of"], burned["label"], burned["changes"]["pc"]["tracks_was"]), (missed["seq"], "Face Danger", {"momentum": 6}))
        self.assertEqual(state_after["last_check"]["outcome"]["hit"], "weak_hit")
        self.assertIn("burned momentum 6 on Face Danger", campaign.describe(burned))

    def test_the_reset_is_lower_with_impacts(self):
        with self.session() as c:
            c.commit({"pc": {"conditions": {"add": ["wounded"]}, "momentum": "+4"}})  # one impact: ceiling 9, reset 1
            c.act("face_danger", stat="edge", rng=Dice(1, 5, 8))
            c.burn()
            self.assertEqual(self.momentum(c)["value"], 1)

    def test_a_roll_is_burned_once_and_only_when_it_helps(self):
        with self.session() as c:
            with self.assertRaisesRegex(SoloError, "nothing to burn momentum on"):
                c.burn()
            c.act("face_danger", stat="edge", rng=Dice(1, 9, 9))  # momentum 2: nothing under it
            with self.assertRaisesRegex(SoloError, "wouldn't change the roll"):
                c.burn()
            self.with_momentum(c, 9)
            c.act("face_danger", stat="edge", rng=Dice(6, 1, 1))  # already a strong hit
            with self.assertRaisesRegex(SoloError, "wouldn't change the roll"):
                c.burn()
            c.act("face_danger", stat="edge", rng=Dice(1, 5, 5))
            c.burn()
            with self.assertRaisesRegex(SoloError, "already burned"):
                c.burn()

    def test_momentum_at_or_below_zero_cannot_be_burned(self):
        with self.session() as c:
            self.with_momentum(c, 0)
            c.act("face_danger", stat="edge", rng=Dice(1, 5, 5))
            with self.assertRaisesRegex(SoloError, "only positive momentum"):
                c.burn()

    def test_a_progress_roll_ignores_momentum(self):
        with self.session() as c:
            self.with_momentum(c, 9)
            c.track_add("A vow", "vow", "dangerous")
            c.act("fulfill_your_vow", rng=Dice(9, 9))
            with self.assertRaisesRegex(SoloError, "ignored on a progress roll"):
                c.burn()


class OpenRollTest(IronswornCampaignTest):
    """A roll the player could still burn momentum on isn't the result yet: a clock listening for a
    miss waits until the story goes on, so a burn that turns the miss into a hit spares it."""

    def missed(self, c):
        c.commit({"pc": {"momentum": "+4"}})
        return c.act("face_danger", stat="edge", rng=Dice(1, 5, 8))  # 4 against 5 and 8, and a burn at 6 would help

    def test_the_clock_waits_while_a_burn_could_still_change_the_result(self):
        with self.session() as c:
            missed = self.missed(c)
            self.assertEqual((missed["open"], c.state["open_roll"], c.state["clocks"]["doom"]["value"]), (True, missed["seq"], 0))

    def test_a_burn_that_saves_the_roll_saves_the_clock(self):
        with self.session() as c:
            self.missed(c)
            c.burn()
            c.commit({"note": "it holds"})
            self.assertEqual((c.state["open_roll"], c.state["clocks"]["doom"]["value"]), (None, 0))

    def stands(self, c):
        self.assertEqual((c.state["open_roll"], c.state["clocks"]["doom"]["value"]), (None, 1))
        self.assertEqual([e["type"] for e in c.events if e["type"] == "settled"], ["settled"])
        self.assertTrue(next(e for e in c.state["log"] if e["type"] == "settled")["hidden"])  # the player's log doesn't show it

    def test_the_miss_that_stands_ticks_the_clock_at_the_next_commit(self):
        with self.session() as c:
            self.missed(c)
            c.commit({"note": "it stands"})
            self.stands(c)

    def test_a_roll_that_stands_is_no_longer_burned_or_offered(self):
        with self.session() as c:
            self.missed(c)
            self.assertIsNotNone(campaign.burn_option(c.state))
            c.commit({"note": "it stands"})  # and the clock listening for a miss ticks
            self.assertIsNone(campaign.burn_option(c.state))
            with self.assertRaisesRegex(SoloError, "that roll stands: the story went on after it"):
                c.burn()
            self.stands(c)

    def test_or_at_the_next_move_made(self):
        with self.session() as c:
            self.missed(c)
            c.act("face_danger", stat="edge", rng=Dice(6, 1, 1))
            self.stands(c)

    def test_or_when_the_hero_moves_on(self):
        with self.session() as c:
            self.missed(c)
            c.move("road")
            self.stands(c)

    def test_but_not_at_a_commit_a_move_or_a_move_made_that_is_refused(self):
        with self.session() as c:
            missed = self.missed(c)
            refused = ((c.commit, {"pc": {"health": "lots"}}), (c.commit, {"mood": 1}), (c.move, "nowhere"), (c.act, "face_dangr"),
                       (c.act, "face_danger", "edgy"), (c.act, "fulfill_your_vow"))
            for command, *arguments in refused:
                with self.subTest(arguments=arguments), self.assertRaises(SoloError):
                    command(*arguments)
            # Nothing written, the clock listening for a miss still waits, and the player can still burn.
            self.assertEqual((len(c.events), c.state["open_roll"], c.state["clocks"]["doom"]["value"]), (missed["seq"], missed["seq"], 0))
            self.assertEqual(c.burn()["outcome"]["hit"], "weak_hit")

    def test_a_roll_nothing_can_improve_is_final_at_once(self):
        with self.session() as c:
            missed = c.act("face_danger", stat="edge", rng=Dice(1, 9, 9))  # momentum 2: nothing to cancel
            self.assertNotIn("open", missed)
            self.assertEqual(c.state["clocks"]["doom"]["value"], 1)

    def test_it_replays_the_same(self):
        with self.session() as c:
            self.missed(c)
            c.commit({"note": "it stands"})
            self.missed(c)
            replayed = campaign.fold(c.system, c.adventure, c.events)
            self.assertEqual((replayed["open_roll"], replayed["clocks"], replayed["log"]), (c.state["open_roll"], c.state["clocks"], c.state["log"]))


class ProgressTest(IronswornCampaignTest):
    def test_a_mark_fills_what_the_rank_is_worth(self):
        ticks = {"troublesome": 12, "dangerous": 8, "formidable": 4, "extreme": 2, "epic": 1}
        with self.session() as c:
            for rank, worth in ticks.items():
                c.track_add(f"A {rank} vow", "vow", rank)
                mark = c.track_mark(f"a_{rank}_vow")
                self.assertEqual((c.state["progress"][f"a_{rank}_vow"]["ticks"], mark["now"]["ticks"]), (worth, worth), rank)
            c.track_mark("a_dangerous_vow", times=3)
            self.assertEqual(c.state["progress"]["a_dangerous_vow"]["ticks"], 32)
            over = c.track_mark("a_dangerous_vow", times=3)  # the track is ten boxes and no more
            self.assertEqual((over["now"]["ticks"], over["boxes"]), (40, 10))

    def test_bonds_are_a_track_every_hero_has_and_a_mark_is_a_tick(self):
        with self.session() as c:
            self.assertEqual(c.state["progress"]["bonds"], {"name": "Bonds", "kind": "bonds", "rank": None, "ticks": 0, "ended": None})
            c.track_mark("bonds")
            c.track_mark("bonds", times=4)
            self.assertEqual(c.state["progress"]["bonds"]["ticks"], 5)
            with self.assertRaisesRegex(SoloError, "every hero has one bonds track"):
                c.track_add("More bonds", "bonds")
            with self.assertRaisesRegex(SoloError, "it doesn't end"):
                c.track_end("bonds", "done")

    def test_a_track_needs_a_kind_and_a_rank_the_game_knows(self):
        with self.session() as c:
            with self.assertRaisesRegex(SoloError, "a track is one of: vow, journey, combat"):
                c.track_add("Something", "quest", "dangerous")
            with self.assertRaisesRegex(SoloError, "give the vow a rank"):
                c.track_add("Something", "vow")
            with self.assertRaisesRegex(SoloError, "give the vow a rank"):
                c.track_add("Something", "vow", "mighty")
            first, second = c.track_add("The road", "journey", "formidable"), c.track_add("The road", "journey", "formidable")
        self.assertEqual((first["id"], second["id"]), ("the_road", "the_road_2"))

    def test_ticks_and_rank_can_be_corrected(self):
        with self.session() as c:
            c.track_add("A vow", "vow", "dangerous")
            c.track_mark("a_vow", times=3)
            recommit = c.track_set("a_vow", ticks=4, rank="formidable")  # a miss on the vow: all but one box cleared, rank up
            self.assertEqual((c.state["progress"]["a_vow"]["ticks"], c.state["progress"]["a_vow"]["rank"]), (4, "formidable"))
            c.track_set("a_vow", ticks="+8")
            c.track_set("a_vow", ticks="-4")
            self.assertEqual(c.state["progress"]["a_vow"]["ticks"], 8)
            with self.assertRaisesRegex(SoloError, "set what"):
                c.track_set("a_vow")
            with self.assertRaisesRegex(SoloError, "a rank is one of"):
                c.track_set("a_vow", rank="mighty")
            with self.assertRaisesRegex(SoloError, "has no rank to change"):
                c.track_set("bonds", rank="epic")
        self.assertEqual((recommit["was"], recommit["now"]["ticks"], recommit["boxes"]), ({"ticks": 24, "rank": "dangerous"}, 4, 1))
        self.assertEqual(campaign.describe(recommit), "A vow set: ticks 24 -> 4, rank dangerous -> formidable")

    def test_an_ended_track_is_gone_from_play_but_not_from_the_log(self):
        with self.session() as c:
            c.track_add("A vow", "vow", "epic")
            ended = c.track_end("a_vow", "fulfilled")
            self.assertEqual(c.state["progress"]["a_vow"]["ended"], "fulfilled")
            with self.assertRaisesRegex(SoloError, "no open track called 'a_vow'"):
                c.track_mark("a_vow")
        self.assertEqual(campaign.describe(ended), "A vow ends: fulfilled")

    def test_a_progress_roll_counts_full_boxes_only(self):
        with self.session() as c:
            c.track_add("A vow", "vow", "dangerous")
            c.track_mark("a_vow", times=3)  # 24 ticks: six boxes
            c.track_set("a_vow", ticks="+3")  # and three ticks toward the seventh, which don't count
            rolled = c.act("fulfill your vow", rng=Dice(4, 6))
        self.assertEqual((rolled["outcome"]["progress"], rolled["outcome"]["hit"], rolled["track"]), (6, "weak_hit", "a_vow"))
        self.assertEqual(campaign.describe(rolled), "Fulfill Your Vow (A vow): 6 boxes filled against 4 and 6: a weak hit")

    def test_a_progress_move_needs_to_know_which_track(self):
        with self.session() as c:
            with self.assertRaisesRegex(SoloError, "which vow"):
                c.act("fulfill_your_vow")
            c.track_add("First", "vow", "dangerous")
            c.track_add("Second", "vow", "dangerous")
            c.track_add("The road", "journey", "dangerous")
            with self.assertRaisesRegex(SoloError, "which vow"):
                c.act("fulfill_your_vow", rng=Dice(1, 1))
            with self.assertRaisesRegex(SoloError, "The road is a journey, and this move reads a vow"):
                c.act("fulfill_your_vow", track="the_road")
            named = c.act("fulfill_your_vow", track="Second", rng=Dice(1, 1))
            journey = c.act("reach_your_destination", rng=Dice(1, 1))  # the only journey open
            bonds = c.act("write_your_epilogue", rng=Dice(1, 1))
        self.assertEqual((named["track"], journey["track"], bonds["track"]), ("second", "the_road", "bonds"))

    def test_a_vow_is_a_moment_in_the_story(self):
        with self.session() as c:
            c.track_add("A vow", "vow", "dangerous")
            c.track_end("a_vow", "forsaken")
            kinds = [beat["kind"] for beat in c.state["story"]]
            beats = [m["text"] for m in campaign.moments(c.chronology()) if m["kind"] == "progress"]
        self.assertEqual(kinds[-2:], ["event", "event"])
        self.assertEqual(beats, ["vow begun: A vow (dangerous)", "A vow ends: forsaken"])

    def test_a_vow_can_be_recalled_by_its_words(self):
        with self.session() as c:
            c.track_add("Silence the bell", "vow", "dangerous")
            c.track_end("silence_the_bell", "forsaken")
            found = campaign.recall(c.chronology(), c.state, "bell")
        self.assertEqual([f["text"] for f in found], ["Silence the bell ends: forsaken", "vow begun: Silence the bell (dangerous)"])

    def test_it_is_all_in_the_log_and_replays_the_same(self):
        with self.session() as c:
            c.track_add("A vow", "vow", "formidable")
            c.track_mark("a_vow", times=2)
            c.commit({"pc": {"momentum": "+4"}})
            c.act("face_danger", stat="edge", rng=Dice(1, 5, 8))
            c.burn()
            c.track_mark("bonds")
            c.track_end("a_vow", "fulfilled")
            replayed = campaign.fold(c.system, c.adventure, c.events)
            self.assertEqual(replayed["progress"], c.state["progress"])
            self.assertEqual(replayed["pc"], c.state["pc"])
            self.assertEqual(replayed["last_check"], c.state["last_check"])


class MomentumTest(IronswornCampaignTest):
    def test_a_commit_moves_momentum_inside_its_range(self):
        with self.session() as c:
            event = c.commit({"pc": {"momentum": "+3"}})
            self.assertEqual(self.momentum(c)["value"], 5)
            high = c.commit({"pc": {"momentum": "+20"}})
            self.assertEqual(self.momentum(c)["value"], 10)
            low = c.commit({"pc": {"momentum": "-30"}})
            self.assertEqual(self.momentum(c)["value"], -6)
        self.assertEqual(campaign.describe(event), "momentum 2 -> 5")
        self.assertEqual((high["warnings"], low["warnings"]), (["momentum stops at 10 (range -6-10)"], ["momentum stops at -6 (range -6-10)"]))

    def test_impacts_lower_the_ceiling_and_the_reset(self):
        with self.session() as c:
            c.commit({"pc": {"momentum": "+8"}})
            c.commit({"pc": {"conditions": {"add": ["wounded"]}}})
            self.assertEqual({k: self.momentum(c)[k] for k in ("value", "max", "reset")}, {"value": 9, "max": 9, "reset": 1})
            c.commit({"pc": {"conditions": {"add": ["shaken", "maimed"]}}})
            self.assertEqual({k: self.momentum(c)[k] for k in ("value", "max", "reset")}, {"value": 7, "max": 7, "reset": 0})
            c.commit({"pc": {"conditions": {"remove": ["wounded", "shaken", "maimed"]}}})
            self.assertEqual({k: self.momentum(c)[k] for k in ("value", "max", "reset")}, {"value": 7, "max": 10, "reset": 2})

    def test_an_impact_keeps_its_track_from_rising_until_it_is_cleared(self):
        with self.session() as c:
            c.commit({"pc": {"health": "-3", "conditions": {"add": ["wounded"]}}})
            held = c.commit({"pc": {"health": "+2"}})
            self.assertEqual(c.state["pc"]["tracks"]["health"]["value"], 2)
            self.assertEqual(held["warnings"], ["health can't rise while wounded is marked: clear it first"])
            c.commit({"pc": {"health": "-1"}})  # falling is fine
            c.commit({"pc": {"conditions": {"remove": ["wounded"]}, "health": "+2"}})  # cleared in the same commit
            self.assertEqual(c.state["pc"]["tracks"]["health"]["value"], 3)
            c.commit({"pc": {"conditions": {"add": ["encumbered"]}, "supply": "-1"}})  # holds nothing
            c.commit({"pc": {"supply": "+1"}})
            self.assertEqual(c.state["pc"]["tracks"]["supply"]["value"], 5)

    def test_a_hero_takes_a_new_asset_or_loses_one_by_commit(self):
        with self.session() as c:
            commit = c.commit({"pc": {"abilities": {"add": ["Horse", "Archer"], "remove": ["Hawk", "Storyweaver"]}}})
            self.assertEqual(self.hero(c)["abilities"], ["Archer", "Wayfinder", "Horse"])  # Archer was there already; Storyweaver never was
        self.assertEqual(campaign.describe(commit), "learns Horse; loses Hawk")

    def test_the_other_tracks_stay_between_zero_and_five(self):
        with self.session() as c:
            commit = c.commit({"pc": {"spirit": "-9"}})
        self.assertEqual(c.state["pc"]["tracks"]["spirit"]["value"], 0)
        self.assertEqual(commit["warnings"], ["spirit stops at 0 (range 0-5)"])

    def test_a_hero_carried_into_a_new_story_starts_over_at_the_reset(self):
        with self.session() as c:
            c.commit({"pc": {"momentum": "+7", "health": "-2", "conditions": {"add": ["wounded", "shaken"]}}})
        sheet = campaign.hero(self.root)
        self.assertNotIn("momentum", sheet["tracks"])
        rebuilt = campaign.character_sheet(sheet, packs.load_system(IRONSWORN))
        self.assertEqual(rebuilt["tracks"]["momentum"], {"value": 2, "min": -6, "max": 10, "reset": 2})
        self.assertEqual((rebuilt["tracks"]["health"], rebuilt["conditions"]), ({"value": 5, "max": 5}, []))

    def test_the_bonds_a_hero_made_go_with_them_and_their_vows_do_not(self):
        with self.session() as c:
            c.track_mark("bonds", times=6)
            c.track_add("A vow", "vow", "dangerous")
        later = self.tmp / "later"
        root = campaign.create(later, IRONSWORN, OATH, campaign.hero(self.root))
        with campaign.session(root) as c:
            self.assertEqual(sorted(c.state["progress"]), ["bonds"])
            self.assertEqual(c.state["progress"]["bonds"]["ticks"], 6)
            self.assertEqual(c.state["log"][0]["type"], "created")  # the first line of the story is its beginning


class OddsOracleTest(IronswornCampaignTest):
    def test_each_odds_is_a_chance_of_yes_on_a_d100(self):
        edges = {"small chance": 90, "unlikely": 75, "50/50": 50, "likely": 25, "almost certain": 10}  # the highest roll that is still a no
        with self.session() as c:
            for level, top in edges.items():
                with self.subTest(level=level):
                    no, yes = c.ask("Is it so?", likely=level, rng=Dice(top)), c.ask("Is it so?", likely=level, rng=Dice(top + 1))
                    self.assertEqual((no["answer"], yes["answer"]), ("no", "yes"))

    def test_doubles_are_a_twist_yes_or_no(self):
        with self.session() as c:
            matches = {roll: c.ask("Is it so?", likely="50/50", rng=Dice(roll))["match"] for roll in (10, 11, 12, 22, 99, 100)}
        self.assertEqual(matches, {10: False, 11: True, 12: False, 22: True, 99: True, 100: True})

    def test_the_odds_default_to_even_and_follow_an_npc_when_asked_to(self):
        with self.session() as c:
            plain = c.ask("Is it so?", rng=Dice(60))
            even = c.ask("Is it so?", likely="even", rng=Dice(60))
            friend = c.ask("Will he help?", npc="merchant", rng=Dice(30))  # friendly: one step above even
            with self.assertRaisesRegex(SoloError, "the odds are one of: small chance, unlikely, 50/50, likely, almost certain"):
                c.ask("Is it so?", likely="probably")
            with self.assertRaisesRegex(SoloError, "no columns"):
                c.ask("Is it so?", kind="number")
        self.assertEqual((plain["likely"], even["likely"], friend["likely"], friend["answer"]), ("50/50", "50/50", "likely", "yes"))
        self.assertEqual(campaign.describe(plain), 'asked "Is it so?" (odds 50/50, rolled 60): yes')

    def test_the_table_offers_the_odds_of_the_system(self):
        with self.session() as c:
            self.assertEqual(c.state["labels"]["likelihood"], ["small chance", "unlikely", "50/50", "likely", "almost certain"])

    def test_two_words_to_read_come_from_the_action_and_theme_tables(self):
        with self.session() as c:
            words = c.meaning("What does he want?", rng=Dice(1, 2))["words"]
        tables = packs.load_system(IRONSWORN)["tables"]
        row = lambda table, roll: next(r["text"] for r in tables[table]["results"] if r["range"][0] <= roll <= r["range"][1])
        self.assertEqual(words, [row("action", 1), row("theme", 2)])


class CreationTest(unittest.TestCase):
    def test_the_stat_array_is_dealt_across_the_stats(self):
        system = packs.load_system(IRONSWORN)
        for seed in range(6):
            with self.subTest(seed=seed):
                hero = creation.character(system, "random", seed=seed)
                self.assertEqual(sorted(hero["attributes"].values()), [1, 1, 2, 2, 3])
                self.assertEqual(hero["tracks"], {"health": 5, "spirit": 5, "supply": 5, "momentum": 2})
                self.assertEqual(len(set(hero["abilities"])), 3)
                names = {asset["name"] for asset in system["assets"].values()}
                self.assertLessEqual(set(hero["abilities"]), names)
                self.assertIn(hero["name"], system["creation"]["names"]["any"])
        self.assertEqual(creation.character(system, "random", seed=4), creation.character(system, "random", seed=4))
        dealt = {tuple(creation.character(system, "random", seed=s)["attributes"].values()) for s in range(6)}
        self.assertGreater(len(dealt), 1)

    def test_a_random_hero_starts_a_campaign(self):
        system = packs.load_system(IRONSWORN)
        sheet = creation.character(system, "random", seed=2)
        pc = campaign.character_sheet(sheet, system)
        self.assertEqual((pc["tracks"]["momentum"]["value"], pc["tracks"]["momentum"]["reset"]), (2, 2))
        self.assertEqual(pc["skills"], {})


class PackTest(unittest.TestCase):
    def setUp(self):
        self.system = packs.load_system(IRONSWORN)

    def test_the_bundled_game_is_complete_and_valid(self):
        self.assertEqual(packs.missing(self.system), [])
        self.assertEqual(packs.validate(self.system, packs.load_adventure(OATH)), [])
        self.assertEqual(len(self.system["moves"]), 35)
        for name in ("face_danger", "strike", "swear_an_iron_vow", "fulfill_your_vow", "pay_the_price", "ask_the_oracle"):
            self.assertIn(name, self.system["moves"])

    def test_the_moves_come_in_the_books_order_not_the_alphabets(self):
        self.assertEqual(list(self.system["moves"])[:4], ["face_danger", "secure_an_advantage", "gather_information", "heal"])
        self.assertEqual(list(self.system["moves"])[-2:], ["pay_the_price", "ask_the_oracle"])

    def test_it_has_no_book_to_wait_for(self):
        for hero in ("hrafna", "torvald", "eydis"):
            campaign.character_sheet(creation.character(self.system, hero), self.system)

    def test_what_the_moves_can_roll_is_on_the_sheet(self):
        for move_id, move in self.system["moves"].items():
            for stat in move.get("stats", []):
                self.assertTrue(stat in self.system["attributes"] or stat in self.system["tracks"], (move_id, stat))
        self.assertEqual(self.system["moves"]["endure_harm"]["pick"], "highest")
        self.assertEqual(self.system["moves"]["fulfill_your_vow"]["track"], "vow")
        self.assertEqual(self.system["moves"]["end_the_fight"]["track"], "combat")
        self.assertEqual(self.system["moves"]["reach_your_destination"]["track"], "journey")
        self.assertEqual(self.system["moves"]["write_your_epilogue"]["track"], "bonds")

    def test_a_voice_is_a_problem_in_a_game_with_no_skills_to_roll_quietly(self):
        adventure = packs.load_adventure(OATH)
        adventure["scenes"]["road"]["voices"] = [{"skill": "edge", "text": "A loose stone."}]
        self.assertEqual(packs.validate(self.system, adventure),
                         ["scene road: a game of moves has no quiet skill rolls, so a voice is never heard: write what the hero notices into the scene's text"])

    def test_the_campaign_generator_says_it_does_not_write_games_of_moves_yet(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaisesRegex(SoloError, "Ironsworn is a game of moves"):
            generate.new(Path(folder) / "salt", IRONSWORN, "a smuggler coast where the dead keep the lighthouses")

    def test_every_page_of_it_gives_its_credit(self):
        pages = {p["title"]: p for p in packs.engine_rules(self.system)}
        for title in ("Face Danger", "Strike", "Slayer", "Hawk"):
            with self.subTest(page=title):
                self.assertIn("created by Shawn Tomkin", pages[title]["text"])
                self.assertIn("Creative Commons Attribution 4.0", pages[title]["text"])
                self.assertIn("Ironsworn", pages[title]["text"])
        self.assertIn("p. 60", pages["Face Danger"]["text"])
        self.assertIn("solo act face_danger", pages["Face Danger"]["text"])

    def test_the_files_come_from_the_import_and_say_so(self):
        for folder in ("moves", "tables", "assets"):
            files = sorted((IRONSWORN / folder).glob("*.toml"))
            self.assertTrue(files, folder)
            for path in files:
                first = path.read_text(encoding="utf-8").splitlines()[0]
                self.assertTrue(first.startswith("# Generated by `solo import datasworn`"), path)
                self.assertIn("CC BY 4.0", first, path)

    def test_only_what_is_under_cc_by_is_here(self):
        # The rest of the book (NPCs, the atlas, the truths) is NC-SA and never comes in.
        self.assertEqual(sorted(p.name for p in IRONSWORN.iterdir()), ["NOTICE.md", "assets", "characters", "creation.toml", "moves", "system.toml", "tables"])
        self.assertIn("created by Shawn Tomkin", (IRONSWORN / "NOTICE.md").read_text(encoding="utf-8"))

    def test_the_rules_are_found_by_what_a_gm_would_ask(self):
        folders = [IRONSWORN / "rules"]
        extra = packs.engine_rules(self.system)
        for topic, title in (("face danger", "Face Danger"), ("momentum", "Momentum"), ("progress", "Progress tracks"), ("iron vow", "Swear an Iron Vow"),
                             ("ask the oracle", "Asking the oracle")):
            with self.subTest(topic=topic):
                self.assertEqual(packs.search_rules(folders, topic, extra)[0][0]["title"], title)

    def test_a_move_that_names_a_stat_the_sheet_lacks_is_a_problem(self):
        system = packs.load_system(IRONSWORN)
        system["moves"]["face_danger"] = {**system["moves"]["face_danger"], "stats": ["luck"]}
        system["moves"]["strike"] = {**system["moves"]["strike"], "kind": "progress", "track": "quest"}
        system["moves"]["clash"] = {**system["moves"]["clash"], "outcomes": {"miss": "no"}, "oracle": ["nowhere"]}
        system["momentum"] = {"min": 1, "max": 10, "reset": 2}
        problems = packs.validate(system)
        for text in ("move face_danger: rolls +luck", "move strike: reads a quest track", "move clash: [outcomes] needs", "move clash: sends you to unknown table nowhere",
                     "[momentum] needs whole numbers"):
            self.assertTrue(any(text in problem for problem in problems), (text, problems))


class MoveCommandTest(CliCase):
    """What the GM types: `solo act`, `solo burn`, `solo track`, and what comes back."""

    def setUp(self):
        super().setUp()
        code, _, err = self.solo("new", str(OATH), "--dir", self.game, "--character", "hrafna")
        self.assertEqual(code, 0, err)

    def act(self, *args, dice):
        with unittest.mock.patch("solo.cli._rng", return_value=Dice(*dice)):
            code, out, err = self.solo("-C", self.game, *args)
        return code, (json.loads(out) if out.startswith("{") else out), err

    def test_a_move_comes_back_with_the_books_words_for_the_result(self):
        code, report, err = self.act("act", "face_danger", "--stat", "edge", dice=(1, 5, 9))  # 4: a miss
        self.assertEqual(code, 0, err)
        self.assertEqual(report["summary"], "Face Danger +edge: 1 + 3 = 4 against 5 and 9: a miss")
        self.assertEqual(report["says"], packs.load_system(IRONSWORN)["moves"]["face_danger"]["outcomes"]["miss"])
        self.assertNotIn("burn", report)  # momentum 2 has nothing to cancel

    def test_a_match_is_named_a_twist_and_a_burn_that_would_help_is_offered(self):
        self.act("commit", "{\"pc\": {\"momentum\": \"+4\"}}", dice=())
        _, report, _ = self.act("act", "face_danger", "--stat", "edge", dice=(1, 5, 5))
        self.assertIn("The challenge dice match: a twist", report["says"])
        self.assertEqual(report["burn"], "solo burn (the player's choice): momentum 6 cancels the challenge dice under it, strong hit instead of miss, and goes back to 2")
        code, burned, _ = self.act("burn", dice=())
        self.assertEqual((code, burned["event"]["outcome"]["hit"]), (0, "strong_hit"))
        self.assertIn("On a **strong hit**", burned["says"])
        code, _, err = self.act("burn", dice=())
        self.assertEqual((code, "already burned" in err), (1, True))

    def test_a_vow_is_sworn_marked_and_fulfilled(self):
        self.assertEqual(self.act("track", "add", "Slay the wight", "--kind", "vow", "--rank", "dangerous", dice=())[1]["summary"], "vow begun: Slay the wight (dangerous)")
        self.assertEqual(self.act("track", "mark", "slay_the_wight", "--times", "2", dice=())[1]["summary"], "progress on Slay the wight: 4 boxes (marked 2 times)")
        self.assertEqual(self.act("track", "set", "slay_the_wight", "--ticks", "+3", dice=())[1]["summary"], "Slay the wight set: ticks 16 -> 19")
        self.assertEqual(self.act("track", "set", "slay_the_wight", "--ticks", "20", dice=())[1]["summary"], "Slay the wight set: ticks 19 -> 20")
        _, listed, _ = self.act("track", "list", dice=())
        self.assertIn("- slay_the_wight: Slay the wight (dangerous vow): 5 of 10 boxes", listed)
        self.assertIn("- bonds: Bonds: 0 of 10 boxes", listed)
        _, report, _ = self.act("act", "fulfill_your_vow", dice=(4, 6))
        self.assertEqual(report["summary"], "Fulfill Your Vow (Slay the wight): 5 boxes filled against 4 and 6: a weak hit")
        self.assertIn("more to be done", report["says"])
        self.assertEqual(self.act("track", "end", "slay_the_wight", "--how", "fulfilled", dice=())[1]["summary"], "Slay the wight ends: fulfilled")
        self.assertNotIn("slay_the_wight", self.act("track", "list", dice=())[1])

    def test_the_gm_reads_the_tracks_and_the_stats_in_the_scene(self):
        self.act("track", "add", "The road north", "--kind", "journey", "--rank", "formidable", dice=())
        self.act("track", "mark", "the_road_north", dice=())
        _, scene, _ = self.act("scene", dice=())
        self.assertIn("## Progress tracks\n- bonds: Bonds: 0 of 10 boxes\n- the_road_north: The road north (formidable journey): 1 of 10 boxes", scene)
        self.assertIn("Hrafna Voss: health 5/5, spirit 5/5, supply 5/5, momentum +2 (to 10, resets to 2)", scene)
        self.assertIn("Stats: edge 3, heart 1, iron 1, shadow 2, wits 2; assets: Archer, Hawk, Wayfinder", scene)
        self.assertNotIn("Chaos factor", scene)
        state = json.loads(self.solo("-C", self.game, "state")[1])
        self.assertEqual(sorted(state["progress"]), ["bonds", "the_road_north"])

    def test_the_oracle_answers_with_the_odds_of_the_game(self):
        code, out, err = self.solo("-C", self.game, "ask", "Is the road open?", "--likely", "almost certain")
        self.assertEqual(code, 0, err)
        self.assertIn("odds almost certain", json.loads(out)["summary"])
        code, _, err = self.solo("-C", self.game, "ask", "Is the road open?", "--likely", "very likely")
        self.assertEqual((code, "the odds are one of: small chance, unlikely, 50/50, likely, almost certain" in err), (1, True))

    def test_skills_and_pushing_are_refused_in_words_that_say_what_to_do(self):
        code, _, err = self.solo("-C", self.game, "check", "edge")
        self.assertEqual((code, "solo act <move> --stat <stat>" in err), (1, True))
        code, _, err = self.solo("-C", self.game, "push")
        self.assertEqual((code, "solo burn" in err), (1, True))

    def test_the_gm_may_run_the_new_commands_without_asking(self):
        allowed = json.loads((Path(self.game) / ".claude" / "settings.json").read_text())["permissions"]["allow"]
        for command in ("act", "burn", "track"):
            self.assertIn(f"Bash(solo {command}:*)", allowed)

    def test_a_hero_is_built_for_the_adventure_s_game_without_naming_it(self):
        code, out, err = self.solo("character", "--adventure", str(OATH), "hrafna")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["tracks"]["momentum"]["reset"], 2)

    def test_the_rules_page_of_a_move_carries_its_credit(self):
        _, page, _ = self.act("rule", "face danger", dice=())
        self.assertIn("# Face Danger", page)
        self.assertIn("solo act face_danger", page)
        self.assertIn("created by Shawn Tomkin", page)
        index = self.solo("-C", self.game, "rule")[1]  # the index lists the pages about the game, not every move and asset
        self.assertIn("- Moves (", index)
        self.assertNotIn("- Face Danger", index)


if __name__ == "__main__":
    unittest.main()
