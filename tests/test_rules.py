"""Stakes, fights, the oracle's surprises, advancement and the player's table settings."""

import copy
import shutil

from helpers import CampaignTest, Dice, LikelihoodTest

from solo import SoloError, campaign, cli, packs


class DyingTest(CampaignTest):
    def test_zero_hp_starts_dying_and_blocks_other_actions(self):
        with self.session() as c:
            c.commit({"pc": {"hp": "-14"}})
            self.assertEqual(c.state["pc"]["dying"], {"successes": 0, "failures": 0})
            with self.assertRaisesRegex(SoloError, "dying"):
                c.check("swords")
            with self.assertRaisesRegex(SoloError, "dying"):
                c.rest("round")

    def test_three_failures_kill_and_harm_while_dying_is_a_failure(self):
        with self.session() as c:
            c.commit({"pc": {"hp": "-14"}})
            c.death_roll(rng=Dice(18))  # CON 14: a failure
            harm = c.commit({"pc": {"hp": "-2"}})
            self.assertEqual(harm["changes"]["pc"]["death_failures"], 1)
            last = c.death_roll(rng=Dice(15))
            self.assertEqual(last["result"], "dies")
            self.assertTrue(c.state["pc"]["dead"])
            self.assertEqual(c.state["ended"]["text"], "Ragna died.")
            with self.assertRaisesRegex(SoloError, "is dead"):
                c.death_roll()
            with self.assertRaisesRegex(SoloError, "is dead"):
                c.commit({"pc": {"hp": "+3"}})
            c.commit({"pc": {"hp": "+3"}, "override": "the priest's pool gives her back"})
            self.assertFalse(c.state["pc"]["dead"])
            self.assertIsNone(c.state["ended"])

    def test_a_dragon_counts_twice_and_a_rally_restores_hp(self):
        with self.session() as c:
            c.commit({"pc": {"hp": "-14"}})
            c.death_roll(rng=Dice(5))
            rally = c.death_roll(rng=Dice(1, 4))  # a Dragon: two more successes, then 1d6 HP
            pc = c.state["pc"]
        self.assertEqual(rally["result"], "rallies")
        self.assertEqual((pc["tracks"]["hp"]["value"], pc["dying"]), (4, None))

    def test_one_death_roll_a_round_in_a_fight(self):
        with self.session() as c:
            c.fight(["priest"], rng=Dice(1, 2))
            c.commit({"pc": {"hp": "-14"}})
            c.death_roll(rng=Dice(5))
            with self.assertRaisesRegex(SoloError, "already made a death roll this round"):
                c.death_roll(rng=Dice(5))
            c.next_round(rng=Dice(1, 2))
            c.death_roll(rng=Dice(5))
            self.assertEqual(c.state["pc"]["dying"]["successes"], 2)

    def test_harm_from_elsewhere_leaves_the_blow_that_is_coming(self):
        with self.session() as c:
            c.fight(["orc_leader"], rng=Dice(1, 2))
            c.enemy("orc_leader", rng=Dice(5))
            c.wound("hero", "1d4", why="a stone falls from the roof", rng=Dice(2))
            self.assertEqual(c.state["combat"]["incoming"]["name"], "Grukk Red Tusk")
            c.defend("take", rng=Dice(3, 3))
            self.assertIsNone(c.state["combat"]["incoming"])
            self.assertEqual(c.state["pc"]["tracks"]["hp"]["value"], 14 - 2 - 6)

    def test_a_death_in_a_fight_ends_the_fight(self):
        with self.session() as c:
            c.fight(["priest"], rng=Dice(1, 2))
            c.commit({"pc": {"hp": "-14"}})
            c.death_roll(rng=Dice(20, 20))  # a Demon: two failures
            c.next_round(rng=Dice(1, 2))
            c.death_roll(rng=Dice(20))
            self.assertTrue(c.state["pc"]["dead"])
            self.assertIsNone(c.state["combat"])
            self.assertEqual(c.events[-1]["type"], "fight_end")
            self.assertEqual(c.events[-1]["standing"], ["The hooded priest"])
            # Whoever takes up the story doesn't walk into the blow that killed Ragna.
            c.take_over("human thief", seed=2)
            with self.assertRaisesRegex(SoloError, "no fight on"):
                c.enemy("priest")

    def test_healing_stops_dying(self):
        with self.session() as c:
            c.commit({"pc": {"hp": "-14"}})
            c.commit({"pc": {"hp": "+2"}})
            self.assertIsNone(c.state["pc"]["dying"])


