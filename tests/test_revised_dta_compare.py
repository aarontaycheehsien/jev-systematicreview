"""Offline comparator checks; no paid Jev calls or PubMed downloads."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from compare_revised_dta import BASELINE, check_pubmed_cache, evaluate_scope, read_and_validate


class ComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = pd.read_csv(BASELINE, dtype={"pmid": str, "review_id": str})

    def make_revised(self, path):
        revised = self.baseline[["review_id", "pmid", "label_included", "jev_probability",
                                 "jev_model"]].copy()
        revised["error"] = ""
        revised.to_csv(path, index=False)
        return revised

    def test_identical_saved_scores_reproduce_baseline_exactly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "revised.csv"
            self.make_revised(path)
            paired, old_models, new_models = read_and_validate(BASELINE, path, False)
            self.assertEqual(len(paired), 30521)
            self.assertEqual(old_models, new_models)
            self.assertEqual(int(paired.abstract_available.sum()), 26832)
            for scope, expected in (("nonmissing", 0.6479776529047265), ("all", None)):
                metrics = evaluate_scope(paired, scope)
                self.assertEqual(len(metrics), 8)
                self.assertTrue((metrics["delta_WSS@95"].abs() < 1e-12).all())
                if expected is not None:
                    self.assertAlmostEqual(float(metrics["original_WSS@95"].mean()), expected, 10)

    def test_missing_pair_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "revised.csv"
            revised = self.make_revised(path).iloc[1:]
            revised.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "30,521"):
                read_and_validate(BASELINE, path, False)

    def test_model_change_requires_explicit_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "revised.csv"
            revised = self.make_revised(path)
            revised["jev_model"] = "hypothetical-different-model"
            revised.to_csv(path, index=False)
            with self.assertRaisesRegex(ValueError, "Model change"):
                read_and_validate(BASELINE, path, False)
            _, old, new = read_and_validate(BASELINE, path, True)
            self.assertNotEqual(old, new)

    def test_cache_detects_abstract_status_drift(self):
        paired = pd.DataFrame({"pmid": ["123", "456"], "abstract_available": [True, False]})
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "metadata.json"
            cache.write_text(json.dumps({
                "123": {"abstract": "present", "retrieval_error": ""},
                "456": {"abstract": "", "retrieval_error": ""}
            }), encoding="utf-8")
            self.assertIn("matches", check_pubmed_cache(paired, cache, False))
            cache.write_text(json.dumps({
                "123": {"abstract": "", "retrieval_error": ""},
                "456": {"abstract": "", "retrieval_error": ""}
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs"):
                check_pubmed_cache(paired, cache, False)


if __name__ == "__main__":
    unittest.main()
