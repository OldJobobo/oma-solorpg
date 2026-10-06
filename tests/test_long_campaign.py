"""A long campaign, as the GM lives it: what the hero did coming back (consequences), the
record read back from the log (the chronology, recall, history, the resume's long memory,
places revisited), the people the GM made up, what word has spread, kinds of foes, where
the story has put people, and a hero's story carried into the next adventure."""

import json
import random

from helpers import BUNDLED, DRAGONBANE, FIXTURES, CampaignTest, Dice
from test_cli import CliCase

from solo import SoloError, campaign, cli, gm

MINE = FIXTURES / "delve"


def go(c, where, **kwargs):
    """A move whose dice don't matter here (the voices on the way in)."""
    return c.move(where, rng=random.Random(len(c.events)), **kwargs)


def say(c, count, text="The wind picks up. What do you do?"):
    for number in range(count):
        c.say(f"{text} ({number})", "gm")
        c.say(f"I wait ({number})", "player")


class Consequences(CampaignTest):
    def test_one_made_on_the_road_comes_due_when_the_hero_reaches_the_hall(self):
        with self.session() as c:
            c.commit({"consequence": {"id": "hrok_talks", "text": "Hrok brags about the bribe", "at": "hall"}})
            go(c, "gate")
            self.assertFalse(c.state["consequences"]["hrok_talks"]["due"])
            self.assertNotIn("## Due now", cli.scene_digest(c))
            go(c, "hall")
        with self.session() as c:
            [due] = [e for e in c.events if e["type"] == "due"]
            self.assertEqual((due["consequence"], due["text"]), ("hrok_talks", "Hrok brags about the bribe"))
            self.assertIn("## Due now", cli.scene_digest(c))
            self.assertIn("- hrok_talks: Hrok brags about the bribe", cli.scene_digest(c))
            c.commit({"consequence": {"id": "hrok_talks", "status": "done"}})
            self.assertNotIn("## Due now", cli.scene_digest(c))
            self.assertEqual(campaign.fold(c.system, c.adventure, c.events), c.state)

    def test_made_in_front_of_someone_it_waits_for_the_next_meeting(self):
        with self.session() as c:
            c.commit({"npc": {"hrok": {"name": "Hrok", "role": "the orc on the gate"}},
                      "consequence": {"id": "owed", "text": "Hrok wants the rest of his silver", "npc": "hrok"}})
            self.assertFalse(campaign.ready(c.adventure, c.state, c.state["consequences"]["owed"]))
            go(c, "gate")
            c.come_due()  # as every command does when it finishes
            self.assertFalse(c.state["consequences"]["owed"]["due"])  # Hrok stayed on the road
            go(c, "road")
            c.come_due()
            self.assertTrue(c.state["consequences"]["owed"]["due"])

    def test_one_that_waits_for_time_comes_due_in_a_rest_from_the_panel(self):
        with self.session() as c:
            c.commit({"consequence": {"id": "rent", "text": "Bram wants paying for the room", "after": {"shift": 1}}})
            c.say("You settle in. What now?", "gm")
        with self.session() as c:
            c.rest("shift", rng=random.Random(1))
        with self.session() as c:
            [due] = [e for e in c.events if e["type"] == "due"]
            self.assertIn("a consequence comes due (rent): Bram wants paying for the room (hidden from the player)", "\n".join(gm.since_gm(c)))

    def test_one_that_waits_on_a_condition_and_a_place_needs_both(self):
        with self.session() as c:
            c.commit({"consequence": {"id": "ambush", "text": "the warband waits at the gate", "at": "gate", "when": "fact.hall.alarm"}})
            go(c, "gate")
            c.come_due()
            self.assertFalse(c.state["consequences"]["ambush"]["due"])
            c.commit({"facts": {"hall.alarm": True}})
            c.come_due()
            self.assertTrue(c.state["consequences"]["ambush"]["due"])  # made on the road, the hero at the gate since

    def test_a_loose_end_without_a_trigger_is_listed_never_announced(self):
        with self.session() as c:
            c.say("The road climbs.", "gm")
            c.commit({"consequence": {"text": "The villagers will want to know what became of the missing shepherd"}})
            go(c, "gate")
            self.assertFalse(any(e["type"] == "due" for e in c.events))
            digest = cli.resume_digest(c)
        self.assertIn("## Loose ends", digest)
        self.assertIn("- the_villagers_will_want: The villagers will want to know what became of the missing shepherd "
                      "(no trigger: bring it in when it fits)", digest)

    def test_the_gm_is_told_whom_it_concerns_and_when_they_are_gone(self):
        with self.session() as c:
            c.say("The road climbs.", "gm")
            c.commit({"consequence": {"id": "grudge", "text": "Grukk's son comes for the hero", "npc": "orc_leader", "at": "final_battle"}})
            c.commit({"npc": {"orc_leader": {"fate": "dead"}}})
            digest = cli.resume_digest(c)
            card = cli.npc_card(c, "orc_leader")
        self.assertIn("- grudge: Grukk's son comes for the hero (at The Ritual Cave); concerns Grukk Red Tusk; "
                      "Grukk Red Tusk is dead: drop it, or let someone else carry it", digest)
        self.assertIn("## Waiting on them (consequences, GM only)\n- grudge:", card)

    def test_the_player_never_sees_them(self):
        with self.session() as c:
            c.commit({"facts": {"gate.guards": 2}, "consequence": {"id": "hrok_talks", "text": "Hrok brags", "at": "hall"}})
            go(c, "gate")
            go(c, "hall")
        state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertNotIn("consequences", state)
        shown = [e["text"] for e in state["log"] if not e.get("hidden")]
        self.assertFalse([t for t in shown if "Hrok" in t or t == "commit"])
        self.assertFalse([s for s in state["story"] if "Hrok" in str(s)])

    def test_what_a_commit_writes_down_for_the_gm_shows_in_its_log(self):
        with self.session() as c:
            event = c.commit({"note": "Ragna bribes the guard", "facts": {"gate.bribed": True},
                              "faction": {"orcs": {"memory": "a stranger bribed the guard"}},
                              "consequence": {"id": "hrok_talks", "text": "Hrok brags", "at": "hall"}})
        self.assertEqual(campaign.gm_line(event), "Ragna bribes the guard [for the GM: facts gate.bribed = true] "
                         "[for the GM: orcs heard: a stranger bribed the guard] [for the GM: consequence hrok_talks open: Hrok brags]")
        self.assertEqual(campaign.describe(event), "Ragna bribes the guard")

    def test_an_id_made_from_the_words_never_takes_over_an_old_one(self):
        with self.session() as c:
            c.commit({"consequence": {"text": "The smith wants paying"}})
            c.commit({"consequence": {"id": "the_smith_wants_paying", "status": "done"}})
            c.commit({"consequence": {"text": "The smith wants paying for the axe"}})
        self.assertEqual(c.state["consequences"]["the_smith_wants_paying_2"]["status"], "open")
        self.assertEqual(c.state["consequences"]["the_smith_wants_paying"]["status"], "done")

    def test_a_bad_one_is_refused_with_what_to_write(self):
        with self.session() as c:
            for payload, message in [
                ({"id": "x"}, "a new one needs its text"),
                ({"text": "a", "at": "tavern"}, "unknown scene tavern"),
                ({"text": "a", "npc": "bram"}, "unknown npc bram"),
                ({"text": "a", "status": "paid"}, "status must be one of open, done, dropped"),
                ({"text": "a", "when": "fact.x ="}, "can't read condition"),
                ({"text": "a", "after": {"week": 1}}, "unknown time unit week"),
                ({"text": "a", "who": "bram"}, "unknown fields who"),
                ("bram comes back", "a consequence is an object"),
            ]:
                with self.subTest(payload=payload), self.assertRaisesRegex(SoloError, message):
                    c.commit({"consequence": payload if isinstance(payload, dict) else [payload]})
            self.assertEqual(c.state["consequences"], {})