class FightTest(CampaignTest):
    def test_initiative_cards_are_dealt_without_repeats(self):
        with self.session() as c:
            event = c.fight(["priest", "cultist", "cultist"], rng=Dice(3, 1, 8, 2))
            foes = c.state["combat"]["foes"]
        self.assertEqual([f["id"] for f in event["order"]], ["priest", "pc", "cultist_2", "cultist"])
        self.assertEqual([f["card"] for f in event["order"]], [1, 3, 4, 10])
        self.assertEqual(foes["cultist_2"]["name"], "Cultist 2")

    def test_a_second_foe_of_a_kind_never_takes_another_npcs_id(self):
        # The second cultist was cultist_2, and an adventure's own cultist_2 fighting too took its place.
        adventure = self.tmp / "red-tusk"
        shutil.copytree(self.adventure, adventure)
        (adventure / "npcs" / "cultist_2.toml").write_text('name = "Brother Vey"\n[stats]\nhp = 12\n', encoding="utf-8")
        with campaign.session(campaign.create(self.tmp / "vey", self.system, adventure, self.character)) as c:
            c.fight(["cultist", "cultist", "cultist_2"], rng=Dice(3, 1, 8, 2))
            foes = {fid: (f["npc"], f["name"]) for fid, f in c.state["combat"]["foes"].items()}
            self.assertEqual(foes, {"cultist": ("cultist", "Cultist"), "cultist_3": ("cultist", "Cultist 3"), "cultist_2": ("cultist_2", "Brother Vey")})
            c.end_fight()
            c.fight(["cultist", "cultist"], rng=Dice(3, 1, 8))
            c.join(["cultist_2"], rng=Dice(1))
            self.assertEqual(sorted(c.state["combat"]["foes"]), ["cultist", "cultist_2", "cultist_3"])

    def test_an_attack_deals_weapon_damage_and_bonus_through_armor(self):
        with self.session() as c:
            c.fight(["priest"], rng=Dice(1, 1))
            c.attack("priest", rng=Dice(10, 6, 5, 3))  # Swords 14; broadsword 2d6 + STR 15's 1d4
            [damage] = [e for e in c.events if e["type"] == "damage"]
            self.assertEqual((damage["expr"], damage["dealt"], damage["hp"]), ("2d6+1d4", 13, 1))
            with self.assertRaisesRegex(SoloError, "already attacked this round"):
                c.attack("priest", rng=Dice(1))
            c.next_round(rng=Dice(1, 1))
            dragon = c.attack(rng=Dice(1, 6, 6, 6, 6, 4))  # a Dragon rolls the weapon dice twice
            damage, end = c.events[-2:]
            self.assertEqual((damage["expr"], damage["down"]), ("2d6+2d6+1d4", True))
            self.assertEqual((end["type"], c.state["combat"]), ("fight_end", None))  # nobody left standing
            self.assertIn("swords", c.state["pc"]["marks"])
            with self.assertRaisesRegex(SoloError, "no fight on"):
                c.attack("priest")
        self.assertTrue(dragon["outcome"]["dragon"])

    def test_a_weapon_by_a_word_of_its_name_but_never_a_guess(self):
        with self.session() as c:
            c.fight(["priest"], rng=Dice(1, 1))
            self.assertEqual(c.attack("priest", "broad", rng=Dice(18))["attack"]["weapon"], "broadsword")
            c.commit({"pc": {"items": {"add": ["Short sword"]}}})
            c.next_round(rng=Dice(1, 1))
            with self.assertRaisesRegex(SoloError, "'sword' could be short_sword, broadsword: name the weapon"):
                c.attack("priest", "sword")
            self.assertEqual(c.attack("priest", "Short sword", rng=Dice(18))["attack"]["weapon"], "short_sword")

    def test_a_pushed_attack_that_hits_deals_damage(self):
        with self.session() as c:
            c.fight(["cultist"], rng=Dice(1, 1))
            c.attack(rng=Dice(18))
            c.push("angry", rng=Dice(2, 3, 3, 2))
            self.assertEqual([e["type"] for e in c.events[-2:]], ["damage", "fight_end"])
            self.assertTrue(c.events[-2]["down"])

    def test_foes_attack_and_the_hero_evades_parries_or_takes_it(self):
        with self.session() as c:
            c.commit({"pc": {"items": {"add": ["Chainmail"]}}})
            c.fight(["priest"], rng=Dice(1, 1))
            c.enemy(rng=Dice(5))  # Knives 13: a hit
            self.assertEqual(c.state["combat"]["incoming"]["damage"], "1d8")
            with self.assertRaisesRegex(SoloError, "still waiting"):
                c.enemy()
            with self.assertRaisesRegex(SoloError, "answer the hit"):
                c.attack()
            c.defend("evade", rng=Dice(4))
            self.assertIsNone(c.state["combat"]["incoming"])
            with self.assertRaisesRegex(SoloError, "can't be pushed"):
                c.push("angry")
            c.enemy(rng=Dice(2))
            c.defend("parry", rng=Dice(19, 7))  # a failed parry takes the hit: 7 - chainmail 3
            self.assertEqual(c.state["pc"]["tracks"]["hp"]["value"], 10)
            miss = c.enemy(rng=Dice(20))
            self.assertIsNone(miss.get("incoming"))
            with self.assertRaisesRegex(SoloError, "nothing is coming"):
                c.defend("take")

    def test_monster_attacks_come_from_a_table_and_some_cant_be_dodged(self):
        with self.session() as c:
            c.fight(["tentacle"], rng=Dice(1, 1))
            c.enemy(rng=Dice(5))
            with self.assertRaisesRegex(SoloError, "can't be dodged"):
                c.defend("evade")
            harm = c.defend("take", rng=Dice(8, 8))
            self.assertEqual(harm["dealt"], 16)
            self.assertEqual(c.state["pc"]["dying"], {"successes": 0, "failures": 0})

    def test_foes_join_rounds_redeal_and_fights_end(self):
        with self.session() as c:
            c.fight(["priest"], rng=Dice(1, 1))
            join = c.join(["tentacle"], rng=Dice(1))
            self.assertEqual([f["card"] for f in join["order"]], [1, 2, 3])
            c.next_round(rng=Dice(1, 1, 1))
            self.assertEqual(c.state["combat"]["round"], 2)
            with self.assertRaisesRegex(SoloError, "fight"):
                c.rest("round")
            c.end_fight()
            self.assertIsNone(c.state["combat"])
            self.assertTrue(c.state["npcs"]["tentacle"]["met"])

    def test_foes_need_stats(self):
        with self.session() as c, self.assertRaisesRegex(SoloError, "unknown npc"):
            c.fight(["wolf"])


