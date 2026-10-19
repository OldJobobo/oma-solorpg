# oma-solorpg: the commands, one make target each. `make` alone lists them.
#
# Your books, the packs built from them and your campaigns live in SOLO_HOME
# (~/Games/solo), never in this folder. Nothing here writes into the repository.

SHELL      := /bin/sh
SOLO_BIN   := $(CURDIR)/bin/solo
ASK        := $(CURDIR)/bin/ask-agent
SOLO_HOME  ?= $(HOME)/Games/solo
export SOLO_HOME

PLUGIN     := cabral.oma-solorpg
SYSTEMS    := $(SOLO_HOME)/systems
SOURCES    := $(SOLO_HOME)/sources
ADVENTURES := $(SOLO_HOME)/adventures
# Dragonbane's rules in two layers over the names this repository ships: the rulebook, and
# on top the pack campaigns use, which holds the solo rules when you have that book.
RULEBOOK   := $(SYSTEMS)/dragonbane-rulebook
TOP        := $(SYSTEMS)/dragonbane
SOLO_TASK    = The solo rules are extracted in $(SOURCES)/dragonbane-solo and go into $(TOP) (it extends dragonbane-rulebook; a pack laid over the rulebook by make supplement is added to its extends list), whose inventory is started too.
NO_SOLO_TASK = I have no solo rules book: leave $(TOP) as it is.
# What a player types reaches the recipes as environment variables, read as "$$PREMISE": a
# premise with backticks or $( ) in it is words, and the shell never runs them. Each is taken
# as typed, or make would read a $( ) in it as its own, and run a $(shell ...).
override PREMISE  := $(value PREMISE)
override TONE     := $(value TONE)
override CAMPAIGN := $(value CAMPAIGN)
export PREMISE TONE CAMPAIGN

.PHONY: help install uninstall deps dragonbane rules supplement check adventure check-adventure campaign campaign-next test qml-check site

help:
	@echo "oma-solorpg"
	@echo ""
	@echo "  make install                         link solo, the GM skills and the Omarchy plugin; enable the plugin"
	@echo "  make uninstall                       disable the plugin and remove the links make install made (your games and packs stay)"
	@echo "  make dragonbane BOOKS=<folder of PDFs>  build Dragonbane's packs and adventures from your books (the rules, the Book of Magic, the card decks, the solo booklet, the Quickstart and the Adventure Book), no agent"
	@echo "  make rules BOOK=<pdf> [SOLO_BOOK=<pdf>]  the same by an agent, for printings the importers don't know"
	@echo "  make supplement ID=<id> BOOK=<pdf>   lay one more book over the rulebook: a card deck, the Book of Magic"
	@echo "  make check                           validate the rules you built, audit them against the books, run their own checks"
	@echo "  make adventure ID=<id> PDF=<pdf>     start an adventure pack from a PDF you own"
	@echo "  make adventure ID=<id> FOUNDRY=<dir> start one from a Foundry VTT export"
	@echo "  make check-adventure ID=<id>         validate an adventure, show its outline, audit it"
	@echo "  make campaign ID=<id> PREMISE=\"...\" [TONE=grim] [MISSIONS=3] [SEED=n]"
	@echo "                                       roll a campaign from a premise and have your agent write it"
	@echo "  make campaign-next CAMPAIGN=<folder> roll a generated campaign's next mission from what the hero did"
	@echo "  make test                            the engine's tests"
	@echo "  make qml-check                       load the plugin's QML offscreen (needs PySide6)"
	@echo "  make site                            serve the website (site/) on http://localhost:8000"
	@echo ""
	@echo "  AGENT=claude|codex picks the agent that does the reading (default: Omarchy's default agent)."
	@echo "  SOLO_HOME=$(SOLO_HOME)"

# solo setup says what is missing, and how to enable the plugin when omarchy isn't here to do it.
install:
	$(SOLO_BIN) setup --plugin
	@if command -v omarchy >/dev/null 2>&1; then omarchy plugin enable $(PLUGIN); fi