class TheRecord(CampaignTest):
    def test_the_resume_says_what_happened_since_the_last_chronicle_entry(self):
        with self.session() as c:
            c.say("The road climbs.", "gm")
            c.commit({"note": "Ragna reads the tracks", "chronicle": "Ragna came to the hill."})
            go(c, "gate")
            c.commit({"note": "Ragna forces the gate bar", "npc": {"hrok": {"name": "Hrok", "role": "the orc on the gate", "memory": "Ragna knocked him down"}},
                      "pc": {"items": {"add": ["an iron key"]}}})
            digest = cli.resume_digest(c)
        chronicle, since = digest.split("## Since your last chronicle entry (from the log, latest last)")
        self.assertIn("- [0d 00:00, The Old Road] Ragna came to the hill.", chronicle)
        self.assertNotIn("Ragna reads the tracks", since)
        self.assertIn("- [0d 00:00] reached The Palisade Gate", since)
        self.assertIn("- [0d 00:00, The Palisade Gate] Ragna forces the gate bar", since)
        self.assertIn("- [0d 00:00, The Palisade Gate] met Hrok, the orc on the gate; remembers: Ragna knocked him down", since)
        self.assertIn("- [0d 00:00, The Palisade Gate] gained an iron key", since)
        self.assertIn("## People the hero knows (the latest met first)\n- hrok: Hrok, the orc on the gate (neutral), at The Palisade Gate; "
                      "remembers: Ragna knocked him down", digest)

    def test_a_campaign_without_a_chronicle_still_has_its_story(self):
        with self.session() as c:
            c.say("The road climbs.", "gm")
            go(c, "gate")
            digest = cli.resume_digest(c)
        self.assertIn("## What has happened so far (from the log, latest last)\n- [0d 00:00] reached The Old Road\n- [0d 00:00] reached The Palisade Gate", digest)
        self.assertIn("`solo recall <words>` searches every word said at this table", digest)

    def test_history_closes_a_chapter_on_each_chronicle_entry(self):
        with self.session() as c:
            c.commit({"note": "first", "chronicle": "Chapter one ends."})
            c.commit({"note": "second"})
            text = cli.history_text(c)
        self.assertIn("## Chapter 1\n- [0d 00:00] Ragna begins The Red Tusk Hall\n- [0d 00:00] reached The Old Road\n"
                      "- [0d 00:00, The Old Road] first\n\nChronicle: Chapter one ends.", text)
        self.assertIn("## Chapter 2 (since the last chronicle entry)\n- [0d 00:00, The Old Road] second", text)

    def test_a_death_and_a_fight_are_in_the_record(self):
        with self.session() as c:
            c.fight(["priest"], rng=Dice(1, 2))
            c.end_fight()
            c.commit({"pc": {"hp": 0}})
            for _ in range(3):
                c.death_roll(rng=Dice(20))
                if c.state["pc"]["dead"]:
                    break
            texts = [m["text"] for m in campaign.moments(c.chronology())]
        self.assertIn("a fight: The hooded priest", texts)
        self.assertIn("the fight ends; still standing: The hooded priest", texts)
        self.assertIn("Ragna died", texts)

    def test_the_gm_is_reminded_to_write_a_chronicle_entry(self):
        with self.session() as c:
            say(c, campaign.CHRONICLE_EVERY - 1)
            self.assertIsNone(cli._chronicle_nudge(c))
            say(c, 1)
            self.assertIn("12 of your messages since the last chronicle entry", cli.scene_digest(c))
            c.commit({"chronicle": "So far."})
            self.assertIsNone(cli._chronicle_nudge(c))


