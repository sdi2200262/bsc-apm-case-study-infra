#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Results Viewer - CLI utility for browsing grading results JSON files.

Provides both command-line argument mode for scripted access and interactive
menu mode for human exploration of detailed test results.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# Output formatting constants
LINE_WIDTH = 60
MESSAGE_TRUNCATE_LIMIT = 200
OUTPUT_LINE_WRAP = 100


def load_results(filepath: Path) -> Dict[str, Any]:
    """
    Load and parse results JSON file.
    
    Args:
        filepath: Path to the JSON results file.
    
    Returns:
        Parsed JSON data as dictionary.
    
    Raises:
        json.JSONDecodeError: If file contains invalid JSON.
        FileNotFoundError: If file does not exist.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def print_header(text: str, char: str = "=") -> None:
    """
    Print a section header with separator lines.
    
    Args:
        text: Header text to display.
        char: Character to use for separator line.
    """
    print(f"\n{char * LINE_WIDTH}")
    print(f" {text}")
    print(f"{char * LINE_WIDTH}")


def truncate(text: str, limit: int = MESSAGE_TRUNCATE_LIMIT) -> str:
    """
    Truncate text to specified limit, adding ellipsis if truncated.
    
    Args:
        text: Text to truncate.
        limit: Maximum length before truncation.
    
    Returns:
        Original text if within limit, truncated text with '...' otherwise.
    """
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def format_status(passed: bool) -> str:
    """
    Format test status as a string indicator.
    
    Args:
        passed: Whether the test passed.
    
    Returns:
        'PASS' or 'FAIL' string.
    """
    return "PASS" if passed else "FAIL"


def format_points(earned: int, total: int) -> str:
    """
    Format points as 'earned/total' string.
    
    Args:
        earned: Points earned.
        total: Maximum points possible.
    
    Returns:
        Formatted points string.
    """
    return f"{earned}/{total}"


def get_categories(tests: Dict[str, Dict[str, Any]]) -> List[str]:
    """
    Extract unique categories from test results.
    
    Args:
        tests: Dictionary of test results keyed by test ID.
    
    Returns:
        Sorted list of unique category names.
    """
    categories = set()
    for test_data in tests.values():
        categories.add(test_data.get("category", "unknown"))
    return sorted(categories)


def print_summary(data: Dict[str, Any]) -> None:
    """
    Print score summary including category breakdown.
    
    Args:
        data: Complete results data dictionary.
    """
    meta = data.get("metadata", {})
    scores = data.get("scores", {})
    breakdown = data.get("category_breakdown", {})
    
    print_header(f"RESULTS: {meta.get('patch_name', 'Unknown')}")
    print(f"  Timestamp: {meta.get('timestamp', 'N/A')}")
    print(f"  Grader Version: {meta.get('grader_version', 'N/A')}")
    
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
        for target in ["python", "c"]:
            cats = breakdown.get(target, {})
            if cats:
                print(f"  {target.upper()}:")
                for cat, cat_scores in sorted(cats.items()):
                    if isinstance(cat_scores, list) and len(cat_scores) == 2:
                        print(f"    {cat:15s} {cat_scores[0]:2d}/{cat_scores[1]:2d}")
                    elif isinstance(cat_scores, dict):
                        score = cat_scores.get('score', 0)
                        max_score = cat_scores.get('max', 0)
                        print(f"    {cat:15s} {score:2d}/{max_score:2d}")


def print_test(test_id: str, test_data: Dict[str, Any], show_full: bool = False) -> None:
    """
    Print details for a single test.
    
    Args:
        test_id: Test identifier.
        test_data: Test result data dictionary.
        show_full: If True, print complete full_output field.
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
        print(f"\n  Full Output:")
        print(f"  {'-' * 50}")
        for line in full_output.split('\n'):
            # Wrap long lines for readability
            while len(line) > OUTPUT_LINE_WRAP:
                print(f"    {line[:OUTPUT_LINE_WRAP]}")
                line = line[OUTPUT_LINE_WRAP:]
            print(f"    {line}")


def print_tests_list(
    tests: Dict[str, Dict[str, Any]],
    filter_passed: Optional[bool] = None,
    filter_category: Optional[str] = None
) -> None:
    """
    Print list of tests with optional filtering.
    
    Args:
        tests: Dictionary of test results keyed by test ID.
        filter_passed: If set, only show tests matching this pass/fail status.
        filter_category: If set, only show tests in this category.
    """
    for test_id, test_data in tests.items():
        # Apply pass/fail filter
        if filter_passed is not None:
            if test_data.get("passed") != filter_passed:
                continue
        
        # Apply category filter
        if filter_category is not None:
            if test_data.get("category", "").lower() != filter_category.lower():
                continue
        
        status = format_status(test_data.get("passed", False))
        points = format_points(
            test_data.get("points_earned", 0),
            test_data.get("points", 0)
        )
        desc = test_data.get("description", "")[:40]
        
        print(f"  [{test_id:6s}] {status:4s} {points:5s} - {desc}")


