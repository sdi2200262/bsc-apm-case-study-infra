#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""
Render an emitted grader results artifact in a human-readable form.

The grader writes a results JSON document for each graded patch:
per-test pass-or-fail status, points awarded against the rubric, and
diagnostic messages. This module reads such an artifact and prints
either a one-shot summary (with optional flags for category breakdown
and per-test detail) or an interactive menu for browsing test
results during development and grading review.

Counterpart to ``cc_chat_parser/inspect.py``, which renders the
parser's metrics artifact in the same style; the two utilities share
no code but share a single mental model: an inspect tool that lives
next to the producer of the artifact it inspects.

Invocation:
    ./inspect.py <results.json>                  # interactive
    ./inspect.py <results.json> --summary        # one-shot summary
    ./inspect.py --help                          # full options
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

LINE_WIDTH = 60
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


def print_header(text: str, char: str = "=") -> None:
    """Print a section header surrounded by separator lines.

    Args:
        text: Header text to display.
        char: Character to use for the separator line.
    """
    print(f"\n{char * LINE_WIDTH}")
    print(f" {text}")
    print(f"{char * LINE_WIDTH}")


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
    print(f"  Timestamp: {meta.get('timestamp', 'N/A')}")

    print_header("SCORES", "-")

    py = scores.get("python", {})
    py_base = py.get("baseline", {})
    py_feat = py.get("feature", {})
    py_total = py.get("total", {})
    c_total = scores.get("c", {}).get("total", {})
    grand = scores.get("grand_total", {})

    print(f"  Python Baseline:  {py_base.get('score', 0):2d}/{py_base.get('max', 0):2d}")
    print(f"  Python Feature:   {py_feat.get('score', 0):2d}/{py_feat.get('max', 0):2d}")
    print(f"  Python Total:     {py_total.get('score', 0):2d}/{py_total.get('max', 0):2d}")
    print(f"  C Replica:        {c_total.get('score', 0):2d}/{c_total.get('max', 0):2d}")
    print(f"  {'-' * 25}")
    print(f"  GRAND TOTAL:      {grand.get('score', 0):2d}/{grand.get('max', 0):2d}")

    if breakdown:
        print_header("CATEGORY BREAKDOWN", "-")
        for target in ("python", "c"):
            cats = breakdown.get(target, {})
            if not cats:
                continue
            print(f"  {target.upper()}:")
            for cat, cat_scores in sorted(cats.items()):
                # Tuples in the JSON written by Scorer.to_dict round-trip
                # as two-element lists; the dict branch tolerates older
                # results files that wrote {"score","max"} mappings.
                if isinstance(cat_scores, list) and len(cat_scores) == 2:
                    print(f"    {cat:15s} {cat_scores[0]:2d}/{cat_scores[1]:2d}")
                elif isinstance(cat_scores, dict):
                    score = cat_scores.get("score", 0)
                    max_score = cat_scores.get("max", 0)
                    print(f"    {cat:15s} {score:2d}/{max_score:2d}")