class Recall(CampaignTest):
    def test_it_finds_what_was_said_written_and_answered(self):
        with self.session() as c:
            c.say("A one-eyed smith called Bram runs the forge at Kjölvik.", "gm")
            c.say("I ask Bram about the priest.", "player")
            c.commit({"facts": {"road.smithy": "Bram's forge, cold since the orcs came"},
                      "npc": {"bram": {"name": "Bram", "role": "a one-eyed smith", "memory": "Ragna asked about the priest"}}})
            c.ask("Does Bram know where the priest sleeps?", rng=Dice(4))
            found = campaign.recall(c.chronology(), c.state, "bram")
            labels = [f["label"] for f in found]
            self.assertEqual(labels[0], "the oracle")  # newest first
            self.assertIn("you said", labels)
            self.assertIn("the player said", labels)
            self.assertIn("fact", labels)
            self.assertIn("Bram remembers", labels)
            self.assertIn("Bram, role", labels)
            # Every word, accents ignored: only what holds both.
            [hit] = campaign.recall(c.chronology(), c.state, "smith kjolvik")
            self.assertEqual(hit["label"], "you said")
            self.assertIn("Kjölvik", hit["text"])

    def test_it_says_so_when_nothing_mentions_it(self):
        with self.session() as c:
            text = cli.recall_text(c, "dragon")
        self.assertIn("Nothing at this table mentions 'dragon'", text)

    def test_a_long_message_is_cut_around_the_match(self):
        with self.session() as c:
            c.say("The rain. " * 40 + "Then the bell of Holmstad rings. " + "The mud. " * 40, "gm")
            [hit] = campaign.recall(c.chronology(), c.state, "holmstad")
        self.assertTrue(hit["text"].startswith("...") and hit["text"].endswith("..."))
        self.assertIn("Holmstad", hit["text"])
        self.assertLess(len(hit["text"]), 300)


