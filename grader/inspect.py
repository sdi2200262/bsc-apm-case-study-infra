# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) BSc APM Case Study 2025-2026
"""Render an emitted grader results artefact in a human-readable form.

The grader writes a results JSON document for each graded patch: each
row's verdict, credited points, and diagnostic messages. The static
rubric metadata (each row's point maximum, category, and description)
lives once in the schema artefact, not on the rows, so every
interpretive view joins the schema by test id; only the raw
``--full-output`` dump reads a row without it. This module prints a
one-shot view selected by flags: the score summary (the default), a
single test's detail, a filtered list, the available categories, or one
test's raw ``full_output`` for piping. It is non-interactive and runs to
completion without prompting.

A sibling utility under ``../parser/`` renders the parser's metrics
artefact in the same style, joining ``parser_schema.json`` the same way.

Invocation (every view but --full-output needs the schema):
    python -m grader.inspect <grader_results.json> --schema <grader_schema.json>
    python -m grader.inspect <grader_results.json> --schema <grader_schema.json> --test P.2.5
    python -m grader.inspect <grader_results.json> --full-output P.1.4
    python -m grader.inspect --help
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import log
from .json_io import read_json

MESSAGE_TRUNCATE_LIMIT = 200
OUTPUT_LINE_WRAP = 100


def _load_results(filepath: Path) -> dict[str, Any]:
    """Load and parse a results JSON file.

    Args:
        filepath: Path to the JSON results file.

    Returns:
        Parsed JSON data as a dictionary.

    Raises:
        json.JSONDecodeError: When the file contains invalid JSON.
        FileNotFoundError: When the file does not exist.
    """
    return read_json(filepath)


def _load_schema(filepath: Path) -> dict[str, Any]:
    """Load and parse the rubric schema JSON file.

    Args:
        filepath: Path to the ``grader_schema.json`` file.

    Returns:
        Parsed schema data: a mapping of test id to rubric metadata.

    Raises:
        json.JSONDecodeError: When the file contains invalid JSON.
        FileNotFoundError: When the file does not exist.
    """
    return read_json(filepath)


def _merge_schema(
    tests: dict[str, dict[str, Any]], schema: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Join each result row with its rubric schema entry.

    The static rubric fields (``points``, ``category``, ``target``,
    ``description``, ``bucket``) come from ``schema``; the per-submission
    outcome fields on the row take precedence on any key collision.

    Args:
        tests: Mapping of test id to per-row outcome data.
        schema: Mapping of test id to rubric metadata.

    Returns:
        The rows enriched with their schema metadata, keyed by test id.
    """
    return {test_id: {**schema.get(test_id, {}), **row} for test_id, row in tests.items()}


def _print_header(text: str) -> None:
    """Print a section header framed by separator rules.

    Args:
        text: Header text to display; rendered upper-cased.
    """
    log.blank()
    log.line()
    log.info(text.upper())
    log.line()


def _truncate(text: str, limit: int = MESSAGE_TRUNCATE_LIMIT) -> str:
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


def _format_status(verdict: str) -> str:
    """Return the short status label for a row's ``verdict``.

    Args:
        verdict: The per-row verdict (``"passed"``, ``"partial"``, or
            ``"failed"``).

    Returns:
        ``"PASS"`` for a pass, ``"PART"`` for a partial, ``"FAIL"``
        otherwise.
    """
    if verdict == "passed":
        return "PASS"
    if verdict == "partial":
        return "PART"
    return "FAIL"


def _format_number(value: float) -> str:
    """Return ``value`` as an integer string when whole, else two decimals."""
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"


def _format_points(earned: float, total: float) -> str:
    """Return points as an ``"earned/total"`` string, decimals only when fractional."""
    return f"{_format_number(earned)}/{_format_number(total)}"


def _get_categories(tests: dict[str, dict[str, Any]]) -> list[str]:
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


def _node_points(node: dict[str, Any]) -> str:
    """Return a score node's credited total over its maximum as ``"total/max"``."""
    return _format_points(node.get("total", 0), node.get("max", 0))


