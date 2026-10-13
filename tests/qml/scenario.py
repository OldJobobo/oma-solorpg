"""Real engine state for rendering the Book: The Red Tusk Hall, played to a fight, and The Bell
Under the Hill, played to a vow, a road and a roll momentum could still save."""

import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent.parent), str(HERE.parent)]
os.environ.setdefault("XDG_STATE_HOME", tempfile.mkdtemp())

from helpers import DRAGONBANE, HRAFNA, IRONSWORN, RAGNA, RED_TUSK, ROOT, Dice, install_rules  # noqa: E402, F401
from solo import campaign  # noqa: E402


def play(out):
    root = campaign.create(Path(tempfile.mkdtemp()) / "game", DRAGONBANE, RED_TUSK, RAGNA)
    with campaign.session(root) as c:
        c.say("Rain has turned the old road to mud. Ahead, smoke rises from behind a palisade of sharpened logs, "
              "and the wind carries drums and laughter down the hill.\n\nFresh boot prints, *too big for a human*, "
              "lead up toward the gate. What do you do?")
        c.say("I follow the prints up to the gate, keeping to the ditch.", by="player")
        c.move("gate", rng=Dice(2))
        c.say("The gate is shut. A torch gutters above it, and someone has carved a tusk into the wood. "
              "In the mud lies a broken axe. Two shapes move on the platform. **What now?**")
        c.say("I try to slip past the guards.", by="player")
        c.check("sneaking", rng=Dice(12))
        c.commit({"note": "the horn sounds", "facts": {"hall.alarm": True}}, rng=Dice(4))
        c.say("A horn splits the rain. Somewhere below the hall, a chant answers it.")
        c.move("hall", rng=Dice(3))
        c.commit({"learn": ["orc_leader.fears"]})
        c.say("Grukk rises from his throne of shields, laughing too loud, and hefts his axe. Behind him a cultist "
              "in a sodden robe draws a curved knife. What do you do?")
        c.say("I draw my broadsword and go for the cultist first.", by="player")
        c.fight(["orc_leader", "cultist"], rng=Dice(1, 2, 3))
        c.attack("cultist", rng=Dice(3, 6, 6, 4))
        c.enemy("orc_leader", rng=Dice(5))
        c.defend("take", rng=Dice(6, 2))
        c.commit({"pc": {"conditions": {"add": ["angry"]}}})
    (Path(out) / "fight.json").write_text((root / "state.json").read_text())
    with campaign.session(root) as c:
        c.enemy("orc_leader", rng=Dice(5))
        c.defend("take", rng=Dice(8, 8))
        c.next_round(rng=Dice(1, 2))  # struck down after attacking: the first death roll is next round
        c.death_roll(rng=Dice(20))
        c.say("Not like this. Not in an orc's hall.", by="player")
        c.next_round(rng=Dice(1, 2))
        c.death_roll(rng=Dice(15))
    (Path(out) / "dead.json").write_text((root / "state.json").read_text())
    return root


def play_ironsworn(out):
    """A vow sworn, a road under way, a wound, and a miss that a burn could still turn into a hit."""
    root = campaign.create(Path(tempfile.mkdtemp()) / "game", IRONSWORN, ROOT / "examples" / "bell-under-the-hill", HRAFNA)
    with campaign.session(root) as c:
        c.say("Marrow Ford lies quiet under a sky the colour of slate. On the hill behind it, a bell tolls once. "
              "An old man on an upturned boat doesn't look up. **What do you do?**")
        c.say("I sit beside him and ask what he has seen.", by="player")
        c.act("gather_information", rng=Dice(5, 2, 8))
        c.commit({"pc": {"momentum": "+1"}, "npc": {"tam": {"attitude": "friendly", "memory": "sat beside the hero and talked to the water"}}})
        c.say("Tam says nothing for a long moment. Then, to the water: *three nights, now.* What do you say?")
        c.say("I swear to end it.", by="player")
        c.act("swear_an_iron_vow", stat="heart", rng=Dice(6, 1, 3))
        c.commit({"pc": {"momentum": "+2"}})
        c.track_add("Silence the bell", "vow", "dangerous")
        c.track_mark("silence_the_bell", times=2)
        c.move("hearth", rng=Dice(3))
        c.track_mark("bonds")
        c.move("ford", rng=Dice(3))
        c.move("road", rng=Dice(3))
        c.track_add("The barrow road", "journey", "troublesome")
        c.act("undertake_a_journey", rng=Dice(4, 3, 8))
        c.track_mark("the_barrow_road")
        c.commit({"pc": {"supply": "-1", "momentum": "+3", "conditions": {"add": ["shaken"]}}})
        c.act("face_danger", stat="edge", rng=Dice(1, 5, 8))
    (Path(out) / "ironsworn.json").write_text((root / "state.json").read_text())
    return root


def play_cut(out):
    """The GM speaks, the player rolls, and then cuts what the GM said: the message goes from the middle of the story."""
    root = campaign.create(Path(tempfile.mkdtemp()) / "game", DRAGONBANE, RED_TUSK, RAGNA)
    with campaign.session(root) as c:
        c.say("The gate is shut. A spider the size of a dog drops onto the road.")
        c.check("awareness", rng=Dice(5))
    (Path(out) / "uncut.json").write_text((root / "state.json").read_text())
    with campaign.session(root) as c:
        c.strike("no spiders")
    (Path(out) / "cut.json").write_text((root / "state.json").read_text())
    return root


if __name__ == "__main__":
    play(sys.argv[1])
