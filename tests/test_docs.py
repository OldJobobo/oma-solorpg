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


class ReadmeTest(unittest.TestCase):
    def readme(self):
        return (ROOT / "README.md").read_text(encoding="utf-8")

    def test_every_command_is_in_the_readmes_commands_table(self):
        from solo import cli
        text = self.readme()
        table = text[text.index("\n## Commands\n"):].split("\n## ", 2)[1]
        listed = set()
        for row in table.splitlines():
            if row.startswith("| `"):
                first = re.split(r"(?<!\\)\|", row)[1]
                listed |= {span.removeprefix("solo ").split()[0] for span in re.findall(r"`([^`]+)`", first)}
        missing = [name for name in cli.command_names() if name not in listed]
        self.assertEqual(missing, [], f"the README's Commands table doesn't list: {', '.join(missing)}")

    def test_the_quick_start_is_the_three_commands_and_the_first_adventure(self):
        text = self.readme()
        quick = text[text.index("## Quick start"):text.index("\n## ", text.index("## Quick start") + 1)]
        self.assertEqual(re.findall(r"^(git clone|git checkout|make install)", quick, re.M), ["git clone", "git checkout", "make install"])
        self.assertIn("The Bell Under the Hill", quick)
        self.assertLess(len(quick.split()), 200)
        for section in ("## Install", "## Update", "## Uninstall", "## Troubleshooting", "## Dragonbane"):
            self.assertIn(f"\n{section}\n", text)


def anchors(text):
    """The anchors GitHub gives a Markdown file's headings: lower case, punctuation dropped, spaces as hyphens."""
    found = set()
    for heading in re.findall(r"^#{1,6} (.+)$", re.sub(r"^```.*?^```", "", text, flags=re.M | re.S), re.M):
        found.add(re.sub(r"[^\w\- ]", "", heading.replace("`", "").lower()).replace(" ", "-"))
    return found


class DesignDocsTest(unittest.TestCase):
    DOCS = ["docs/PLAN.md", "docs/PACK_FORMAT.md", "docs/INGESTION.md"]

    def test_each_design_doc_opens_with_a_contents_list_whose_links_land(self):
        for doc in self.DOCS:
            text = (ROOT / doc).read_text(encoding="utf-8")
            contents = next(line for line in text.splitlines() if line.startswith("Contents: "))
            links = re.findall(r"\]\(#([^)]+)\)", contents)
            self.assertGreater(len(links), 5, doc)
            self.assertEqual([link for link in links if link not in anchors(text)], [], doc)

    def test_plan_says_what_is_true_now(self):
        plan = (ROOT / "docs" / "PLAN.md").read_text(encoding="utf-8")
        for stale in ("omarchy agent`", "the agent window", "GM window: omarchy agent", "Single-window mode: revisit",
                      "Until the cut button", "no cap on its tool calls", "(phase "):
            self.assertNotIn(stale, plan)

    def test_the_commit_keys_are_a_table_with_every_key_the_engine_takes(self):
        from solo import campaign
        text = (ROOT / "docs" / "PACK_FORMAT.md").read_text(encoding="utf-8")
        section = text[text.index("## Commits (what the GM writes)"):text.index("## Format versions")]
        keys = set(re.findall(r"^\| `(\w+)` \|", section, re.M))
        self.assertEqual(keys, set(campaign._COMMIT_KEYS))


class RoadmapTest(unittest.TestCase):
    def test_the_roadmap_is_the_plan_ahead_and_the_logs_are_in_history(self):
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        items = re.split(r"\n## \d\. ", roadmap)[1:]
        self.assertEqual(len(items), 6)
        for item in items:
            for part in ("Goal:", "Status:", "Done when:"):
                self.assertIn(f"\n{part} ", item, item.split("\n", 1)[0])
        self.assertLessEqual(max(len(line) for line in roadmap.splitlines()), 600)
        self.assertNotRegex(roadmap, r"(First|Second|Third|Fourth|Fifth) (import|pass), run")
        self.assertIn("(docs/HISTORY.md)", roadmap)
        self.assertIn("Fifth pass, run (2026-10-01)", (ROOT / "docs" / "HISTORY.md").read_text(encoding="utf-8"))
        # results.tsv is in the repository; the roadmap says what its runs are worth.
        self.assertTrue((ROOT / "tests" / "gm_eval" / "results.tsv").exists())
        self.assertNotIn("results.tsv` isn't in the repository", roadmap)