def _category_breakdown(tests: dict[str, dict[str, Any]]) -> dict[str, dict[str, list[float]]]:
    """Recompute the per-target, per-category score view from the test rows.

    The grader persists no ``category_breakdown`` block, so this rebuilds
    it from the schema-joined rows: each row is assigned to the Python or
    C target by its identifier prefix (``"P"`` or ``"C"``), and its
    credited and maximum points accumulate under its category. The
    ``category`` and maximum ``points`` come from the joined schema.

    Args:
        tests: Mapping of test identifier to schema-joined row data.

    Returns:
        ``{"python": {category: [earned, max]}, "c": {...}}``.
    """
    breakdown: dict[str, dict[str, list[float]]] = {"python": {}, "c": {}}
    for test_id, row in tests.items():
        target = "python" if test_id.upper().startswith("P") else "c"
        category = row.get("category", "unknown")
        entry = breakdown[target].setdefault(category, [0, 0])
        entry[0] += row.get("points_earned", 0)
        entry[1] += row.get("points", 0)
    return breakdown


def _print_summary(data: dict[str, Any], tests: dict[str, dict[str, Any]]) -> None:
    """Print the score summary including the recomputed category breakdown.

    Args:
        data: Complete results data dictionary as written by the
            grader's ``Scorer.to_dict`` (metadata and score nodes).
        tests: The schema-joined rows, used for the category breakdown.
    """
    meta = data.get("metadata", {})
    scores = data.get("scores", {})

    _print_header(f"RESULTS: {meta.get('patch_name', 'Unknown')}")
    log.info(f"Timestamp: {meta.get('timestamp', 'N/A')}")

    _print_header("SCORES")

    py = scores.get("python", {})
    py_base = py.get("baseline", {})
    py_feat = py.get("feature", {})
    c = scores.get("c", {})

    log.info(f"Python Baseline:  {_node_points(py_base)}")
    log.info(f"Python Feature:   {_node_points(py_feat)}")
    log.info(f"Python Total:     {_node_points(py)}")
    log.info(f"C Replica:        {_node_points(c)}")
    log.line()
    log.info(f"GRAND TOTAL:      {_node_points(scores)}")
    strict = scores.get("total_strict", 0)
    partial = scores.get("total_partial", 0)
    log.info(f"  strict {_format_number(strict)}, partial {_format_number(partial)}")

    _print_header("CATEGORY BREAKDOWN")
    breakdown = _category_breakdown(tests)
    for target in ("python", "c"):
        cats = breakdown.get(target, {})
        if not cats:
            continue
        log.info(f"{target.upper()}:")
        for cat, (earned, cat_max) in sorted(cats.items()):
            log.info(f"  {cat:15s} {_format_points(earned, cat_max)}")


def _print_test(test_id: str, test_data: dict[str, Any], show_full: bool = False) -> None:
    """Print details for a single test.

    Args:
        test_id: Test identifier, used as the key in the results
            mapping (e.g. ``"P.1.4"``, ``"C.5.3"``).
        test_data: Test result data for ``test_id``.
        show_full: When ``True``, prints the complete ``full_output``
            field with line wrapping; otherwise prints only the short
            message and metadata.
    """
    verdict = test_data.get("verdict", "failed")
    points_earned = test_data.get("points_earned", 0)
    points_total = test_data.get("points", 0)
    category = test_data.get("category", "unknown")
    description = test_data.get("description", "No description")
    message = test_data.get("message", "")

    status = _format_status(verdict)
    points = _format_points(points_earned, points_total)

    log.blank()
    log.info(f"{test_id} {status} ({points} pts) - {category}")
    log.info(f"Description: {description}")
    similarity = test_data.get("similarity")
    if similarity is not None:
        log.info(f"Similarity: {similarity:.3f} (partial credit)")
    log.info(f"Message: {_truncate(message)}")

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


