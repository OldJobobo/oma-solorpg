"""The repository's own files: the Makefile a player runs first, and the docs that say what it does."""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, install_rules, leave_the_shell_out


@unittest.skipUnless(shutil.which("make"), "needs make")
class MakefileTest(unittest.TestCase):
    """make run on a throwaway home, with the agent replaced by /bin/true."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name)
        leave_the_shell_out(self)
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

    def test_a_premise_with_a_dollar_reaches_solo_as_typed_and_runs_nothing(self):
        ran = self.tmp / "ran"
        premise = f"a toll of $5 at the $(gate) where $(shell touch {ran}) the dead keep the lighthouses"
        install_rules(self.tmp / "games")
        result = self.make("campaign", "ID=salt", "SEED=1", f"PREMISE={premise}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(ran.exists())
        self.assertIn(premise, (self.tmp / "games" / "adventures" / "salt" / "premise.toml").read_text())

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

    def test_the_docs_name_every_button_a_dying_hero_has(self):
        # With the solo rules the Table offers Save yourself and Rally beside the death roll.
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        plan = (ROOT / "docs" / "PLAN.md").read_text(encoding="utf-8")
        dying = [next(line for line in readme.splitlines() if "At 0 HP you're dying" in line),
                 next(line for line in plan.splitlines() if line.startswith("| Dying |"))]
        for label in ("Death roll", "Save yourself", "Rally"):
            self.assertIn(f'text: "{label}"', panel)
            for line in dying:
                self.assertIn(label, line)

    def test_ci_checks_the_pyside6_contributing_says_it_does(self):
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        checked = re.findall(r'PySide6-Essentials==(\d+\.\d+)\.\*', workflow)
        self.assertEqual(len(checked), 1)
        self.assertIn(f"CI checks it on {checked[0]}", contributing)
        self.assertNotIn("6.11 and 6.12 are checked", contributing)

    def test_the_roadmap_never_asks_for_a_scenario_that_exists(self):
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        scenarios = ROOT / "tests" / "gm_eval" / "scenarios"
        for name, words in (("bell-cheat", "add the cheat"), ("bell-table-settings", "lines-and-veils scenario")):
            self.assertTrue((scenarios / f"{name}.toml").exists(), name)
            self.assertNotIn(words, roadmap)

    def test_plan_says_what_is_true_now(self):
        plan = (ROOT / "docs" / "PLAN.md").read_text(encoding="utf-8")
        for stale in ("omarchy agent`", "the agent window", "GM window: omarchy agent", "Single-window mode: revisit",
                      "Until the cut button", "no cap on its tool calls", "Open the GM", "the GM window opens"):
            self.assertNotIn(stale, plan)
        # The Table's header buttons are the ones Panel.qml has.
        header = next(line for line in plan.splitlines() if line.startswith("- Header: campaign title"))
        panel = (ROOT / "Panel.qml").read_text(encoding="utf-8")
        for label in ("Open the Book", "Terminal"):
            self.assertIn(label, header)
            self.assertIn(f'text: "{label}"', panel)
        # Phases 7 to 8d were never defined anywhere a reader could look them up.
        self.assertNotRegex(plan, r"(?i)\bphases? \d")

    def test_the_commit_keys_are_a_table_with_every_key_the_engine_takes(self):
        from solo import campaign
        text = (ROOT / "docs" / "PACK_FORMAT.md").read_text(encoding="utf-8")
        section = text[text.index("## Commits (what the GM writes)"):text.index("## Format versions")]
        keys = set(re.findall(r"^\| `(\w+)` \|", section, re.M))
        self.assertEqual(keys, set(campaign._COMMIT_KEYS))
        # A commit's time takes the clock's units as well as the system's.
        time = re.search(r"^\| `time` \|(.*)$", section, re.M).group(1)
        self.assertEqual([unit for unit in campaign._CLOCK if f"{unit}s" not in time], [])


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
    PLACES = ["Makefile", "CONTRIBUTING.md", "docs/INGESTION.md", "solo/extract.py", "skills/solo-rules-import/SKILL.md", "site/index.html"]

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


class SiteTest(unittest.TestCase):
    def site(self):
        return (ROOT / "site" / "index.html").read_text(encoding="utf-8")

    def test_the_sites_install_is_the_readmes(self):
        html = self.site()
        install = html[html.index('<section id="install"'):html.index("</section>", html.index('<section id="install"'))]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        pin = re.search(r"git checkout --detach ([0-9a-f]{40})", readme).group(1)
        self.assertIn(f"git checkout --detach {pin}", install, "the site pins the commit the README pins")
        for words in ("make install", "The Bell Under the Hill", "make dragonbane BOOKS=", "pacman -S python-pymupdf"):
            self.assertIn(words, install)
        self.assertNotIn("it comes with it", install)
        self.assertNotIn("--system pymupdf", html)

    def test_the_page_asks_only_for_media_that_exists(self):
        for path in re.findall(r'(?:src|poster)="((?:media|img)/[^"]+)"', self.site()):
            self.assertTrue((ROOT / "site" / path).exists(), path)

    # The screenshots of The Sinking Tower and Alone in Deepfall Breach, played from the author's own
    # packs. Every one had a book's numbers in frame (a monster's HP and armor, a pre-generated hero's,
    # the solo booklet's cultists), or an NPC's lines from the book in the codex; the title cards had
    # the same fights under them. They came out, and none comes back under another name.
    TAKEN_OUT = {
        "62f911df424c7b6ce187904cfdf9d14a2e67e0d0479f7b49d114bee2615d9dad",  # tower-fight
        "68765768b1250a70f273e60c851095f8d26f10e35b9c22bd3da8dccbdabfada6",  # tower-codex
        "f6a9c230c89a786260c1c4b1a0add51d9cd0f8e6cfe9ab3563871d16cde88886",  # tower-dragon
        "7c2664980766d8d64c5cb390f5ac2093b2d471778869cb0f63f605bfc819e1ae",  # tower-title
        "7e9d9b56dd595c2ad70cc0c6d60a0e6ca64b9542fc432d8d3bba69b1f9f03f5a",  # breach-fight
        "2a65dd9b8b5a5e24d27b9a7d5eaac9058560cb5f2ba09bf95213c77abfda8b13",  # breach-codex
        "791c1e5ecb771e4b90fab8c9d9ae4e134e81471a53128a27be445883cea37cb6",  # breach-demon
        "32dab13d6798fe2ab0e66973710e57b6376b06e1079d07c6fcd8b82bb927e23f",  # breach-title
        "2a2ac135c5bd3e53b413c18aed553709641d2aef8be039c07ae9f837cc275778",  # table-breach
    }

    def test_no_screenshot_with_a_books_numbers_in_frame_is_in_the_repository(self):
        import hashlib
        pictures = [*(ROOT / "site").rglob("*"), *(ROOT / "assets").glob("*"), *ROOT.glob("*")]
        for path in pictures:
            if path.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg", ".gif"}:
                self.assertNotIn(hashlib.sha256(path.read_bytes()).hexdigest(), self.TAKEN_OUT, path.relative_to(ROOT))
        self.assertNotRegex(self.site(), r'img/(tower|breach)-|img/table-breach')


class ReleaseTest(unittest.TestCase):
    def test_the_manifests_version_has_its_section_in_the_changelog(self):
        import json
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertRegex(changelog, rf"\n## {re.escape(manifest['version'])}( \(not yet tagged\))?\n")
        self.assertIn("\n## 0.3.0\n", changelog)
        # The description says what a player needs before they install.
        self.assertIn("Ironsworn plays free", manifest["description"])
        self.assertIn("your own copy", manifest["description"])
        self.assertIn("\n## Update\n", (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_the_install_pins_the_version_the_readme_says_it_does(self):
        import json
        import subprocess
        version = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))["version"]
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        site = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        pin = re.search(r"git checkout --detach ([0-9a-f]{40})", readme).group(1)
        versions = re.findall(r"\n## (\d+\.\d+\.\d+)", changelog)
        if f"\n## {version} (not yet tagged)\n" in changelog:
            # Until this version is tagged the pin is the one before it, and the README and the site say
            # so instead of describing it as what the reader installs.
            pinned = versions[versions.index(version) + 1]
            for text in (readme, site):
                self.assertIn(f"one from before {version}", text)
        else:
            pinned = version
            self.assertNotIn(f"from before {version}", readme)

        def git(*args):
            try:
                return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60)
            except OSError:
                self.skipTest("git isn't installed")
        shown = git("show", f"{pin}:manifest.json")
        if shown.returncode != 0:
            self.skipTest("the pinned commit isn't in this clone (a shallow one, or a tarball)")
        self.assertEqual(json.loads(shown.stdout)["version"], pinned, "the README pins a commit of another version")
        self.assertEqual(git("merge-base", "--is-ancestor", pin, "HEAD").returncode, 0, "the pinned commit is in this branch's history")
        tag = git("rev-parse", "-q", "--verify", f"refs/tags/{pinned}^{{commit}}")
        if tag.returncode == 0:
            self.assertEqual(tag.stdout.strip(), pin, f"the README pins the commit tagged {pinned}")


class RepositoryTest(unittest.TestCase):
    def test_ci_installs_what_the_skipping_tests_need_and_loads_the_qml(self):
        workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
        self.assertIn("pip install pymupdf", workflow)
        self.assertIn("glslang-tools", workflow)
        self.assertIn("make qml-check", workflow)
        self.assertIn("package-ecosystem: github-actions", (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))

    def test_the_docs_say_ci_checks_the_book_fingerprints_only_once_they_are_committed(self):
        # Without tests/fixtures/book_fingerprints.txt the book-text test skips in CI, and a doc that says every
        # pull request is checked against it promises a check nobody runs.
        hedge = "once the maintainer commits them"
        committed = (ROOT / "tests" / "fixtures" / "book_fingerprints.txt").exists()
        for path in (ROOT / "NOTICE.md", ROOT / "CONTRIBUTING.md", ROOT / "docs" / "INGESTION.md", ROOT / "tests" / "test_no_book_text.py"):
            with self.subTest(path.name):
                (self.assertNotIn if committed else self.assertIn)(hedge, path.read_text(encoding="utf-8"))
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        item = roadmap[roadmap.index("\n## 1. "):roadmap.index("\n## 2. ")]
        left = item[item.index("\nLeft:"):item.index("\nDone when:")]
        (self.assertNotIn if committed else self.assertIn)("book fingerprints", left)

    def test_security_counts_as_a_vulnerability_only_what_the_design_holds_back(self):
        security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        counts = security[security.index("## What counts"):security.index("## Which versions")]
        # `extends` names a pack wherever it is (docs/PACK_FORMAT.md): the house fixture's reaches up out of its folder.
        self.assertIn('extends = "../', (ROOT / "tests" / "fixtures" / "house" / "system.toml").read_text(encoding="utf-8"))
        outside = next(line for line in counts.splitlines() if "outside the pack's folder" in line)
        self.assertNotIn("an `extends`", outside)
        self.assertIn("`extends` names a pack, which can be anywhere", counts)
        # Codex has no list of allowed commands and reads anywhere, which the README says: under it, only a write
        # outside the campaign folder gets past what it holds back.
        commands = next(line for line in counts.splitlines() if "run a command it isn't allowed" in line)
        self.assertIn("Under Codex", commands)

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
        # The credit that travels with the pack lists the same changes, every one.
        def changes(text):
            return text[text.index("`solo import datasworn` made these changes to the text:"):text.index("Apart from that, the book's text is kept as written.")]
        pack = (ROOT / "packs" / "ironsworn" / "NOTICE.md").read_text(encoding="utf-8")
        self.assertIn(credit, pack)
        self.assertEqual(changes(pack), changes(notice))
        for change in ("named after the group first", "the row loses the link, and the importer lists it"):
            self.assertIn(change, changes(pack))

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