def print_test(test_id: str, test_data: dict[str, Any], show_full: bool = False) -> None:
    """Print details for a single test.

    Args:
        test_id: Test identifier, used as the key in the results
            mapping (e.g. ``"P.1.4"``, ``"C.5.4"``).
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

    print(f"\n[{test_id}] {status} ({points} pts) - {category}")
    print(f"  Description: {description}")
    print(f"  Message: {truncate(message)}")

    if show_full:
        full_output = test_data.get("full_output", "")
        print("\n  Full Output:")
        print(f"  {'-' * 50}")
        for line in full_output.split("\n"):
            while len(line) > OUTPUT_LINE_WRAP:
                print(f"    {line[:OUTPUT_LINE_WRAP]}")
                line = line[OUTPUT_LINE_WRAP:]
            print(f"    {line}")


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

        print(f"  [{test_id:6s}] {status:4s} {points:5s} - {desc}")


def search_outputs(tests: dict[str, dict[str, Any]], query: str) -> None:
    """Print every test whose ``full_output`` contains ``query``.

    Args:
        tests: Mapping of test identifier to test result data.
        query: Search string. Matching is case-insensitive.
    """
    print_header(f"SEARCH RESULTS: {query}", "-")
    found = False
    query_lower = query.lower()

    for test_id, test_data in tests.items():
        full_out = test_data.get("full_output", "")
        if query_lower in full_out.lower():
            found = True
            print(f"\n  Found in [{test_id}]:")
            idx = full_out.lower().find(query_lower)
            start = max(0, idx - 50)
            end = min(len(full_out), idx + len(query) + 50)
            context = full_out[start:end]
            print(f"    ...{context}...")

    if not found:
        print("  No matches found.")


def interactive_menu(data: dict[str, Any]) -> None:
    """Run the interactive menu for browsing results.

    Args:
        data: Complete results data dictionary.
    """
    tests = data.get("tests", {})

    while True:
        print_header("RESULTS VIEWER MENU")
        print("  1. Show summary")
        print("  2. List all tests")
        print("  3. Show failed tests")
        print("  4. Show passed tests")
        print("  5. Filter by category")
        print("  6. View specific test (with full output)")
        print("  7. Search in full outputs")
        print("  q. Quit")

        choice = input("\nEnter choice: ").strip().lower()

        if choice == "q":
            print("Exiting.")
            break
        elif choice == "1":
            print_summary(data)
        elif choice == "2":
            print_header("ALL TESTS", "-")
            print_tests_list(tests)
        elif choice == "3":
            print_header("FAILED TESTS", "-")
            print_tests_list(tests, filter_passed=False)
        elif choice == "4":
            print_header("PASSED TESTS", "-")
            print_tests_list(tests, filter_passed=True)
        elif choice == "5":
            categories = get_categories(tests)
            print(f"\nAvailable categories: {', '.join(categories)}")
            cat = input("Enter category: ").strip()
            if cat:
                print_header(f"TESTS IN CATEGORY: {cat.upper()}", "-")
                print_tests_list(tests, filter_category=cat)
        elif choice == "6":
            test_ids = list(tests.keys())
            print(f"\nAvailable tests: {', '.join(test_ids)}")
            test_id = input("Enter test ID: ").strip().upper()
            if test_id in tests:
                print_test(test_id, tests[test_id], show_full=True)
            else:
                print(f"Test '{test_id}' not found.")
        elif choice == "7":
            query = input("Enter search string: ").strip()
            if query:
                search_outputs(tests, query)
        else:
            print("Invalid choice. Please try again.")

        input("\nPress Enter to continue...")


def create_parser() -> argparse.ArgumentParser:
    """Return the argparse parser configured for the inspect CLI."""
    parser = argparse.ArgumentParser(
        prog="inspect.py",
        description="CLI utility for browsing grading results JSON files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  Interactive mode (default):
    ./inspect.py results.json

  Non-interactive commands:
    ./inspect.py results.json --summary
    ./inspect.py results.json --test P.2.5
    ./inspect.py results.json --failed
    ./inspect.py results.json --passed
    ./inspect.py results.json --category course
    ./inspect.py results.json --full-output P.1.4
    ./inspect.py results.json --list-categories

  Pipe full output for processing:
    ./inspect.py results.json -o C.5.4 | python3 -m json.tool

Test IDs:
  Python: P.1.1 to P.1.10, P.2.1 to P.2.8, P.3.1 to P.3.6
  C:      C.1.1, C.1.2, C.2.1 to C.2.10, C.3.1 to C.3.8,
          C.4.1 to C.4.6, C.5.1 to C.5.4

Categories:
  protocol, course, general, build, stack, memory
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
        help="Print score summary and exit",
    )
    parser.add_argument(
        "--test", "-t",
        metavar="ID",
        help="Show details for a specific test ID (e.g., P.1.4, P.2.5, C.5.4)",
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


def main() -> int:
    """Entry point. Returns ``0`` on success, ``1`` on input errors."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.results_file.exists():
        print(f"Error: File not found: {args.results_file}", file=sys.stderr)
        return 1

    try:
        data = load_results(args.results_file)
    except json.JSONDecodeError as error:
        print(f"Error: Invalid JSON: {error}", file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    tests = data.get("tests", {})

    if args.list_categories:
        for cat in get_categories(tests):
            print(cat)
        return 0

    if args.full_output:
        test_id = args.full_output.upper()
        if test_id not in tests:
            print(f"Error: Test '{test_id}' not found", file=sys.stderr)
            print(f"Available tests: {', '.join(tests.keys())}", file=sys.stderr)
            return 1
        print(tests[test_id].get("full_output", ""))
        return 0

    if args.summary:
        print_summary(data)
        return 0

    if args.test:
        test_id = args.test.upper()
        if test_id not in tests:
            print(f"Error: Test '{test_id}' not found", file=sys.stderr)
            print(f"Available tests: {', '.join(tests.keys())}", file=sys.stderr)
            return 1
        print_test(test_id, tests[test_id], show_full=True)
        return 0

    if args.failed:
        print_header("FAILED TESTS", "-")
        print_tests_list(tests, filter_passed=False)
        return 0

    if args.passed:
        print_header("PASSED TESTS", "-")
        print_tests_list(tests, filter_passed=True)
        return 0

    if args.category:
        print_header(f"TESTS IN CATEGORY: {args.category.upper()}", "-")
        print_tests_list(tests, filter_category=args.category)
        return 0

    interactive_menu(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
