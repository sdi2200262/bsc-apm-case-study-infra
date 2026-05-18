# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
#
# Release-prep targets for the BSc APM Case Study grading environment.
#
# This environment runs the same pinned openeclass release image and
# the same mock CAS implementation as the participant testing
# environment; only the seed data and the multi-user mock CAS config
# diverge, and the CAS diverges only as far as needed to carry two
# seeded users with disjoint enrolment.
#
# Targets:
#   seed                 Regenerate seed/seed.json and mock-cas/cas-config.json from seed/seed.yaml.
#   check-openeclass-ref Assert the openeclass checkout is at the pinned ref.
#   build-images         Build the openeclass and mock CAS images.
#   save-images          Save both images to release/<image>-<arch>.tar.
#   release              Assemble the grading environment release tarball.
#   clean                Remove the release/ directory.
#   help                 Print this listing.

ARCH ?= $(shell uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
OPENECLASS_PATH ?= ../openeclass
OPENECLASS_REF ?= Release_4.3.3
RELEASE_DIR ?= release
STAGING_DIR = $(RELEASE_DIR)/staging
LICENSE_SRC ?= ../LICENSE

OPENECLASS_TAG = bsc-apm/openeclass:grader
MOCK_CAS_TAG = bsc-apm/mock-cas:grader

OPENECLASS_TAR = $(RELEASE_DIR)/openeclass-image-$(ARCH).tar
MOCK_CAS_TAR = $(RELEASE_DIR)/mock-cas-image-$(ARCH).tar
RELEASE_TARBALL = $(RELEASE_DIR)/bsc-apm-grader-env-$(ARCH).tar.gz

UV ?= uv

.PHONY: help seed check-openeclass-ref build-images save-images release clean

help:
	@echo "Available targets:"
	@echo "  seed                 regenerate seed/seed.json and mock-cas/cas-config.json"
	@echo "  check-openeclass-ref assert the openeclass checkout is at $(OPENECLASS_REF)"
	@echo "  build-images         build openeclass and mock CAS images"
	@echo "  save-images          save built images to release/*.tar"
	@echo "  release              assemble $(RELEASE_TARBALL)"
	@echo "  clean                remove $(RELEASE_DIR)/"
	@echo ""
	@echo "Variables:"
	@echo "  ARCH=$(ARCH)"
	@echo "  OPENECLASS_PATH=$(OPENECLASS_PATH)"
	@echo "  OPENECLASS_REF=$(OPENECLASS_REF)"
	@echo "  RELEASE_DIR=$(RELEASE_DIR)"

seed:
	$(UV) run --no-project seed/generate_seed_json.py
	$(UV) run --no-project seed/generate_cas_config.py

check-openeclass-ref:
	@actual=$$(git -C $(OPENECLASS_PATH) rev-parse HEAD); \
	expected=$$(git -C $(OPENECLASS_PATH) rev-parse $(OPENECLASS_REF)); \
	if [ "$$actual" != "$$expected" ]; then \
	  echo "openeclass at $(OPENECLASS_PATH) is not at $(OPENECLASS_REF)"; \
	  echo "  expected: $$expected"; \
	  echo "  actual:   $$actual"; \
	  echo "run: git -C $(OPENECLASS_PATH) checkout $(OPENECLASS_REF)"; \
	  exit 1; \
	fi

build-images: check-openeclass-ref
	docker build -t $(OPENECLASS_TAG) $(OPENECLASS_PATH)
	docker build -t $(MOCK_CAS_TAG) mock-cas/

save-images: build-images
	@mkdir -p $(RELEASE_DIR)
	docker save $(OPENECLASS_TAG) -o $(OPENECLASS_TAR)
	docker save $(MOCK_CAS_TAG) -o $(MOCK_CAS_TAR)

release: seed save-images
	@mkdir -p $(STAGING_DIR)/seed
	cp README.md $(LICENSE_SRC) install compose.yaml $(STAGING_DIR)/
	cp -r scripts $(STAGING_DIR)/
	cp seed/seed.php seed/seed.json $(STAGING_DIR)/seed/
	cp $(OPENECLASS_TAR) $(MOCK_CAS_TAR) $(STAGING_DIR)/
	tar -czf $(RELEASE_TARBALL) -C $(STAGING_DIR) .
	rm -rf $(STAGING_DIR)
	@echo "release tarball: $(RELEASE_TARBALL)"

clean:
	rm -rf $(RELEASE_DIR)
