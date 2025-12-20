#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Scorer - Point allocation and test result aggregation.

Scoring structure (48 points total):
- Python Baseline: 12 points (existing main branch functionality)
- Python Feature: 12 points (get_course_announcements implementation)
- C Replica: 24 points (full C implementation)
"""

from typing import Dict, List, Tuple
from dataclasses import dataclass, field


@dataclass
class TestDefinition:
    """Definition of a single test case."""
    id: str
    points: int
    category: str
    target: str  # "python", "c", or "both"
    description: str
    group: str  # "baseline" or "feature"


# Test definitions organized by execution order
PYTHON_BASELINE_TESTS: List[TestDefinition] = [
    TestDefinition("B1", 2, "build", "python", "Python dependency installation", "baseline"),
    TestDefinition("P1", 1, "protocol", "python", "initialize response structure", "baseline"),
    TestDefinition("P2", 1, "protocol", "python", "tools/list response structure", "baseline"),
    TestDefinition("L1", 1, "login", "python", "Successful login", "baseline"),
    TestDefinition("L2", 1, "login", "python", "Already logged in handling", "baseline"),
    TestDefinition("L3", 1, "login", "python", "Missing credentials error", "baseline"),
    TestDefinition("O1", 1, "logout", "python", "Successful logout", "baseline"),
    TestDefinition("O2", 1, "logout", "python", "Logout when not logged in", "baseline"),
    TestDefinition("C1", 1, "courses", "python", "Get courses when logged in", "baseline"),
    TestDefinition("C2", 1, "courses", "python", "Get courses when not logged in", "baseline"),
    TestDefinition("A1", 1, "authstatus", "python", "Authstatus when not logged in", "baseline"),
]

PYTHON_FEATURE_TESTS: List[TestDefinition] = [
    TestDefinition("AN1", 2, "announcements", "python", "Not logged in error (exact string)", "feature"),
    TestDefinition("AN2", 2, "announcements", "python", "Invalid course URL error (exact string)", "feature"),
    TestDefinition("AN3", 2, "announcements", "python", "No announcements found (exact string)", "feature"),
    TestDefinition("AN4", 3, "announcements", "python", "Valid announcements with default days_back", "feature"),
    TestDefinition("AN5", 3, "announcements", "python", "Valid announcements with custom days_back", "feature"),
]

C_TESTS: List[TestDefinition] = [
    TestDefinition("B2", 3, "build", "c", "C compilation (make c-server)", "baseline"),
    TestDefinition("M1", 3, "memory", "c", "Valgrind memory clean", "baseline"),
    TestDefinition("P1_c", 1, "protocol", "c", "initialize response structure", "baseline"),
    TestDefinition("P2_c", 1, "protocol", "c", "tools/list response structure", "baseline"),
    TestDefinition("L1_c", 1, "login", "c", "Successful login", "baseline"),
    TestDefinition("L2_c", 1, "login", "c", "Already logged in handling", "baseline"),
    TestDefinition("L3_c", 1, "login", "c", "Missing credentials error", "baseline"),
    TestDefinition("O1_c", 1, "logout", "c", "Successful logout", "baseline"),
    TestDefinition("O2_c", 1, "logout", "c", "Logout when not logged in", "baseline"),
    TestDefinition("C1_c", 1, "courses", "c", "Get courses when logged in", "baseline"),
    TestDefinition("C2_c", 1, "courses", "c", "Get courses when not logged in", "baseline"),
    TestDefinition("A1_c", 1, "authstatus", "c", "Authstatus when not logged in", "baseline"),
    TestDefinition("AN1_c", 2, "announcements", "c", "Not logged in error", "feature"),
    TestDefinition("AN2_c", 2, "announcements", "c", "Invalid course URL error", "feature"),
    TestDefinition("AN3_c", 1, "announcements", "c", "No announcements found", "feature"),
    TestDefinition("AN4_c", 2, "announcements", "c", "Valid announcements with default days_back", "feature"),
    TestDefinition("AN5_c", 1, "announcements", "c", "Valid announcements with custom days_back", "feature"),
]


def get_all_tests() -> Dict[str, TestDefinition]:
    """Return all test definitions keyed by ID."""
    all_tests = PYTHON_BASELINE_TESTS + PYTHON_FEATURE_TESTS + C_TESTS
    return {t.id: t for t in all_tests}


def get_max_scores() -> Dict[str, int]:
    """Calculate maximum possible scores for each category."""
    return {
        "python_baseline": sum(t.points for t in PYTHON_BASELINE_TESTS),
        "python_feature": sum(t.points for t in PYTHON_FEATURE_TESTS),
        "python_total": sum(t.points for t in PYTHON_BASELINE_TESTS + PYTHON_FEATURE_TESTS),
        "c_total": sum(t.points for t in C_TESTS),
        "total": sum(t.points for t in PYTHON_BASELINE_TESTS + PYTHON_FEATURE_TESTS + C_TESTS),
    }


@dataclass
class TestResult:
    """Result of a single test execution."""
    test_id: str
    passed: bool
    message: str
    full_output: str = ""  # Full output for JSON report


@dataclass
class Scorer:
    """Calculates and aggregates test scores."""
    results: Dict[str, TestResult] = field(default_factory=dict)
    
    def record(self, test_id: str, passed: bool, message: str, full_output: str = "") -> None:
        """Record a test result."""
        self.results[test_id] = TestResult(
            test_id=test_id,
            passed=passed,
            message=message,
            full_output=full_output or message
        )
    
    def get_python_baseline_score(self) -> Tuple[int, int]:
        """Return (score, max) for Python baseline tests."""
        score = 0
        max_score = 0
        for test in PYTHON_BASELINE_TESTS:
            max_score += test.points
            if self.results.get(test.id, TestResult(test.id, False, "")).passed:
                score += test.points
        return score, max_score
    
    def get_python_feature_score(self) -> Tuple[int, int]:
        """Return (score, max) for Python feature tests."""
        score = 0
        max_score = 0
        for test in PYTHON_FEATURE_TESTS:
            max_score += test.points
            if self.results.get(test.id, TestResult(test.id, False, "")).passed:
                score += test.points
        return score, max_score
    
    def get_python_total_score(self) -> Tuple[int, int]:
        """Return (score, max) for all Python tests."""
        baseline = self.get_python_baseline_score()
        feature = self.get_python_feature_score()
        return baseline[0] + feature[0], baseline[1] + feature[1]
    
    def get_c_score(self) -> Tuple[int, int]:
        """Return (score, max) for C tests."""
        score = 0
        max_score = 0
        for test in C_TESTS:
            max_score += test.points
            if self.results.get(test.id, TestResult(test.id, False, "")).passed:
                score += test.points
        return score, max_score
    
    def get_total_score(self) -> Tuple[int, int]:
        """Return (score, max) for all tests."""
        py = self.get_python_total_score()
        c = self.get_c_score()
        return py[0] + c[0], py[1] + c[1]
    
    def get_category_breakdown(self, target: str) -> Dict[str, Tuple[int, int]]:
        """
        Return score breakdown by category for a target (python/c).
        
        Returns dict mapping category -> (score, max).
        """
        if target == "python":
            tests = PYTHON_BASELINE_TESTS + PYTHON_FEATURE_TESTS
        else:
            tests = C_TESTS
        
        categories: Dict[str, List[int]] = {}
        for test in tests:
            if test.category not in categories:
                categories[test.category] = [0, 0]
            categories[test.category][1] += test.points
            if self.results.get(test.id, TestResult(test.id, False, "")).passed:
                categories[test.category][0] += test.points
        
        return {cat: (scores[0], scores[1]) for cat, scores in categories.items()}
    
    def to_dict(self) -> dict:
        """Export full scoring data as dictionary for JSON serialization."""
        tests = get_all_tests()
        py_baseline = self.get_python_baseline_score()
        py_feature = self.get_python_feature_score()
        py_total = self.get_python_total_score()
        c_total = self.get_c_score()
        total = self.get_total_score()
        
        return {
            "scores": {
                "python": {
                    "baseline": {"score": py_baseline[0], "max": py_baseline[1]},
                    "feature": {"score": py_feature[0], "max": py_feature[1]},
                    "total": {"score": py_total[0], "max": py_total[1]},
                },
                "c": {
                    "total": {"score": c_total[0], "max": c_total[1]},
                },
                "grand_total": {"score": total[0], "max": total[1]},
            },
            "tests": {
                test_id: {
                    "passed": result.passed,
                    "points": tests[test_id].points if test_id in tests else 0,
                    "points_earned": tests[test_id].points if test_id in tests and result.passed else 0,
                    "category": tests[test_id].category if test_id in tests else "unknown",
                    "description": tests[test_id].description if test_id in tests else "",
                    "message": result.message,
                    "full_output": result.full_output,
                }
                for test_id, result in self.results.items()
            },
            "category_breakdown": {
                "python": self.get_category_breakdown("python"),
                "c": self.get_category_breakdown("c"),
            },
        }