class Places(CampaignTest):
    def test_a_place_the_hero_comes_back_to_says_what_they_left(self):
        with self.session() as c:
            go(c, "gate")
            c.commit({"note": "Ragna forces the gate bar", "facts": {"gate.bar_broken": True}})
            go(c, "hall")
            c.rest("shift", rng=random.Random(1))
            go(c, "gate")
            digest = cli.scene_digest(c)
        self.assertIn("## Back here (the hero was here once before, and left 6 hours ago)\nWhat happened here then, latest last:\n"
                      "- [0d 00:00] Ragna forces the gate bar", digest)
        self.assertIn("- gate.bar_broken: true", digest)

    def test_a_first_visit_has_no_back_here(self):
        with self.session() as c:
            go(c, "gate")
            self.assertNotIn("## Back here", cli.scene_digest(c))

    def test_the_facts_about_this_place_survive_however_many_come_after(self):
        with self.session() as c:
            go(c, "gate")
            c.commit({"facts": {"gate.bar_broken": True}})
            c.commit({"facts": {f"elsewhere.fact_{n}": n for n in range(60)}})
            digest = cli.scene_digest(c)
        self.assertIn("- gate.bar_broken: true", digest)
        self.assertIn("- elsewhere.fact_59: 59", digest)
        self.assertNotIn("- elsewhere.fact_0: 0", digest)
        self.assertIn("- and 21 more, settled earlier elsewhere: solo recall <word> finds them", digest)

    def test_someone_the_story_moved_is_found_where_it_put_them(self):
        with self.session() as c:
            c.commit({"npc": {"orc_leader": {"location": "gate"}}})
            go(c, "gate")
            self.assertIn("- orc_leader: Grukk Red Tusk", cli.scene_digest(c))
            go(c, "hall")
            digest = cli.scene_digest(c)
            self.assertNotIn("- orc_leader:", digest)
            self.assertIn("Not here any more, though the text names them (the story has put them elsewhere): Grukk Red Tusk (now at The Palisade Gate)", digest)
            c.commit({"npc": {"orc_leader": {"location": None}}})
            self.assertIn("- orc_leader: Grukk Red Tusk", cli.scene_digest(c))


