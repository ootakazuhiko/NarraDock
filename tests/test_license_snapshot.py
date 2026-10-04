"""Guard the approved wording and the distinct activation state; no legal certification."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA256 = "0744ff99f4ef6d5e6d0b1acef0cf375fd1b19b15494a4a5df9cedb491af2f15a"
SNAPSHOT = "licenses/NarraDock-Source-Available-1.0.ja.md"


class LicenseSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.raw = (ROOT / SNAPSHOT).read_bytes()
        self.text = self.raw.decode("utf-8")
        self.status = json.loads((ROOT / "docs/license-status.json").read_text(encoding="utf-8"))

    def test_original_bytes_are_unchanged(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), EXPECTED_SHA256)

    def test_status_binds_the_exact_snapshot(self):
        self.assertEqual(self.status["approved_text"], SNAPSHOT)
        self.assertEqual(self.status["approved_text_sha256"], EXPECTED_SHA256)

    def test_all_twenty_articles_are_preserved(self):
        self.assertEqual(re.findall(r"^## 第(\d+)条", self.text, re.MULTILINE),
                         [str(number) for number in range(1, 21)])

    def test_annexes_and_review_note_are_retained(self):
        for heading in ("## 別紙A", "## 別紙B", "## 採用審査メモ"):
            self.assertIn(heading, self.text)

    def test_terms_are_approved_not_undecided(self):
        self.assertEqual(self.status["terms_status"], "approved")
        self.assertEqual(self.status["decision_date"], "2026-10-04")
        self.assertTrue(self.status["maintainer_authorized_product_development"])

    def test_unprovided_activation_is_not_invented(self):
        self.assertEqual(self.status["activation_status"], "pending_annex_completion")
        for field in ("effective_date", "applicable_software_revision"):
            self.assertIsNone(self.status[field])
        for field in ("public_license_grant_active", "paid_order_acceptance_enabled",
                      "legal_review_completed", "contributor_relicensing_rights_verified"):
            self.assertIs(self.status[field], False)
        self.assertEqual(self.status["annex_a_status"], "not_completed")
        self.assertEqual(self.status["annex_b_status"], "not_completed")

    def test_license_entry_links_to_decision_and_text(self):
        notice = (ROOT / "LICENSE.md").read_text(encoding="utf-8")
        self.assertIn(SNAPSHOT, notice)
        self.assertIn("docs/license-decision.md", notice)
        self.assertIn("not yet an effective public software grant", notice)

    def test_public_inventory_includes_policy_and_handoff(self):
        inventory = json.loads((ROOT / "public-files.json").read_text(encoding="utf-8"))
        self.assertEqual(len(inventory), len(set(inventory)))
        for name in (SNAPSHOT, "LICENSE.md", "docs/license-decision.md",
                     "docs/license-status.json", "docs/codex-handoff.md",
                     "tests/test_license_snapshot.py"):
            self.assertIn(name, inventory)


if __name__ == "__main__":
    unittest.main()
