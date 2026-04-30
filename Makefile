# Release-prep targets for the BSc APM Case Study participant package.
#
# Targets:
#   participant-guide   Build the participant guide PDF.
#   participant-package Assemble the release zip at release/participant-package.zip.
#   clean               Remove the release/ directory and LaTeX build artefacts.
#   help                Print this listing.

RELEASE_DIR ?= release
STAGING_DIR = $(RELEASE_DIR)/staging
RELEASE_ZIP = $(RELEASE_DIR)/participant-package.zip

GUIDE_DIR = participant/guide
GUIDE_TEX = participant-guide-cc.tex
GUIDE_PDF = $(GUIDE_DIR)/participant-guide-cc.pdf

TASK_DIR = participant/task
SCRIPTS_DIR = participant/scripts
SKILLS_DIR = participant/skills

LATEXMK ?= latexmk

.PHONY: help participant-guide participant-package clean

help:
	@echo "Available targets:"
	@echo "  participant-guide    build $(GUIDE_PDF)"
	@echo "  participant-package  assemble $(RELEASE_ZIP)"
	@echo "  clean                remove $(RELEASE_DIR)/ and LaTeX build artefacts"

participant-guide:
	cd $(GUIDE_DIR) && $(LATEXMK) -pdf $(GUIDE_TEX)

participant-package: participant-guide
	rm -rf $(STAGING_DIR)
	mkdir -p $(STAGING_DIR)/participant-package/task
	mkdir -p $(STAGING_DIR)/participant-package/scripts
	cp $(GUIDE_PDF) $(STAGING_DIR)/participant-package/
	cp $(TASK_DIR)/PRD.md $(STAGING_DIR)/participant-package/task/
	cp $(TASK_DIR)/PROMPT.md $(STAGING_DIR)/participant-package/task/
	cp $(TASK_DIR)/README.txt $(STAGING_DIR)/participant-package/task/
	cp $(SCRIPTS_DIR)/list-chats.py $(STAGING_DIR)/participant-package/scripts/
	cp $(SCRIPTS_DIR)/collect-chats.py $(STAGING_DIR)/participant-package/scripts/
	cp $(SCRIPTS_DIR)/reset-chats.py $(STAGING_DIR)/participant-package/scripts/
	mkdir -p $(STAGING_DIR)/participant-package/.claude
	cp -r $(SKILLS_DIR) $(STAGING_DIR)/participant-package/.claude/skills
	rm -f $(RELEASE_ZIP)
	cd $(STAGING_DIR) && zip -r ../$(notdir $(RELEASE_ZIP)) participant-package
	rm -rf $(STAGING_DIR)
	@echo "wrote $(RELEASE_ZIP)"

clean:
	rm -rf $(RELEASE_DIR)
	cd $(GUIDE_DIR) && $(LATEXMK) -C
