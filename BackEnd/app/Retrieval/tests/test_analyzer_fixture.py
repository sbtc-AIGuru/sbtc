import unittest

from BackEnd.app.Retrieval.tests.analyze_fixture import (
    LEGACY_FIXTURE,
    check_case,
    load_cases,
    run_diagnostics,
    validate_fixture,
)
from BackEnd.app.Retrieval.analyzers import MedicalAnalyzer
from BackEnd.app.Retrieval.lexicon import Lexicon


class AnalyzerFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases()

    def test_fixture_is_balanced_and_complete(self):
        validate_fixture(self.cases)
        self.assertEqual(len(self.cases), 90)
        self.assertEqual(sum(bool(case.get("known_limitation")) for case in self.cases), 1)

    def test_legacy_fixture_is_preserved_as_a_separate_profile(self):
        cases = load_cases(LEGACY_FIXTURE, profile="folded-v0")
        self.assertEqual(len(cases), 90)
        self.assertTrue(any("folded" in group["fields"] for case in cases for group in case["required_any"]))

    def test_no_folded_profile_contract_cases_pass(self):
        report = run_diagnostics(self.cases, MedicalAnalyzer(Lexicon()))
        self.assertEqual(report["contract_mismatch_cases"], 0)
        self.assertEqual(report["known_limitations"][0]["case_id"], "vi-24")
        self.assertEqual(report["known_limitations"][0]["limitation"], "accentless_vietnamese_query_rescue_removed_with_folded_field")

    def test_expectation_checker_accepts_explicit_alternative_sequences(self):
        case = {
            "required_any": [
                {"fields": ["contents", "broad"], "one_of": [["động_kinh"], ["động", "kinh"]]},
            ],
            "required_exact": ["j18.9"],
            "anchors_include": ["local:epilepsy"],
            "anchors_exclude": ["local:diabetes"],
        }
        fields = {
            "contents": ("cơn", "động", "kinh"),
            "broad": ("động", "kinh", "động_kinh"),
            "exact": ("j18.9",),
            "anchors": ("local:epilepsy",),
        }
        self.assertEqual(check_case(case, fields), [])

    def test_expectation_checker_reports_missing_and_forbidden_values(self):
        case = {
            "required_any": [{"fields": ["contents"], "one_of": [["pneumonia"]]}],
            "required_none": [{"fields": ["anchors"], "one_of": [["local:hypertension"]]}],
            "required_exact": ["j18.9"],
            "anchors_include": ["local:pneumonia"],
            "anchors_exclude": ["local:diabetes"],
        }
        fields = {
            "contents": (),
            "exact": (),
            "anchors": ("local:hypertension", "local:diabetes"),
        }
        failures = check_case(case, fields)
        self.assertEqual(len(failures), 5)

    def test_fixture_rejects_a_missing_record_instead_of_rebalancing_silently(self):
        with self.assertRaisesRegex(ValueError, "Expected 90 cases"):
            validate_fixture(self.cases[:-1])


if __name__ == "__main__":
    unittest.main()
