"""Shared test helpers: fixed dice and throwaway campaigns."""

import contextlib
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from solo import campaign

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
# The bundled pack holds only Dragonbane's names; the rules come from the player's book.
# The tests lay a made-up rules layer over it (tests/fixtures/house), the way a pack built
# from the book is laid over it in play.
BUNDLED = ROOT / "packs" / "dragonbane"
DRAGONBANE = FIXTURES / "house"
# The same, with a made-up monster or two (their attacks, what they resist) over it.
BEASTS = FIXTURES / "beasts"
# The same, where a Dragon on an attack is the player's choice and a Demon brings a mishap.
DRAGONS = FIXTURES / "dragons"
# The same, where a threat advances once for each activity of a stretch or more.
ACTIVITY = FIXTURES / "activity"
RED_TUSK = ROOT / "examples" / "red-tusk"
RAGNA = FIXTURES / "ragna.toml"
# A made-up mage, for the tests of magic.
MAGE = FIXTURES / "mage.toml"
# Ironsworn is the one bundled game with its rules in the repository (CC BY, see NOTICE.md), so
# the tests for its engine family play on the pack itself, on a small made-up adventure.
IRONSWORN = ROOT / "packs" / "ironsworn"
OATH = FIXTURES / "oath"
HRAFNA = IRONSWORN / "characters" / "hrafna.toml"


def install_rules(home):
    """Put the test rules where a player's pack built from their book goes (SOLO_HOME/systems),
    so commands that look Dragonbane up by name find rules over the bundled names."""
    systems = Path(home) / "systems"
    systems.mkdir(parents=True, exist_ok=True)
    (systems / "dragonbane").symlink_to(DRAGONBANE, target_is_directory=True)


def leave_the_shell_out(test):
    """Run the test without what a player or developer may have exported: a seed changes every roll and
    what each event records, SOLO_TRACE gets the test's commands appended, the SOLO_GM_* limits change a
    turn's, and CLAUDECODE or SOLO_BOOK would make it a Book turn. Each comes back after the test."""
    patch = unittest.mock.patch.dict(os.environ)
    patch.start()
    test.addCleanup(patch.stop)
    for name in list(os.environ):
        if name in ("SOLO_SEED", "SOLO_TRACE", "SOLO_BOOK", "CLAUDECODE") or name.startswith("SOLO_GM_"):
            del os.environ[name]


class Dice:
    """Stands in for random.Random and returns the given faces in order."""

    def __init__(self, *faces):
        self.faces = list(faces)

    def randint(self, low, high):
        face = self.faces.pop(0)
        assert low <= face <= high, f"face {face} is outside {low}..{high}"
        return face


class CampaignTest(unittest.TestCase):
    """A fresh campaign folder and XDG state folder for every test."""

    system, adventure, character = DRAGONBANE, RED_TUSK, RAGNA

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        leave_the_shell_out(self)
        patch = unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.tmp / "state")})
        patch.start()
        self.addCleanup(patch.stop)
        self.root = campaign.create(self.tmp / "game", self.system, self.adventure, self.character)

    def session(self):
        return campaign.session(self.root)


class LikelihoodTest(CampaignTest):
    """Dragonbane without its solo tools (the fortune chart, the inspiration table, dragon and
    demon effects): the likelihood oracle, chaos and scene checks, as systems without a
    fortune chart play."""

    @contextlib.contextmanager
    def session(self):
        with campaign.session(self.root) as c:
            for key in ("oracle", "effects"):
                c.system.pop(key, None)
            yield c