# Puts back what the desktop effects changed, then removes only the symlinks that point into this
# folder. ~/Games/solo (campaigns, packs), ~/.local/state/solo and ~/.cache/solo* are left alone.
uninstall:
	-$(SOLO_BIN) desk restore
	@if command -v omarchy >/dev/null 2>&1; then omarchy plugin disable $(PLUGIN) || true; fi
	@for link in "$$HOME/.local/bin/solo" "$$HOME/.config/omarchy/plugins/$(PLUGIN)" \
	    $$(for d in .claude .agents .codex .pi/agent; do for s in solo-gm solo-import solo-rules-import solo-campaign; do echo "$$HOME/$$d/skills/$$s"; done; done); do \
	  if [ -L "$$link" ] && case "$$(readlink "$$link")" in "$(CURDIR)"/*|"$(CURDIR)") true;; *) false;; esac; then rm "$$link" && echo "removed $$link"; fi; \
	done

# PyMuPDF reads the PDFs. Only the import commands need it.
deps:
	@python3 -c "import pymupdf" 2>/dev/null || { \
	  echo "solo extract needs PyMuPDF: on Omarchy, sudo pacman -S python-pymupdf (the README's Troubleshooting has other systems)"; exit 1; }

# Dragonbane's packs and adventures from your own PDFs, without an agent: each book an importer here knows is read by its bookmarks and layout, and what the pack holds is checked
# against the book's pages. Nothing of a book is in this repository: the importers hold where things are and how to read them. REPLACE=1 builds again over packs made this way.
dragonbane: deps
	@test -n "$(BOOKS)" || { echo "usage: make dragonbane BOOKS=~/Books/Dragonbane   (a folder of your PDFs, or one PDF)"; exit 2; }
	$(SOLO_BIN) import book "$(BOOKS)" $(if $(REPLACE),--replace)

# 1. The books as text, page by page (once: a second run keeps what is there).
# 2. The two packs, each saying what it is laid over.
# 3. A first inventory per book: an item per section and table, every page cited.
# 4. Your agent reads the books and fills the packs, with the solo-rules-import skill.
rules: deps
	@test -n "$(BOOK)" || { echo "usage: make rules BOOK=~/Books/<rulebook>.pdf [SOLO_BOOK=~/Books/<solo rules>.pdf]"; exit 2; }
	@test -f "$(SOURCES)/dragonbane-rulebook/manifest.json" || $(SOLO_BIN) extract "$(BOOK)" --out "$(SOURCES)/dragonbane-rulebook"
	@mkdir -p "$(RULEBOOK)" "$(TOP)"
	@test -f "$(RULEBOOK)/system.toml" || printf 'format = 1\nextends = "bundled:dragonbane"\n' > "$(RULEBOOK)/system.toml"
	@test -f "$(TOP)/system.toml" || printf 'format = 1\nextends = "dragonbane-rulebook"\n' > "$(TOP)/system.toml"
	@grep -q 'dragonbane-rulebook' "$(TOP)/system.toml" || { \
	  echo "$(TOP)/system.toml doesn't extend dragonbane-rulebook: an older pack is there. Move it aside and run make rules again."; exit 1; }
	@test -f "$(RULEBOOK)/inventory.toml" || $(SOLO_BIN) inventory "$(RULEBOOK)" --extract "$(SOURCES)/dragonbane-rulebook"
	@if [ -n "$(SOLO_BOOK)" ]; then \
	  test -f "$(SOURCES)/dragonbane-solo/manifest.json" || $(SOLO_BIN) extract "$(SOLO_BOOK)" --out "$(SOURCES)/dragonbane-solo"; \
	  test -f "$(TOP)/inventory.toml" || $(SOLO_BIN) inventory "$(TOP)" --extract "$(SOURCES)/dragonbane-solo"; \
	fi
	@$(ASK) "$(SOLO_HOME)" "Use the solo-rules-import skill to build Dragonbane's rules from my books. The repository is $(CURDIR): read docs/INGESTION.md and docs/PACK_FORMAT.md there first. The rulebook is extracted in $(SOURCES)/dragonbane-rulebook and goes into $(RULEBOOK), whose inventory is started. $(if $(SOLO_BOOK),$(SOLO_TASK),$(NO_SOLO_TASK)) The bundled pack holds only names: every key it lists under needs must come from the rulebook. Work a chapter at a time, and run make check in the repository until it passes."

# One more book over the rulebook, in a pack of its own so it audits against its own pages: a
# card deck, the Book of Magic, a bestiary. It is extracted, inventoried and mapped like the
# rulebook; then it goes on the top pack's `extends` list, which is what campaigns play on.
supplement:
	@test -n "$(ID)" -a -n "$(BOOK)" || { echo "usage: make supplement ID=<id> BOOK=~/Books/<pdf>   (the pack is dragonbane-<id>)"; exit 2; }
	@$(MAKE) --no-print-directory deps
	@test -f "$(SYSTEMS)/dragonbane-rulebook/system.toml" || { echo "build the rulebook first: make rules BOOK=<rulebook pdf>"; exit 1; }
	@test -f "$(SOURCES)/dragonbane-$(ID)/manifest.json" || $(SOLO_BIN) extract "$(BOOK)" --out "$(SOURCES)/dragonbane-$(ID)"
	@mkdir -p "$(SYSTEMS)/dragonbane-$(ID)"
	@test -f "$(SYSTEMS)/dragonbane-$(ID)/system.toml" || printf 'format = 1\nextends = "dragonbane-rulebook"\n' > "$(SYSTEMS)/dragonbane-$(ID)/system.toml"
	@test -f "$(SYSTEMS)/dragonbane-$(ID)/inventory.toml" || $(SOLO_BIN) inventory "$(SYSTEMS)/dragonbane-$(ID)" --extract "$(SOURCES)/dragonbane-$(ID)"
	@$(ASK) "$(SOLO_HOME)" "Use the solo-rules-import skill to build a supplement pack from my book. The repository is $(CURDIR): read docs/INGESTION.md and docs/PACK_FORMAT.md there first. The book is extracted in $(SOURCES)/dragonbane-$(ID) and goes into $(SYSTEMS)/dragonbane-$(ID) (it extends dragonbane-rulebook), whose inventory is started. Then list it in the extends of $(TOP)/system.toml (a list, the rulebook first: extends = [\"dragonbane-rulebook\", \"dragonbane-$(ID)\"]), and run make check in the repository until it passes."

# Each book's pack (the rulebook, each supplement over it, the top pack) against its inventory
# and its pages, and against its own fixed-dice checks if it has a checks/ folder (they hold
# the book's numbers, so they live with the pack), then the whole against what a campaign needs.
check:
	@for pack in "$(SYSTEMS)"/dragonbane-*/ "$(TOP)"; do \
	  if [ -f "$$pack/inventory.toml" ]; then $(SOLO_BIN) audit --system "$$pack" || exit 1; fi; \
	  if [ -d "$$pack/checks" ]; then OMA_SOLORPG="$(CURDIR)" python3 -m unittest discover -s "$$pack/checks" || exit 1; fi; \
	done
	$(SOLO_BIN) validate --system dragonbane