class OracleTest(LikelihoodTest):
    def test_doubles_within_the_chaos_factor_set_off_a_random_event(self):
        with self.session() as c:
            asked = c.ask("Is the gate open?", likely="even", rng=Dice(33, 50, 1, 2))
            quiet = c.ask("Is it raining?", likely="even", rng=Dice(44))  # 4 is over chaos 3
        self.assertEqual(asked["answer"], "yes")
        self.assertEqual(asked["random_event"]["focus"], "thread_back")
        self.assertEqual(asked["random_event"]["about"], "the hero's current goal")
        self.assertEqual(asked["random_event"]["meaning"], ["abandon", "a secret"])
        self.assertNotIn("random_event", quiet)

    def test_an_npc_event_with_nobody_known_brings_someone_new(self):
        with self.session() as c:
            asked = c.ask("Anyone about?", likely="even", rng=Dice(11, 10, 1, 1))
        self.assertEqual(asked["random_event"]["focus"], "new_npc")

    def test_scene_checks_alter_or_interrupt_scenes(self):
        with self.session() as c:
            # Each scene here has one voice, rolled after the scene check: 15 keeps it silent.
            self.assertEqual(c.move("gate", rng=Dice(9, 15))["scene_check"]["result"], "expected")
            self.assertEqual(c.move("hall", rng=Dice(3, 15))["scene_check"]["result"], "altered")
            self.assertIn("## Scene check: altered", cli.scene_digest(c))
            interrupted = c.move("cellar", rng=Dice(2, 20, 1, 1, 15))["scene_check"]
            self.assertEqual(interrupted["event"]["about"], "Grukk Red Tusk")
            self.assertIn("Someone the hero knows acts on their own wants (Grukk Red Tusk): abandon / a debt", cli.scene_digest(c))
            forced = c.move("final_battle", force="the tunnel")
        self.assertNotIn("scene_check", forced)

    def test_chaos_moves_by_commit_within_one_to_nine(self):
        with self.session() as c:
            c.commit({"chaos": "+9"})
            self.assertEqual(c.state["chaos"], 9)
            c.commit({"chaos": 0})
            self.assertEqual(c.state["chaos"], 1)

    def test_meaning_gives_an_action_and_a_subject(self):
        with self.session() as c:
            event = c.meaning("What does the priest want?", rng=Dice(50, 50))
        self.assertEqual(event["words"], ["warn", "the future"])
        self.assertEqual(campaign.describe(event), 'meaning of "What does the priest want?": warn / the future')


