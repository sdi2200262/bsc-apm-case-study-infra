# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
#
# Grader-side maintenance targets.
#
# The grader vendors a pinned snapshot of the testing environment's
# seed.yaml. The two targets below keep that snapshot in lock-step
# with the upstream source at bsc-apm-case-study-task/seed/seed.yaml,
# pinned by default to the amd64 release tag so reproducibility
# tracks the released testing-environment surface rather than an
# arbitrary main commit. Override REF to pin to a different tag or
# commit SHA.

REF ?= bsc-apm-case-study-task
SEED_URL := https://raw.githubusercontent.com/sdi2200262/bsc-apm-case-study-task/$(REF)/seed/seed.yaml
SEED_FILE := seed.yaml

.PHONY: help refresh-seed check-seed

help:
	@echo "grader/Makefile targets"
	@echo ""
	@echo "  refresh-seed   Overwrite the seed body from REF (default: $(REF))."
	@echo "                 The local header comment block is preserved."
	@echo "  check-seed     Fetch REF and diff the body against the local"
	@echo "                 mirror without modifying anything; exit non-zero"
	@echo "                 on drift."
	@echo ""
	@echo "Override the pin via REF=<tag-or-sha> on the command line:"
	@echo "  make check-seed REF=main"
	@echo "  make refresh-seed REF=v1.2.3"

refresh-seed:
	@tmp=$$(mktemp) && \
	  trap 'rm -f "$$tmp" "$$tmp.body" "$$tmp.header"' EXIT && \
	  curl -fsSL "$(SEED_URL)" -o "$$tmp" && \
	  awk '!found && /^[^#]/ && !/^[[:space:]]*$$/ {found=1} found {print}' "$$tmp" > "$$tmp.body" && \
	  awk '!found && /^[^#]/ && !/^[[:space:]]*$$/ {found=1} !found {print}' "$(SEED_FILE)" > "$$tmp.header" && \
	  cat "$$tmp.header" "$$tmp.body" > "$(SEED_FILE)" && \
	  echo "refresh-seed: $(SEED_FILE) updated from REF=$(REF) (local header preserved)"

check-seed:
	@tmp_up=$$(mktemp) && \
	  tmp_local_body=$$(mktemp) && \
	  tmp_up_body=$$(mktemp) && \
	  trap 'rm -f "$$tmp_up" "$$tmp_local_body" "$$tmp_up_body"' EXIT && \
	  curl -fsSL "$(SEED_URL)" -o "$$tmp_up" && \
	  awk '!found && /^[^#]/ && !/^[[:space:]]*$$/ {found=1} found {print}' "$$tmp_up" > "$$tmp_up_body" && \
	  awk '!found && /^[^#]/ && !/^[[:space:]]*$$/ {found=1} found {print}' "$(SEED_FILE)" > "$$tmp_local_body" && \
	  if diff -u "$$tmp_local_body" "$$tmp_up_body" >/dev/null; then \
	    echo "check-seed: $(SEED_FILE) body matches REF=$(REF)"; \
	  else \
	    echo "check-seed: $(SEED_FILE) drifts from REF=$(REF); diff (local vs upstream):"; \
	    diff -u "$$tmp_local_body" "$$tmp_up_body" || true; \
	    exit 1; \
	  fi
