# Grading environment

A self-contained openeclass and mock CAS, built and released from this
repository, that the grader asserts a participant's submission against.

## Overview

The environment runs the same pinned openeclass release as the
participant package (`Release_4.3.3`, the `gunet/openeclass` build) and
the same mock CAS implementation. Only the seed and the CAS user set
diverge, and the CAS diverges only as far as needed to carry two users.
That richer two-user seed is what makes it the grader's environment
rather than the participant's single-user mock.

## Quick start

```bash
./install         # one-time setup
./scripts/up      # bring the stack up (openeclass + mock CAS + MariaDB)
./scripts/status  # health check
./scripts/reset   # the nuclear reset the grader invokes per run
```

A healthy bring-up has both seeded users authenticate end to end and the
two-user data render (day-0 CS101 relative, the rest absolute). The
grader's no-patch baseline against this environment scores 10/100 (the
Python baseline rows; the unmodified upstream ships no `c-replica/`, so
every C row is zero).

## Seed and divergence

`seed/seed.yaml` is the single source of truth. It seeds two users with
disjoint enrolment, `student_courses` (CS101, PHYS150, MATH201) and
`student_general` (BIO110), plus two system announcements; the mock CAS
authenticates that `users` list and returns each user's own attributes.
Dates anchor at seed-apply time, so a volume-dropping reset re-anchors
them. The disjoint enrolment is load-bearing, because the one
relative-date announcement lives only in a course `student_general` is
not enrolled in, so it can never reach a general response.

`seed/seed.json` and `mock-cas/cas-config.json` are generated from
`seed/seed.yaml` by the two `seed/generate_*.py` scripts; never
hand-edit them. `make check-openeclass-ref` fails loudly if the
openeclass checkout drifts off the pin.

## Build and release

`make seed` regenerates the two JSON files. `make release` assembles
`release/bsc-apm-grader-env-<arch>.tar.gz` (needs a `gunet/openeclass`
checkout at `Release_4.3.3`, default `../openeclass`, override with
`OPENECLASS_PATH=`). `.github/workflows/release-{amd64,arm64}.yml` build
and publish on `workflow_dispatch` to the fixed-name private tags
`grader-env-amd64` and `grader-env-arm64` (delete-then-publish, so the
tag tracks the built commit; an authenticated `gh` is needed to
download).

## Related

- [../grader/README.md](../grader/README.md): the grader that runs against this environment.
- [bsc-apm-case-study-task](https://github.com/sdi2200262/bsc-apm-case-study-task): the participant package whose single-user testing environment this one parallels but seeds differently.