class People(CampaignTest):
    def test_someone_the_gm_made_up_stays_the_same_person(self):
        with self.session() as c:
            c.commit({"npc": {"bram": {"name": "Bram", "role": "a one-eyed smith", "description": "soot to the elbows",
                                       "voice": "slow, never finishes a sentence", "wants": "his daughter back", "fears": "fire"}}})
            card = cli.npc_card(c, "bram")
            [entry] = [e for e in campaign.codex(c.adventure, c.state) if e["id"] == "bram"]
            self.assertEqual((entry["role"], entry["known"], entry["unknown"]), ("a one-eyed smith", {}, 2))
            c.commit({"learn": ["bram.wants"]})
            [entry] = [e for e in campaign.codex(c.adventure, c.state) if e["id"] == "bram"]
        self.assertIn("a one-eyed smith\n", card)
        self.assertIn("Voice: slow, never finishes a sentence", card)
        self.assertIn("(You made up role, description, voice, wants, fears in play: keep to it.)", card)
        self.assertEqual((entry["known"], entry["unknown"]), ({"wants": "his daughter back"}, 1))

    def test_the_adventures_own_people_keep_their_book_profile(self):
        with self.session() as c, self.assertRaisesRegex(SoloError, "the adventure already gives their wants; what changed about them goes in a memory"):
            c.commit({"npc": {"orc_leader": {"wants": "peace"}}})

    def test_word_spreads_to_a_faction(self):
        with self.session() as c:
            c.say("The road climbs.", "gm")
            c.commit({"faction": {"orcs": {"memory": "a dwarf is asking about the priest"}}})
            self.assertEqual(c.state["factions"]["orcs"]["standing"], -1)  # memory alone moves nothing
            go(c, "gate")
            go(c, "hall")
            scene = cli.scene_digest(c)
            digest = cli.resume_digest(c)
            card = cli.npc_card(c, "orc_leader")
        self.assertIn("their people have heard: a dwarf is asking about the priest", scene)
        self.assertIn("## Factions (where the hero stands, and what word has reached them)\n- orcs: Red Tusk orcs (unfriendly); "
                      "they've heard: a dwarf is asking about the priest", digest)
        self.assertIn("Faction: Red Tusk orcs (standing unfriendly); they've heard: a dwarf is asking about the priest", card)

    def test_the_people_line_keeps_more_than_the_last_memory(self):
        with self.session() as c:
            for memory in ("Ragna spared his son", "Ragna shared bread", "Ragna laughed at his joke", "Ragna nodded"):
                c.commit({"npc": {"orc_leader": {"memory": memory}}})
            go(c, "gate")
            go(c, "hall")
            self.assertIn("remembers: Ragna shared bread / Ragna laughed at his joke / Ragna nodded", cli.scene_digest(c))


class Kinds(CampaignTest):
    adventure = MINE
    character = BUNDLED / "characters" / "ragna.toml"

    def test_a_kind_of_foe_has_no_fate_and_never_runs_out(self):
        with self.session() as c:
            with self.assertRaisesRegex(SoloError, "tunnel_goblin is a kind of foe .* say what became of these ones with a fact"):
                c.commit({"npc": {"tunnel_goblin": {"fate": "dead"}}})
            c.fight(["tunnel_goblin", "tunnel_goblin"], rng=random.Random(1))
            c.end_fight()
            c.fight(["tunnel_goblin"], rng=random.Random(2))  # another band, another day
            self.assertIn("A kind of foe the hero meets again and again", cli.npc_card(c, "tunnel_goblin"))

    def test_the_freed_miner_is_found_again_at_her_forge(self):
        """The deep workings' commit, as the pack writes it, sends Brenna home to be found again."""
        text = (MINE / "scenes" / "deep.md").read_text(encoding="utf-8")
        commit = json.loads(text.split("Freed: commit `")[1].split("`")[0])
        with self.session() as c:
            c.commit(commit)
            self.assertEqual(c.state["factions"]["miners"]["memories"], ["a stranger freed Brenna from the goblins"])
            go(c, "smithy", force="testing")
            self.assertIn("brenna", campaign.people_here(c.adventure, c.state))


class SafePlaces(CampaignTest):
    adventure = MINE
    character = BUNDLED / "characters" / "ragna.toml"

    def test_a_threat_waits_while_the_hero_is_somewhere_safe(self):
        with self.session() as c:
            go(c, "adit")
            go(c, "deep")
            c.threat("A trio of goblin scouts spring an ambush", threat_id="goblin_scouts")
            go(c, "adit")
            go(c, "village")  # out of the mine
            c.rest("shift", rng=random.Random(1))
            self.assertEqual(c.state["clocks"]["goblin_scouts"]["value"], 1)
            self.assertIn("the hero is somewhere safe, so time here doesn't bring it closer", cli.scene_digest(c))
            go(c, "adit")
            c.commit({"time": {"stretch": 5}})
            self.assertTrue(any(e["type"] == "threat" and e["action"] == "triggered" for e in c.events))
            [triggered] = [e for e in c.events if e["type"] == "threat" and e["action"] == "triggered"]
            self.assertIn("[for the GM: it happens now, before anything else: run it in this reply", campaign.gm_line(triggered))


