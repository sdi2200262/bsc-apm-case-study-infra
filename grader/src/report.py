#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025 BSc Case Study Grader Contributors
"""
Report Writer - Generates grading reports in JSON and text formats.

JSON output: Complete, machine-parsable report with full details.
Console output: Human-readable summary with medium-length excerpts.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

from .scorer import (
    Scorer, get_all_tests, 
    PYTHON_BASELINE_TESTS, PYTHON_COURSE_TESTS, PYTHON_GENERAL_TESTS,
    C_INFRA_TESTS, C_BASELINE_TESTS, C_COURSE_TESTS, C_GENERAL_TESTS
)

# Aggregate test lists for reporting
PYTHON_FEATURE_TESTS = PYTHON_COURSE_TESTS + PYTHON_GENERAL_TESTS
C_TESTS = C_INFRA_TESTS + C_BASELINE_TESTS + C_COURSE_TESTS + C_GENERAL_TESTS


# Maximum length for console message excerpts
CONSOLE_MESSAGE_LIMIT = 200


def truncate(text: str, limit: int = CONSOLE_MESSAGE_LIMIT) -> str:
    """
    Truncate text to limit, adding ellipsis if needed.
    
    Args:
        text: Text string to truncate.
        limit: Maximum length (default: CONSOLE_MESSAGE_LIMIT).
    
    Returns:
        Truncated string with "..." suffix if truncated, original string otherwise.
    """
    if len(text) <= limit:
        return text
    return text[:limit-3] + "..."


class ReportWriter:
    """Generates and writes grading reports."""
    
    def __init__(self, workspace_root: Path, patch_name: str):
        """
        Initialize report writer.
        
        Args:
            workspace_root: Root directory for output files
            patch_name: Name of the patch being graded
        """
        self.workspace_root = Path(workspace_root).resolve()
        self.patch_name = patch_name
        self.timestamp = datetime.now().isoformat()
        
        # Output paths (same directory as workspace root)
        self.json_path = self.workspace_root / f"results_{patch_name}.json"
        self.txt_path = self.workspace_root / f"results_{patch_name}.txt"
    
    def write_json(self, scorer: Scorer, metadata: Optional[dict] = None) -> Path:
        """
        Write complete JSON report.
        
        Args:
            scorer: Scorer instance with test results
            metadata: Optional additional metadata (e.g., patch info, timing)
            
        Returns:
            Path to written JSON file
        """
        report = {
            "metadata": {
                "patch_name": self.patch_name,
                "timestamp": self.timestamp,
                "grader_version": "1.0.0",
                **(metadata or {})
            },
            **scorer.to_dict()
        }
        
        with open(self.json_path, "w") as f:
            json.dump(report, f, indent=2)
        
        return self.json_path
    
    def write_text(self, scorer: Scorer) -> Path:
        """
        Write human-readable text report.
        
        Args:
            scorer: Scorer instance with test results
            
        Returns:
            Path to written text file
        """
        lines = []
        tests = get_all_tests()
        
        # Header
        lines.append("=" * 70)
        lines.append(f"GRADING REPORT: {self.patch_name}")
        lines.append("=" * 70)
        lines.append(f"Generated: {self.timestamp}")
        lines.append("")
        
        # Python Baseline Section
        py_baseline = scorer.get_python_baseline_score()
        lines.append("-" * 70)
        lines.append(f"PYTHON BASELINE ({py_baseline[0]}/{py_baseline[1]})")
        lines.append("-" * 70)
        
        for test in PYTHON_BASELINE_TESTS:
            result = scorer.results.get(test.id)
            if result:
                status = "PASS" if result.passed else "FAIL"
                lines.append(f"  [{status}] {test.id}: {test.description}")
                lines.append(f"          {truncate(result.message)}")
            else:
                lines.append(f"  [SKIP] {test.id}: {test.description}")
                lines.append(f"          Not executed")
        lines.append("")
        
        # Python Feature Section
        py_feature = scorer.get_python_feature_score()
        lines.append("-" * 70)
        lines.append(f"PYTHON FEATURE ({py_feature[0]}/{py_feature[1]})")
        lines.append("-" * 70)
        
        for test in PYTHON_FEATURE_TESTS:
            result = scorer.results.get(test.id)
            if result:
                status = "PASS" if result.passed else "FAIL"
                lines.append(f"  [{status}] {test.id}: {test.description}")
                lines.append(f"          {truncate(result.message)}")
            else:
                lines.append(f"  [SKIP] {test.id}: {test.description}")
                lines.append(f"          Not executed")
        lines.append("")
        
        # C Section
        c_total = scorer.get_c_score()
        lines.append("-" * 70)
        lines.append(f"C REPLICA ({c_total[0]}/{c_total[1]})")
        lines.append("-" * 70)
        
        for test in C_TESTS:
            result = scorer.results.get(test.id)
            if result:
                status = "PASS" if result.passed else "FAIL"
                lines.append(f"  [{status}] {test.id}: {test.description}")
                lines.append(f"          {truncate(result.message)}")
            else:
                lines.append(f"  [SKIP] {test.id}: {test.description}")
                lines.append(f"          Not executed")
        lines.append("")
        
        # Summary
        py_total = scorer.get_python_total_score()
        total = scorer.get_total_score()
        
        lines.append("=" * 70)
        lines.append("SUMMARY")
        lines.append("=" * 70)
        lines.append(f"  Python Baseline:  {py_baseline[0]:2d}/{py_baseline[1]:2d}")
        lines.append(f"  Python Feature:   {py_feature[0]:2d}/{py_feature[1]:2d}")
        lines.append(f"  Python Total:     {py_total[0]:2d}/{py_total[1]:2d}")
        lines.append(f"  C Replica:        {c_total[0]:2d}/{c_total[1]:2d}")
        lines.append(f"  ----------------------------------------")
        lines.append(f"  TOTAL:            {total[0]:2d}/{total[1]:2d}")
        lines.append("")
        lines.append("=" * 70)
        
        content = "\n".join(lines)
        with open(self.txt_path, "w") as f:
            f.write(content)
        
        return self.txt_path
    
    def print_console_summary(self, scorer: Scorer, verbose: bool = False) -> None:
        """
        Print summary to console.
        
        Args:
            scorer: Scorer instance with test results
            verbose: If True, print individual test results
        """
        py_baseline = scorer.get_python_baseline_score()
        py_feature = scorer.get_python_feature_score()
        py_total = scorer.get_python_total_score()
        c_total = scorer.get_c_score()
        total = scorer.get_total_score()
        
        print("")
        print("=" * 50)
        print("GRADING SUMMARY")
        print("=" * 50)
        
        if verbose:
            self._print_verbose_results(scorer)
        
        print(f"  Python Baseline:  {py_baseline[0]:2d}/{py_baseline[1]:2d}")
        print(f"  Python Feature:   {py_feature[0]:2d}/{py_feature[1]:2d}")
        print(f"  Python Total:     {py_total[0]:2d}/{py_total[1]:2d}")
        print(f"  C Replica:        {c_total[0]:2d}/{c_total[1]:2d}")
        print(f"  ----------------------------------------")
        print(f"  TOTAL:            {total[0]:2d}/{total[1]:2d}")
        print("")
        print(f"  JSON report: {self.json_path}")
        print(f"  Text report: {self.txt_path}")
        print("=" * 50)
    
    def _print_verbose_results(self, scorer: Scorer) -> None:
        """
        Print individual test results in verbose mode.
        
        Args:
            scorer: Scorer instance with test results.
        """
        tests = get_all_tests()
        
        print("\n  Python Baseline:")
        for test in PYTHON_BASELINE_TESTS:
            result = scorer.results.get(test.id)
            if result:
                status = "PASS" if result.passed else "FAIL"
                print(f"    [{status}] {test.id}: {truncate(result.message, 60)}")
        
        print("\n  Python Feature:")
        for test in PYTHON_FEATURE_TESTS:
            result = scorer.results.get(test.id)
            if result:
                status = "PASS" if result.passed else "FAIL"
                print(f"    [{status}] {test.id}: {truncate(result.message, 60)}")
        
        print("\n  C Replica:")
        for test in C_TESTS:
            result = scorer.results.get(test.id)
            if result:
                status = "PASS" if result.passed else "FAIL"
                print(f"    [{status}] {test.id}: {truncate(result.message, 60)}")
        
        print("")
