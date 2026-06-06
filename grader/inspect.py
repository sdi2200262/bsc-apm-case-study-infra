#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Render an emitted grader results artifact in a human-readable form.

The grader writes a results JSON document for each graded patch:
per-test pass-or-fail status, points awarded against the rubric, and
diagnostic messages. This module reads such an artifact and prints a
one-shot view selected by flags: the score summary (the default), a
single test's detail, a filtered list, the available categories, or one
test's raw ``full_output`` for piping. It is non-interactive and runs to
completion without prompting.

A sibling utility under ``../parser/`` renders the parser's metrics
artifact in the same style.

Invocation:
    ./inspect.py <results.json>                  # score summary
    ./inspect.py <results.json> --test P.2.5     # one test's detail
    ./inspect.py <results.json> --failed         # filtered list
    ./inspect.py --help                          # full options
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import log

MESSAGE_TRUNCATE_LIMIT = 200
OUTPUT_LINE_WRAP = 100


def load_results(filepath: Path) -> dict[str, Any]:
    """Load and parse a results JSON file.

    Args:
        filepath: Path to the JSON results file.

    Returns:
        Parsed JSON data as a dictionary.

    Raises:
        json.JSONDecodeError: When the file contains invalid JSON.
        FileNotFoundError: When the file does not exist.
    """
    with open(filepath, "r", encoding="utf-8") as source:
        return json.load(source)


def print_header(text: str) -> None:
    """Print a section header framed by separator rules.

    Args:
        text: Header text to display; rendered upper-cased.
    """
    log.blank()
    log.line()
    log.info(text.upper())
    log.line()


def truncate(text: str, limit: int = MESSAGE_TRUNCATE_LIMIT) -> str:
    """Return ``text`` truncated to ``limit`` characters with an ellipsis suffix.

    Args:
        text: Text to truncate.
        limit: Maximum length before truncation.

    Returns:
        Original text when within ``limit``; truncated text with a
        three-character ellipsis suffix otherwise.
    """
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def format_status(passed: bool) -> str:
    """Return ``"PASS"`` when ``passed`` is true, ``"FAIL"`` otherwise."""
    return "PASS" if passed else "FAIL"


def format_points(earned: int, total: int) -> str:
    """Return points as an ``"earned/total"`` string."""
    return f"{earned}/{total}"


def get_categories(tests: dict[str, dict[str, Any]]) -> list[str]:
    """Return the sorted list of unique categories across all tests.

    Args:
        tests: Mapping of test identifier to test result data.

    Returns:
        Sorted list of category labels found in the test results,
        with ``"unknown"`` substituted for any test missing a label.
    """
    categories: set[str] = set()
    for test_data in tests.values():
        categories.add(test_data.get("category", "unknown"))
    return sorted(categories)


def print_summary(data: dict[str, Any]) -> None:
    """Print the score summary including the category breakdown.

    Args:
        data: Complete results data dictionary as written by the
            grader's ``Scorer.to_dict``.
    """
    meta = data.get("metadata", {})
    scores = data.get("scores", {})
    breakdown = data.get("category_breakdown", {})

    print_header(f"RESULTS: {meta.get('patch_name', 'Unknown')}")
    log.info(f"Timestamp: {meta.get('timestamp', 'N/A')}")

    print_header("SCORES")

    py = scores.get("python", {})
    py_base = py.get("baseline", {})
    py_feat = py.get("feature", {})
    py_total = py.get("total", {})
    c_total = scores.get("c", {}).get("total", {})
    grand = scores.get("grand_total", {})

    log.info(f"Python Baseline:  {py_base.get('score', 0):2d}/{py_base.get('max', 0):2d}")
    log.info(f"Python Feature:   {py_feat.get('score', 0):2d}/{py_feat.get('max', 0):2d}")
    log.info(f"Python Total:     {py_total.get('score', 0):2d}/{py_total.get('max', 0):2d}")
    log.info(f"C Replica:        {c_total.get('score', 0):2d}/{c_total.get('max', 0):2d}")
    log.line()
    log.info(f"GRAND TOTAL:      {grand.get('score', 0):2d}/{grand.get('max', 0):2d}")

    if breakdown:
        print_header("CATEGORY BREAKDOWN")
        for target in ("python", "c"):
            cats = breakdown.get(target, {})
            if not cats:
                continue
            log.info(f"{target.upper()}:")
            for cat, cat_scores in sorted(cats.items()):
                # The category scores round-trip from JSON as a
                # [score, max] list; the dict branch also accepts a
                # {"score": ..., "max": ...} mapping written by a
                # results file in that alternative shape.
                if isinstance(cat_scores, list) and len(cat_scores) == 2:
                    log.info(f"  {cat:15s} {cat_scores[0]:2d}/{cat_scores[1]:2d}")
                elif isinstance(cat_scores, dict):
                    score = cat_scores.get("score", 0)
                    max_score = cat_scores.get("max", 0)
                    log.info(f"  {cat:15s} {score:2d}/{max_score:2d}")