class AdvancementTest(CampaignTest):
    def test_dragons_and_demons_mark_skills_and_advance_rolls_them(self):
        with self.session() as c:
            c.check("sneaking", rng=Dice(1, 4))  # outside a fight, a Dragon rolls its effect too
            self.assertEqual(c.events[-1]["text"], "You spot a way forward nobody else did")
            c.check("str", rng=Dice(1, 2))  # attributes aren't marked
            c.check("awareness", rng=Dice(20, 1, 3))  # the Demon's effect, and it ticks the ritual: one omen
            self.assertIn("Something you carry breaks", [e.get("text") for e in c.events])
            c.mark("swords", reason="defeated a dangerous foe")
            with self.assertRaisesRegex(SoloError, "already marked"):
                c.mark("swords")
            with self.assertRaisesRegex(SoloError, "attribute"):
                c.mark("str")
            self.assertEqual(c.state["pc"]["marks"], ["sneaking", "awareness", "swords"])
            c.advance(rng=Dice(15, 20, 2))
            skills = c.state["pc"]["skills"]
            with self.assertRaisesRegex(SoloError, "no skills are marked"):
                c.advance()
        self.assertEqual([skills[k]["value"] for k in ("sneaking", "awareness", "swords")], [5, 11, 14])

    def test_the_dead_learn_nothing(self):
        with self.session() as c:
            c.mark("swords")
            c.commit({"pc": {"hp": "-14"}})
            c.death_roll(rng=Dice(20, 20))  # a Demon: two failures
            c.death_roll(rng=Dice(20))
            self.assertTrue(c.state["pc"]["dead"])
            for learn in (lambda: c.mark("sneaking"), c.advance):
                with self.assertRaisesRegex(SoloError, "is dead"):
                    learn()


