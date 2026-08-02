from __future__ import annotations

import unittest
from pathlib import Path

from candidates.candidate_evaluation import ExternalDependency, validate_region_candidate
from orchestrator.region import Criterion, RegionProposal


class RegionGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = "HEADER = 1\ndef target(value):\n    return value + 1\n"
        self.region = RegionProposal(Criterion(Path("module.py"), "target", 1, 3), ((1, 3),))

    def test_allows_insertions_and_deletions_in_region(self) -> None:
        candidate = "HEADER = 1\ndef target(value):\n    if value:\n        return value\n    return 0\n"
        result = validate_region_candidate(self.original, candidate, self.region)
        self.assertTrue(result.accepted)
        self.assertEqual(result.outcome, "accepted_region_only")

    def test_rejects_out_of_region_change(self) -> None:
        candidate = "HEADER = 2\ndef target(value):\n    return value + 1\n"
        result = validate_region_candidate(self.original, candidate, self.region)
        self.assertFalse(result.accepted)
        self.assertIn("out-of-region", " ".join(result.reasons))

    def test_allows_declared_referenced_helper(self) -> None:
        candidate = "HEADER = 1\ndef helper(value):\n    return value\ndef target(value):\n    return helper(value)\n"
        result = validate_region_candidate(
            self.original,
            candidate,
            self.region,
            [ExternalDependency("helper", "helper", "The branch-free helper is the only reusable form.")],
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.dependencies, ("helper",))

    def test_rejects_unreferenced_or_undeclared_helper(self) -> None:
        candidate = "HEADER = 1\ndef helper(value):\n    return value\ndef target(value):\n    return value + 1\n"
        result = validate_region_candidate(self.original, candidate, self.region)
        self.assertFalse(result.accepted)
        self.assertIn("helper", " ".join(result.reasons))

    def test_allows_referenced_stdlib_import_only_when_declared(self) -> None:
        candidate = "import math\nHEADER = 1\ndef target(value):\n    return math.floor(value)\n"
        result = validate_region_candidate(
            self.original,
            candidate,
            self.region,
            [ExternalDependency("math", "import", "A stdlib operation is required for flooring.")],
        )
        self.assertTrue(result.accepted)


if __name__ == "__main__":
    unittest.main()