class Shapes(CampaignTest):
    """What GMs wrote in a real run: read when the meaning is plain, refused with the right
    shape when it isn't."""

    def test_plain_meanings_are_read(self):
        with self.session() as c:
            event = c.commit({"npcs": {"bram": {"name": "Bram", "wants": "his daughter back"}}, "learn": {"bram": "wants"},
                              "promises": {"word_to_bram": {"npc": "bram", "text": "bring word of his daughter"}}})
            self.assertEqual(event["warnings"], ["read npcs as npc", "read promises as promise"])
            self.assertEqual(c.state["learned"], ["bram.wants"])
            self.assertEqual(c.state["promises"]["word_to_bram"]["terms"], "bring word of his daughter")
            c.commit({"consequence": {"text": "Bram asks again", "npc": "bram"}})
            c.commit({"consequence": {"bram_asks_again": {"status": "done"}}})
            self.assertEqual(c.state["consequences"]["bram_asks_again"]["status"], "done")
            c.commit({"promise": {"npc": "bram", "terms": "pay for the room"}})
            self.assertIn("pay_for_the_room", c.state["promises"])

    def test_facts_under_the_scene_a_list_of_them_and_time_in_words_are_read(self):
        with self.session() as c:
            scene = c.state["scene"]
            event = c.commit({"scene": {"facts": {"floor_searched": True, "hall.alarm": False}}, "time": "10 minutes"})
            self.assertEqual(event["changes"]["facts"], {f"{scene}.floor_searched": True, "hall.alarm": False})
            self.assertEqual(event["changes"]["time"], 600)
            self.assertEqual(event["warnings"], [f"read scene as facts under {scene}", 'read time "10 minutes" as {"minutes": 10}'])
            # A sentence with no key is filed under the scene by its first words; the same sentence is the same fact.
            c.commit({"scene": {"fact": "A wounded man lies on the trail"}})
            event = c.commit({"facts": ["A wounded man lies on the trail", "A wounded man lies dead now", "gate.open"]})
            self.assertEqual(event["changes"]["facts"], {f"{scene}.a_wounded_man_lies": "A wounded man lies on the trail",
                                                         f"{scene}.a_wounded_man_lies_2": "A wounded man lies dead now", "gate.open": True})
            self.assertEqual(c.commit({"facts": "gate.open"})["changes"]["facts"], {"gate.open": True})
            event = c.commit({"facts": {"hall": ["Osk tells the old tale", "throne"], "hall.alarm": True}})
            self.assertEqual(event["changes"]["facts"], {"hall.osk_tells_the_old": "Osk tells the old tale", "hall.throne": True, "hall.alarm": True})
            self.assertIn("read facts as", event["warnings"][0])
            self.assertNotIn("warnings", c.commit({"facts": {"hall.alarm": False}}))
            self.assertEqual(c.commit({"facts": {"scene": ["The floor was swept"]}})["changes"]["facts"], {f"{scene}.the_floor_was_swept": "The floor was swept"})
            for words, seconds in (("a stretch", 900), ("2 hours and 30 minutes", 9000), ("1.5 shifts", 32400)):
                with self.subTest(words=words):
                    self.assertEqual(c.commit({"time": words})["changes"]["time"], seconds)

    def test_the_rest_is_refused_with_what_to_write(self):
        with self.session() as c:
            for payload, message in [
                ({"memory": {"orc_leader": "spared"}}, 'a memory belongs to someone: {"npc": {"<id>": {"memory"'),
                ({"scene": "gate"}, "a commit doesn't take the hero anywhere: solo move gate"),
                ({"npc": {"orc_leader": {"at": "gate"}}}, "where someone is, is location"),
                ({"consequence": {"text": "Bram asks", "when": "Ragna finds his daughter"}}, "`when` is a condition the engine can check"),
            ]:
                with self.subTest(payload=payload), self.assertRaisesRegex(SoloError, message):
                    c.commit(payload)


