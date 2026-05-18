# Grading environment

A self-contained openeclass + mock CAS environment built and released
from this repository for the grader. 

## Invariant

Same pinned openeclass release as the participant package
(`Release_4.3.3`, same `gunet/openeclass` build), same mock CAS
implementation. Only the seed and the CAS user set diverge, and the
CAS diverges solely to let the seed carry two users:

- `seed/seed.yaml` (single source of truth) seeds two users with
  disjoint enrolment: `student_courses` (CS101, PHYS150, MATH201) and
  `student_general` (BIO110), plus two system announcements. Dates
  anchor at seed-apply time, so a volume-dropping reset re-anchors them.
- `mock-cas` authenticates a `users` list (`config.py`/`handlers.py`)
  and returns each user's own attributes (`rendering.py`).

`seed/seed.json` and `mock-cas/cas-config.json` are generated from
`seed/seed.yaml` by the two `seed/generate_*.py` scripts; never
hand-edit them. `make check-openeclass-ref` fails loudly if the
openeclass checkout drifts off the pin.

## Build and release

`make seed` regenerates the two JSON files. `make release` assembles
`release/bsc-apm-grader-env-<arch>.tar.gz` (needs a `gunet/openeclass`
checkout at `Release_4.3.3`; default `../openeclass`, override
`OPENECLASS_PATH=`). `.github/workflows/release-{amd64,arm64}.yml`
build and publish on `workflow_dispatch` to the fixed-name private
tags `grader-env-amd64` / `grader-env-arm64` (delete-then-publish, so
the tag tracks the built commit; an authenticated `gh` is needed to
download).

## Bring-up

`./install` then `./scripts/up` then `./scripts/status`.
`./scripts/reset` is the nuclear reset the grader invokes per run.
Validation: both seeded users authenticate end to end and the two-user
data renders (day-0 CS101 relative, the rest absolute). The no-patch
baseline score is Forthcoming: the current grader logic is single-user
and the two-principal redesign is a separate workstream.