adventure:
	@test -n "$(ID)" || { echo "usage: make adventure ID=<id> PDF=<pdf>   or   make adventure ID=<id> FOUNDRY=<export files or folder>"; exit 2; }
	@test -n "$(PDF)$(FOUNDRY)" || { echo "give the adventure: PDF=<pdf> or FOUNDRY=<export files or folder>"; exit 2; }
	@mkdir -p "$(ADVENTURES)/$(ID)"
ifneq ($(FOUNDRY),)
	$(SOLO_BIN) import foundry adventure $(FOUNDRY) --out "$(ADVENTURES)/$(ID)"
	@$(ASK) "$(SOLO_HOME)" "Use the solo-import skill to enrich the adventure pack in $(ADVENTURES)/$(ID), imported from a Foundry export: factions, clocks, gates, branches, NPC profiles, voices. The repository is $(CURDIR): read docs/INGESTION.md and docs/PACK_FORMAT.md there first. Run make check-adventure ID=$(ID) in the repository until it is clean, then walk me through what you inferred."
else
	@$(MAKE) --no-print-directory deps
	@test -f "$(SOURCES)/$(ID)/manifest.json" || $(SOLO_BIN) extract "$(PDF)" --out "$(SOURCES)/$(ID)"
	@test -f "$(ADVENTURES)/$(ID)/inventory.toml" || $(SOLO_BIN) inventory "$(ADVENTURES)/$(ID)" --extract "$(SOURCES)/$(ID)"
	@$(ASK) "$(SOLO_HOME)" "Use the solo-import skill to build the adventure pack in $(ADVENTURES)/$(ID) from the PDF extracted in $(SOURCES)/$(ID), whose inventory is started. Give adventure.toml a system (dragonbane) and a summary so it shows on the New adventure screen. The repository is $(CURDIR): read docs/INGESTION.md and docs/PACK_FORMAT.md there first. Run make check-adventure ID=$(ID) in the repository until it is clean, then walk me through what you inferred."