class TheHerosStory(CampaignTest):
    def test_it_goes_on_to_the_next_adventure(self):
        with self.session() as c:
            c.commit({"npc": {"orc_leader": {"attitude": "+1", "memory": "Ragna spared him"}},
                      "facts": {"hero.oath": "never to leave a prisoner behind", "hall.alarm": True},
                      "promise": {"id": "warband", "npc": "orc_leader", "terms": "the warband answers her call"},
                      "consequence": {"text": "Grukk sends word of the priest's master"},
                      "chronicle": "Ragna spared Grukk.", "end": "The orcs keep their hill."})
            go(c, "gate")
            go(c, "hall")
        sheet = campaign.hero(self.root)
        self.assertEqual(sheet["facts"], {"hero.oath": "never to leave a prisoner behind"})
        [record] = sheet["past"]
        self.assertEqual(record["title"], "The Red Tusk Hall")
        self.assertEqual(record["ended"], "The orcs keep their hill.")
        self.assertEqual(record["chronicle"], ["Ragna spared Grukk."])
        self.assertEqual(record["loose_ends"], ["the warband answers her call (a promise, Grukk Red Tusk)", "Grukk sends word of the priest's master"])
        self.assertEqual(record["people"], ["Grukk Red Tusk (neutral): Ragna spared him"])
        later = campaign.create(self.tmp / "later", DRAGONBANE, MINE, sheet)
        with campaign.session(later) as c:
            self.assertEqual(c.state["facts"], {"hero.oath": "never to leave a prisoner behind"})
            digest = cli.resume_digest(c)
            self.assertIn("Their story (hero.* facts): oath: never to leave a prisoner behind", cli.scene_digest(c))
        # Twice over: the past goes on growing.
        self.assertEqual([r["title"] for r in campaign.hero(later)["past"]], ["The Red Tusk Hall", "The Old Mine"])
        self.assertIn("## Before this adventure (the hero's earlier stories; the people in them may turn up again)\n"
                      "- The Red Tusk Hall: The orcs keep their hill.\n  - Ragna spared Grukk.", digest)
        self.assertIn("## The hero, as the player made them (hero.* facts)\n- oath: never to leave a prisoner behind", digest)
        with campaign.session(later) as c:
            found = campaign.recall(c.chronology(), c.state, "grukk spared")
        self.assertEqual([f["label"] for f in found], ["before this adventure, chronicle", "before this adventure, people"])


class Commands(CliCase):
    def run_json(self, *args):
        code, out, err = self.solo("-C", self.game, *args)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_the_gm_hears_of_it_the_moment_it_comes_due(self):
        self.new_game()
        self.run_json("commit", json.dumps({"consequence": {"id": "hrok_talks", "text": "Hrok brags about the bribe", "at": "gate"}}))
        report = self.run_json("move", "gate")
        self.assertIn("a consequence comes due (hrok_talks): Hrok brags about the bribe", report["then"])
        code, out, _ = self.solo("-C", self.game, "recall", "bribe")
        self.assertIn("# Recall: bribe", out)
        self.assertIn("consequence hrok_talks: Hrok brags about the bribe", out)
        code, out, _ = self.solo("-C", self.game, "history")
        self.assertIn("## Chapter 1\n- [0d 00:00] Ragna begins The Red Tusk Hall", out)
        self.assertIn("a consequence came due: Hrok brags about the bribe", out)

    def test_a_commit_asks_for_a_chronicle_entry_when_it_is_time(self):
        self.new_game()
        with campaign.session(self.game) as c:
            say(c, campaign.CHRONICLE_EVERY)
        self.assertIn("since the last chronicle entry", self.run_json("commit", '{"note": "a pause"}')["chronicle"])
        self.assertNotIn("chronicle", self.run_json("commit", '{"chronicle": "Ragna reached the gate."}'))