def print_test(test_id: str, test_data: dict[str, Any], show_full: bool = False) -> None:
    """Print details for a single test.

    Args:
        test_id: Test identifier, used as the key in the results
            mapping (e.g. ``"P.1.4"``, ``"C.5.3"``).
        test_data: Test result data for ``test_id``.
        show_full: When ``True``, prints the complete ``full_output``
            field with line wrapping; otherwise prints only the short
            message and metadata.
    """
    passed = test_data.get("passed", False)
    points_earned = test_data.get("points_earned", 0)
    points_total = test_data.get("points", 0)
    category = test_data.get("category", "unknown")
    description = test_data.get("description", "No description")
    message = test_data.get("message", "")

    status = format_status(passed)
    points = format_points(points_earned, points_total)

    log.blank()
    log.info(f"{test_id} {status} ({points} pts) - {category}")
    log.info(f"Description: {description}")
    log.info(f"Message: {truncate(message)}")

    if show_full:
        full_output = test_data.get("full_output", "")
        log.blank()
        log.info("Full Output:")
        log.line()
        for output_line in full_output.split("\n"):
            while len(output_line) > OUTPUT_LINE_WRAP:
                log.info(f"  {output_line[:OUTPUT_LINE_WRAP]}")
                output_line = output_line[OUTPUT_LINE_WRAP:]
            log.info(f"  {output_line}")


def print_tests_list(
    tests: dict[str, dict[str, Any]],
    filter_passed: bool | None = None,
    filter_category: str | None = None,
) -> None:
    """Print a flat list of tests with optional pass/fail or category filtering.

    Args:
        tests: Mapping of test identifier to test result data.
        filter_passed: When set, only emit tests whose pass/fail
            status matches.
        filter_category: When set, only emit tests in this category.
            Comparison is case-insensitive.
    """
    for test_id, test_data in tests.items():
        if filter_passed is not None and test_data.get("passed") != filter_passed:
            continue
        if filter_category is not None:
            if test_data.get("category", "").lower() != filter_category.lower():
                continue

        status = format_status(test_data.get("passed", False))
        points = format_points(
            test_data.get("points_earned", 0),
            test_data.get("points", 0),
        )
        desc = test_data.get("description", "")[:40]

        log.info(f"{test_id:6s} {status:4s} {points:5s} - {desc}")


def create_parser() -> argparse.ArgumentParser:
    """Return the argparse parser configured for the inspect CLI."""
    parser = argparse.ArgumentParser(
        prog="inspect.py",
        description="CLI utility for browsing grading results JSON files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  Score summary (default):
    ./inspect.py results.json

  Other one-shot views:
    ./inspect.py results.json --summary
    ./inspect.py results.json --test P.2.5
    ./inspect.py results.json --failed
    ./inspect.py results.json --passed
    ./inspect.py results.json --category course
    ./inspect.py results.json --full-output P.1.4
    ./inspect.py results.json --list-categories

  Pipe full output for processing:
    ./inspect.py results.json -o C.5.3 | python3 -m json.tool

Test IDs:
  Python: P.1.1 to P.1.11, P.2.1 to P.2.9, P.3.1 to P.3.7
  C:      C.1.1 to C.1.6, C.2.1 to C.2.12, C.3.1 to C.3.9,
          C.4.1 to C.4.7, C.5.1 to C.5.3
  C .mem: <C.2.3..C.2.12>.mem, <C.3.1..C.3.9>.mem, <C.4.1..C.4.7>.mem

Categories:
  protocol, course, general, build, stack, config, memory
        """,
    )

    parser.add_argument(
        "results_file",
        type=Path,
        help="Path to the results JSON file",
    )
    parser.add_argument(
        "--summary", "-s",
        action="store_true",
        help="Print score summary and exit (the default when no view flag is given)",
    )
    parser.add_argument(
        "--test", "-t",
        metavar="ID",
        help="Show details for a specific test ID (e.g., P.1.4, P.2.5, C.5.3)",
    )
    parser.add_argument(
        "--failed", "-f",
        action="store_true",
        help="List all failed tests",
    )
    parser.add_argument(
        "--passed", "-p",
        action="store_true",
        help="List all passed tests",
    )
    parser.add_argument(
        "--category", "-c",
        metavar="CAT",
        help="Filter tests by category (protocol, course, general, build, stack, memory)",
    )
    parser.add_argument(
        "--full-output", "-o",
        metavar="ID",
        help="Print only the full_output field for a test (useful for piping)",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="List available test categories and exit",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI: parse args, load the results file, dispatch the action.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: ``0`` on success or any informational
        path (summary, list, filter, full output); ``1`` when the
        results file is missing, invalid JSON, unreadable, or names a
        test ID not present in the file.
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.results_file.exists():
        log.error(f"File not found: {args.results_file}")
        return 1

    try:
        data = load_results(args.results_file)
    except json.JSONDecodeError as error:
        log.error(f"Invalid JSON: {error}")
        return 1
    except OSError as error:
        log.error(str(error))
        return 1

    tests = data.get("tests", {})

    if args.list_categories:
        # Raw, one-per-line output for scripting; not decorated.
        for cat in get_categories(tests):
            print(cat)
        return 0

    if args.full_output:
        test_id = args.full_output.upper()
        if test_id not in tests:
            log.error(f"Test '{test_id}' not found")
            log.error(f"Available tests: {', '.join(tests.keys())}")
            return 1
        # Raw field dump for piping (e.g. into json.tool); not decorated.
        print(tests[test_id].get("full_output", ""))
        return 0

    if args.test:
        test_id = args.test.upper()
        if test_id not in tests:
            log.error(f"Test '{test_id}' not found")
            log.error(f"Available tests: {', '.join(tests.keys())}")
            return 1
        print_test(test_id, tests[test_id], show_full=True)
        return 0

    if args.failed:
        print_header("FAILED TESTS")
        print_tests_list(tests, filter_passed=False)
        return 0

    if args.passed:
        print_header("PASSED TESTS")
        print_tests_list(tests, filter_passed=True)
        return 0

    if args.category:
        print_header(f"TESTS IN CATEGORY: {args.category.upper()}")
        print_tests_list(tests, filter_category=args.category)
        return 0

    # Default and explicit --summary: the one-shot score summary.
    print_summary(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