endif

check-adventure:
	@test -n "$(ID)" || { echo "usage: make check-adventure ID=<id>"; exit 2; }
	$(SOLO_BIN) validate --adventure "$(ID)"
	$(SOLO_BIN) outline --adventure "$(ID)"
	@if [ -f "$(ADVENTURES)/$(ID)/inventory.toml" ]; then $(SOLO_BIN) audit --adventure "$(ID)"; fi
	@if [ -d "$(ADVENTURES)/$(ID)/checks" ]; then OMA_SOLORPG="$(CURDIR)" python3 -m unittest discover -s "$(ADVENTURES)/$(ID)/checks"; fi
	@if [ -f "$(ADVENTURES)/$(ID)/premise.toml" ] || [ -f "$(ID)/premise.toml" ]; then $(SOLO_BIN) campaign check "$(ID)"; fi

# A campaign from a premise: the engine rolls its bones (the hub, the factions, the first
# mission's waypoints, each roll recorded), then your agent writes it with the solo-campaign skill.
campaign:
	@test -n "$(ID)" -a -n "$$PREMISE" || { echo 'usage: make campaign ID=<id> PREMISE="a sentence" [TONE=grim] [MISSIONS=3] [SYSTEM=dragonbane] [SEED=n]'; exit 2; }
	$(SOLO_BIN) campaign new "$(ID)" --premise "$$PREMISE" --tone "$$TONE" --missions $(or $(MISSIONS),3) --system $(or $(SYSTEM),dragonbane) $(if $(SEED),--seed $(SEED))
	@$(ASK) "$(SOLO_HOME)" "Use the solo-campaign skill to write the campaign just rolled in $(ADVENTURES)/$(ID) from my premise: $$PREMISE. The repository is $(CURDIR): read docs/PACK_FORMAT.md there first. Keep to what the dice rolled (rolls.toml), write every file marked rolled, not yet written, and run make check-adventure ID=$(ID) in the repository until it is clean. Then tell me about the campaign without spoiling it."

# The next mission of a generated campaign, once the one before is done: rolled from what the
# hero did, then written by your agent.
campaign-next:
	@test -n "$$CAMPAIGN" || { echo "usage: make campaign-next CAMPAIGN=<campaign folder>"; exit 2; }
	$(SOLO_BIN) campaign next "$$CAMPAIGN"
	@$(ASK) "$(SOLO_HOME)" "Use the solo-campaign skill to write the next mission of the campaign in $$CAMPAIGN: solo campaign next has just rolled it into the campaign's adventure pack (campaign.toml there says where). The repository is $(CURDIR): read docs/PACK_FORMAT.md there first. Read what the hero did (solo -C $$CAMPAIGN history), pay off what the dice picked to come back, and run make check-adventure ID=<the adventure folder> in the repository until it is clean."

test:
	python3 -m unittest discover -s tests

qml-check:
	QT_QPA_PLATFORM=offscreen python3 tests/qml/theme_check.py $${TMPDIR:-/tmp}/oma-solorpg-theme-qml
	QT_QPA_PLATFORM=offscreen python3 tests/qml/workspace_check.py
	QT_QPA_PLATFORM=offscreen python3 tests/qml/sidebar_check.py $${TMPDIR:-/tmp}/oma-solorpg-sidebar
	QT_QPA_PLATFORM=offscreen python3 tests/qml/panel_check.py $${TMPDIR:-/tmp}/oma-solorpg-qml

# The website, as GitHub Pages serves it (.github/workflows/pages.yml publishes site/).
site:
	python3 -m http.server 8000 --directory site