class PrefsTest(CampaignTest):
    def test_table_settings_are_kept_and_shown_to_the_gm(self):
        with self.session() as c:
            c.set_prefs(tone="grim", lines=["harm to children"], veils=["torture"])
            c.set_prefs(lines=["harm to children", "spiders"])
            self.assertEqual(c.state["prefs"], {"tone": "grim", "lines": ["harm to children", "spiders"], "veils": ["torture"]})
            digest = cli.resume_digest(c)
            self.assertIn("- Line (never in the story): spiders", digest)
            self.assertIn("- Tone: grim", cli.scene_digest(c))
            c.set_prefs(clear=True)
            self.assertEqual(c.state["prefs"], {"tone": "", "lines": [], "veils": []})

    def test_the_gm_cant_change_them_without_asking(self):
        self.assertNotIn("prefs", cli.GM_COMMANDS)
        # The X-card and the budget are the player's too: a GM that could cut its own words or raise its own limit is no check.
        for command in ("strike", "gm", "report"):
            self.assertNotIn(command, cli.GM_COMMANDS)


class PackValidationTest(CampaignTest):
    def test_combat_data_is_checked(self):
        system = packs.load_system(self.system)
        adventure = packs.load_adventure(self.adventure)
        self.assertEqual(packs.validate(system, adventure), [])
        system = copy.deepcopy(system)
        system["weapons"]["club"] = {"skill": "clubs", "damage": "1d6"}
        adventure["npcs"]["priest"]["attacks"] = "nowhere"
        problems = packs.validate(system, adventure)
        self.assertIn("system: weapon club uses unknown skill clubs", problems)
        self.assertIn("npc priest: attacks names unknown table nowhere", problems)

    def test_clock_stop_triggers_are_checked(self):
        system, adventure = packs.load_system(self.system), packs.load_adventure(self.adventure)
        adventure["clocks"]["dark_ritual"]["stop"] = ["npc:nobody:dead"]
        self.assertIn("clock dark_ritual: npc:nobody:dead should be npc:<id>:<alive|dead|fled|captured|gone>", packs.validate(system, adventure))


class AllyTest(CampaignTest):
    def test_an_ally_attacks_a_foe_once_a_round(self):
        with self.session() as c:
            c.fight(["cultist", "cultist"], rng=Dice(1, 2, 3))
            hit = c.ally("orc_leader", "cultist", rng=Dice(5, 4, 3))  # Axes 14; battleaxe 2d8
            self.assertEqual((hit["dealt"], hit["hp"], hit["down"]), (7, 1, False))
            with self.assertRaisesRegex(SoloError, "already attacked this round"):
                c.ally("orc_leader", "cultist", rng=Dice(5))
            c.next_round(rng=Dice(1, 2, 3))
            c.ally("orc_leader", "cultist", rng=Dice(2, 8, 8))
            foes = c.state["combat"]["foes"]
            self.assertTrue(foes["cultist"]["down"])
            self.assertEqual(c.state["combat"]["last"]["from"], "pc")  # drawn from the hero's side
            c.next_round(rng=Dice(1, 2))
            miss = c.ally("orc_leader", "cultist_2", rng=Dice(19))
            self.assertNotIn("dealt", miss)
            self.assertEqual(foes["cultist_2"]["hp"], 8)
            self.assertEqual(c.state["story"][-1]["kind"], "hit")

    def test_who_can_fight_beside_the_hero(self):
        with self.session() as c:
            c.fight(["orc_leader"], rng=Dice(1, 2))
            with self.assertRaisesRegex(SoloError, "fighting against the hero"):
                c.ally("orc_leader")
            with self.assertRaisesRegex(SoloError, "no attack skill"):
                c.ally("tentacle")

    def test_the_fight_says_who_is_still_to_act(self):
        with self.session() as c:
            c.fight(["cultist"], rng=Dice(1, 2))  # Ragna draws 1, the cultist 2
            self.assertEqual(c.to_act(), ["Ragna", "Cultist"])
            c.attack(rng=Dice(18))
            self.assertEqual(c.to_act(), ["Cultist"])
            c.enemy(rng=Dice(15))
            self.assertEqual(c.to_act(), [])
            self.assertIn("everyone has acted", "\n".join(cli._now(c)))
            c.next_round(rng=Dice(2, 1))
            self.assertEqual(c.to_act(), ["Cultist", "Ragna"])