def search_outputs(tests: Dict[str, Dict[str, Any]], query: str) -> None:
    """
    Search for a string in test full_output fields.
    
    Args:
        tests: Dictionary of test results keyed by test ID.
        query: Search string (case-insensitive).
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


def interactive_menu(data: Dict[str, Any]) -> None:
    """
    Run interactive menu for browsing results.
    
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
        
        if choice == 'q':
            print("Exiting.")
            break
        elif choice == '1':
            print_summary(data)
        elif choice == '2':
            print_header("ALL TESTS", "-")
            print_tests_list(tests)
        elif choice == '3':
            print_header("FAILED TESTS", "-")
            print_tests_list(tests, filter_passed=False)
        elif choice == '4':
            print_header("PASSED TESTS", "-")
            print_tests_list(tests, filter_passed=True)
        elif choice == '5':
            categories = get_categories(tests)
            print(f"\nAvailable categories: {', '.join(categories)}")
            cat = input("Enter category: ").strip()
            if cat:
                print_header(f"TESTS IN CATEGORY: {cat.upper()}", "-")
                print_tests_list(tests, filter_category=cat)
        elif choice == '6':
            test_ids = list(tests.keys())
            print(f"\nAvailable tests: {', '.join(test_ids)}")
            test_id = input("Enter test ID: ").strip().upper()
            if test_id in tests:
                print_test(test_id, tests[test_id], show_full=True)
            else:
                print(f"Test '{test_id}' not found.")
        elif choice == '7':
            query = input("Enter search string: ").strip()
            if query:
                search_outputs(tests, query)
        else:
            print("Invalid choice. Please try again.")
        
        input("\nPress Enter to continue...")


def create_parser() -> argparse.ArgumentParser:
    """
    Create and configure argument parser.
    
    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="results_viewer.py",
        description="CLI utility for browsing grading results JSON files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage Examples:
  Interactive mode (default):
    ./results_viewer.py results.json

  Non-interactive commands:
    ./results_viewer.py results.json --summary
    ./results_viewer.py results.json --test AN1
    ./results_viewer.py results.json --failed
    ./results_viewer.py results.json --passed
    ./results_viewer.py results.json --category login
    ./results_viewer.py results.json --full-output L1
    ./results_viewer.py results.json --list-categories

  Pipe full output for processing:
    ./results_viewer.py results.json -o P2 | python3 -m json.tool

Test IDs:
  Python: B1, P1, P2, L1-L3, O1-O2, C1-C2, A1, AN1-AN5
  C:      B2, M1, P1_c, P2_c, L1_c-L3_c, O1_c-O2_c, C1_c-C2_c, A1_c, AN1_c-AN5_c

Categories:
  build, protocol, login, logout, courses, authstatus, announcements, memory
        """
    )
    
    parser.add_argument(
        "results_file",
        type=Path,
        help="Path to the results JSON file"
    )
    parser.add_argument(
        "--summary", "-s",
        action="store_true",
        help="Print score summary and exit"
    )
    parser.add_argument(
        "--test", "-t",
        metavar="ID",
        help="Show details for a specific test ID (e.g., L1, AN2, P1_c)"
    )
    parser.add_argument(
        "--failed", "-f",
        action="store_true",
        help="List all failed tests"
    )
    parser.add_argument(
        "--passed", "-p",
        action="store_true",
        help="List all passed tests"
    )
    parser.add_argument(
        "--category", "-c",
        metavar="CAT",
        help="Filter tests by category (e.g., login, announcements)"
    )
    parser.add_argument(
        "--full-output", "-o",
        metavar="ID",
        help="Print only the full_output field for a test (useful for piping)"
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="List available test categories and exit"
    )
    
    return parser


def main() -> int:
    """
    Main entry point.
    
    Returns:
        Exit code (0 for success, 1 for error).
    """
    parser = create_parser()
    args = parser.parse_args()
    
    # Validate input file
    if not args.results_file.exists():
        print(f"Error: File not found: {args.results_file}", file=sys.stderr)
        return 1
    
    # Load JSON data
    try:
        data = load_results(args.results_file)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    
    tests = data.get("tests", {})
    
    # Handle --list-categories
    if args.list_categories:
        for cat in get_categories(tests):
            print(cat)
        return 0
    
    # Handle --full-output
    if args.full_output:
        test_id = args.full_output.upper()
        if test_id not in tests:
            print(f"Error: Test '{test_id}' not found", file=sys.stderr)
            print(f"Available tests: {', '.join(tests.keys())}", file=sys.stderr)
            return 1
        print(tests[test_id].get("full_output", ""))
        return 0
    
    # Handle --summary
    if args.summary:
        print_summary(data)
        return 0
    
    # Handle --test
    if args.test:
        test_id = args.test.upper()
        if test_id not in tests:
            print(f"Error: Test '{test_id}' not found", file=sys.stderr)
            print(f"Available tests: {', '.join(tests.keys())}", file=sys.stderr)
            return 1
        print_test(test_id, tests[test_id], show_full=True)
        return 0
    
    # Handle --failed
    if args.failed:
        print_header("FAILED TESTS", "-")
        print_tests_list(tests, filter_passed=False)
        return 0
    
    # Handle --passed
    if args.passed:
        print_header("PASSED TESTS", "-")
        print_tests_list(tests, filter_passed=True)
        return 0
    
    # Handle --category
    if args.category:
        print_header(f"TESTS IN CATEGORY: {args.category.upper()}", "-")
        print_tests_list(tests, filter_category=args.category)
        return 0
    
    # Default: interactive mode
    interactive_menu(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