def _print_tests_list(
    tests: dict[str, dict[str, Any]],
    filter_passed: bool | None = None,
    filter_category: str | None = None,
) -> None:
    """Print a flat list of tests with optional pass/fail or category filtering.

    Args:
        tests: Mapping of test identifier to test result data.
        filter_passed: When set, only emit tests whose passed/not-passed
            status matches; a partial row counts as not passed.
        filter_category: When set, only emit tests in this category.
            Comparison is case-insensitive.
    """
    for test_id, test_data in tests.items():
        is_passed = test_data.get("verdict") == "passed"
        if filter_passed is not None and is_passed != filter_passed:
            continue
        if (
            filter_category is not None
            and test_data.get("category", "").lower() != filter_category.lower()
        ):
            continue

        status = _format_status(test_data.get("verdict", "failed"))
        points = _format_points(
            test_data.get("points_earned", 0),
            test_data.get("points", 0),
        )
        desc = test_data.get("description", "")[:40]

        log.info(f"{test_id:6s} {status:4s} {points:5s} - {desc}")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI: parse args, load the results file, dispatch the action.

    Args:
        argv: Optional argument list; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit code: ``0`` on success or any informational
        path (summary, list, filter, full output); ``1`` when the
        results or schema file is missing, invalid JSON, unreadable,
        names a test ID not present, or an interpretive view is
        requested without the rubric schema.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.results_file.exists():
        log.error(f"File not found: {args.results_file}")
        return 1

    try:
        data = _load_results(args.results_file)
    except json.JSONDecodeError as error:
        log.error(f"Invalid JSON: {error}")
        return 1
    except OSError as error:
        log.error(str(error))
        return 1

    tests = data.get("tests", {})

    # The raw full_output dump is the one view that reads a row without
    # any rubric metadata, so it needs no schema.
    if args.full_output:
        test_id = args.full_output.upper()
        if test_id not in tests:
            log.error(f"Test '{test_id}' not found")
            log.error(f"Available tests: {', '.join(tests.keys())}")
            return 1
        # Raw field dump for piping (e.g. into json.tool); not decorated.
        print(tests[test_id].get("full_output", ""))
        return 0

    # Every other view interprets the rows against the rubric schema; the
    # rows carry only outcomes, so the schema is required, not optional.
    if args.schema_file is None:
        log.error(
            "this view needs the rubric schema; pass --schema grader_schema.json "
            "(emit it with 'python -m grader --schema')"
        )
        return 1
    if not args.schema_file.exists():
        log.error(f"Schema file not found: {args.schema_file}")
        return 1
    try:
        schema = _load_schema(args.schema_file)
    except json.JSONDecodeError as error:
        log.error(f"Invalid JSON: {error}")
        return 1
    except OSError as error:
        log.error(str(error))
        return 1

    merged = _merge_schema(tests, schema)

    if args.list_categories:
        # Raw, one-per-line output for scripting; not decorated.
        for cat in _get_categories(merged):
            print(cat)
        return 0

    if args.test:
        test_id = args.test.upper()
        if test_id not in merged:
            log.error(f"Test '{test_id}' not found")
            log.error(f"Available tests: {', '.join(merged.keys())}")
            return 1
        _print_test(test_id, merged[test_id], show_full=True)
        return 0

    if args.failed:
        _print_header("FAILED TESTS")
        _print_tests_list(merged, filter_passed=False)
        return 0

    if args.passed:
        _print_header("PASSED TESTS")
        _print_tests_list(merged, filter_passed=True)
        return 0

    if args.category:
        _print_header(f"TESTS IN CATEGORY: {args.category.upper()}")
        _print_tests_list(merged, filter_category=args.category)
        return 0

    # Default and explicit --summary: the one-shot score summary.
    _print_summary(data, merged)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Return the argparse parser configured for the inspect CLI."""
    parser = argparse.ArgumentParser(
        prog="python -m grader.inspect",
        description="CLI utility for browsing grading results JSON files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  Score summary (default):
    python -m grader.inspect grader_results.json --schema grader_schema.json

  Other one-shot views:
    python -m grader.inspect grader_results.json --schema grader_schema.json --summary
    python -m grader.inspect grader_results.json --schema grader_schema.json --test P.2.5
    python -m grader.inspect grader_results.json --schema grader_schema.json --failed
    python -m grader.inspect grader_results.json --schema grader_schema.json --passed
    python -m grader.inspect grader_results.json --schema grader_schema.json --category course
    python -m grader.inspect grader_results.json --schema grader_schema.json --list-categories

  Raw full_output for piping (no schema needed):
    python -m grader.inspect grader_results.json --full-output P.1.4
    python -m grader.inspect grader_results.json -o C.5.3 | python3 -m json.tool

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
        "--schema",
        dest="schema_file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to grader_schema.json; required for every view except --full-output",
    )
    parser.add_argument(
        "--summary",
        "-s",
        action="store_true",
        help="Print score summary and exit (the default when no view flag is given)",
    )
    parser.add_argument(
        "--test",
        "-t",
        metavar="ID",
        help="Show details for a specific test ID (e.g., P.1.4, P.2.5, C.5.3)",
    )
    parser.add_argument(
        "--failed",
        "-f",
        action="store_true",
        help="List all failed tests",
    )
    parser.add_argument(
        "--passed",
        "-p",
        action="store_true",
        help="List all passed tests",
    )
    parser.add_argument(
        "--category",
        "-c",
        metavar="CAT",
        help="Filter tests by category (protocol, course, general, build, stack, memory)",
    )
    parser.add_argument(
        "--full-output",
        "-o",
        metavar="ID",
        help="Print only the full_output field for a test (useful for piping)",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="List available test categories and exit",
    )

    return parser


if __name__ == "__main__":
    sys.exit(main())