class PyMuPDFTest(unittest.TestCase):
    # Arch marks its system Python as externally managed, so uv and pip refuse to install into it;
    # on Omarchy the package comes from pacman, and the README says what to do elsewhere.
    PLACES = ["Makefile", "CONTRIBUTING.md", "docs/INGESTION.md", "solo/extract.py", "skills/solo-rules-import/SKILL.md"]

    def test_every_place_that_says_how_to_install_pymupdf_gives_the_pacman_line(self):
        for place in self.PLACES:
            text = (ROOT / place).read_text(encoding="utf-8")
            self.assertNotIn("--system pymupdf", text, place)
            self.assertIn("pacman -S python-pymupdf", text, place)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("sudo pacman -S python-pymupdf", readme)
        self.assertIn("python3 -m pip install --user pymupdf", readme)

    def test_extract_without_pymupdf_says_how_to_install_it_on_omarchy(self):
        import sys
        import unittest.mock
        from solo import SoloError, extract
        with unittest.mock.patch.dict(sys.modules, {"pymupdf": None}), self.assertRaises(SoloError) as refused:
            extract._pymupdf()
        self.assertIn("sudo pacman -S python-pymupdf", str(refused.exception))


class RepositoryTest(unittest.TestCase):
    def test_ci_installs_what_the_skipping_tests_need_and_loads_the_qml(self):
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("pip install pymupdf", workflow)
        self.assertIn("glslang-tools", workflow)
        self.assertIn("make qml-check", workflow)
        self.assertIn("package-ecosystem: github-actions", (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))

    def test_the_issue_forms_know_the_main_import_and_point_security_reports_away_from_issues(self):
        forms = ROOT / ".github" / "ISSUE_TEMPLATE"
        self.assertIn("make dragonbane", (forms / "import-went-wrong.yml").read_text(encoding="utf-8"))
        self.assertIn("solo report", (forms / "something-went-wrong.yml").read_text(encoding="utf-8"))
        self.assertIn("/security/policy", (forms / "config.yml").read_text(encoding="utf-8"))
        self.assertIn("Report a vulnerability", (ROOT / "SECURITY.md").read_text(encoding="utf-8"))
        # A relative link 404s from a pull request's page.
        self.assertNotIn("](../", (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8"))


class LicenseTest(unittest.TestCase):
    def test_license_is_the_mit_text_alone_so_github_can_tell_which_it_is(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("MIT License\n"))
        self.assertTrue(text.endswith("DEALINGS IN THE\nSOFTWARE.\n"))
        # What the license doesn't cover is said in NOTICE.md instead.
        self.assertIn("It does not cover Dragonbane", (ROOT / "NOTICE.md").read_text(encoding="utf-8"))

    def test_the_ironsworn_credit_says_every_change_the_importer_makes(self):
        import tomllib
        from solo import datasworn
        notice = (ROOT / "NOTICE.md").read_text(encoding="utf-8")
        credit = tomllib.loads((ROOT / "packs" / "ironsworn" / "system.toml").read_text(encoding="utf-8"))["credit"]
        self.assertIn(credit, notice)
        pointer = datasworn._clean("{{table:classic/oracles/moves/pay_the_price}}", {"moves/pay_the_price": "pay_the_price"})
        self.assertIn(pointer, notice)
        self.assertEqual(datasworn._clean("Roll on {{table:classic/oracles/left/out}}.", {}), "Roll on .")
        self.assertIn("A link to a table that wasn't imported is removed", notice)
        self.assertIn("Datasworn", notice)

    def test_the_dragonbane_license_has_one_name_outside_the_notice_it_recommends(self):
        # Free League's license is the Dragonbane Third-Party Tabletop Module License. The notice it
        # recommends (section 9) calls it the Third Party Supplement License, and is kept word for word.
        notice = "This Supplement was created under Fria Ligan AB's Dragonbane Third Party Supplement License."
        files = [ROOT / "README.md", ROOT / "NOTICE.md", ROOT / "docs" / "INGESTION.md", ROOT / "site" / "index.html"]
        for path in files:
            text = path.read_text(encoding="utf-8").replace(notice, "")
            names = set(re.findall(r"Dragonbane Third[- ]Party[\w -]*?License", text))
            self.assertLessEqual(names, {"Dragonbane Third-Party Tabletop Module License"}, path.name)
        self.assertIn(notice, (ROOT / "NOTICE.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
