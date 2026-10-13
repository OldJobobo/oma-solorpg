"""The repository's own files: the Makefile a player runs first, and the docs that say what it does."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, install_rules


@unittest.skipUnless(shutil.which("make"), "needs make")
class MakefileTest(unittest.TestCase):
    """make run on a throwaway home, with the agent replaced by /bin/true."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        self.env = {**os.environ, "HOME": str(self.tmp / "home"), "SOLO_HOME": str(self.tmp / "games"),
                    "XDG_STATE_HOME": str(self.tmp / "state"), "XDG_CONFIG_HOME": str(self.tmp / "config"),
                    "XDG_CACHE_HOME": str(self.tmp / "cache")}

    def make(self, *args):
        return subprocess.run(["make", "-s", "-C", str(ROOT), "ASK=/bin/true", *args],
                              env=self.env, capture_output=True, text=True, timeout=60)

    def test_a_premise_with_backticks_reaches_solo_as_words_and_runs_nothing(self):
        ran = self.tmp / "ran"
        premise = f"a coast where `touch {ran}` the dead keep the lighthouses"
        install_rules(self.tmp / "games")
        result = self.make("campaign", "ID=salt", "SEED=1", f"PREMISE={premise}", f"TONE=grim `touch {ran}`")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(ran.exists())
        self.assertIn(f"`touch {ran}`", (self.tmp / "games" / "adventures" / "salt" / "premise.toml").read_text())

    def test_a_campaign_folder_with_backticks_runs_nothing(self):
        ran = self.tmp / "ran"
        self.make("campaign-next", f"CAMPAIGN={self.tmp}/`touch {ran}`")
        self.assertFalse(ran.exists())

    def test_uninstall_puts_the_desktop_back_before_it_removes_anything(self):
        steps = self.make("-n", "uninstall").stdout
        self.assertIn("desk restore", steps)
        self.assertLess(steps.index("desk restore"), steps.index("plugin disable"))

    def test_every_target_is_phony(self):
        makefile = (ROOT / "Makefile").read_text()
        phony = set(re.search(r"^\.PHONY:(.*)$", makefile, re.M).group(1).split())
        targets = set(re.findall(r"^([a-z][a-z-]*):", makefile, re.M))
        self.assertEqual(targets - phony, set())


if __name__ == "__main__":
    unittest.main()
