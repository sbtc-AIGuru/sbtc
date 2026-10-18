"""Diagnostic runner for the independently authored medical analyzer fixture."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from BackEnd.app.Retrieval.analyzers import MedicalAnalyzer
from BackEnd.app.Retrieval.lexicon import Lexicon


FIXTURE = Path(__file__).parent / "fixtures/medical_analyzer_cases_no_folded_v1.jsonl"
LEGACY_FIXTURE = Path(__file__).parent / "fixtures/medical_analyzer_cases.jsonl"
LANGUAGES = ("vi", "en", "zh")
RISK_GROUPS = (
    "unicode_boundary",
    "segmentation_morphology",
    "medical_literals_dose",
    "negation_acronyms",
    "variants_mixed_language",
    "text_style_noise",
    "cross_language",
)
INPUT_STYLES = ("prose", "qa", "heading_body", "list", "table_flat", "short_mixed")
FIELDS = {"contents", "broad", "exact", "anchors"}
LEGACY_FIELDS = FIELDS | {"folded"}
PAIRED_CONCEPTS = {
    "diabetes": "local:diabetes",
    "chronic_kidney_disease": "local:chronic_kidney_disease",
    "pneumonia": "local:pneumonia",
    "paracetamol": "local:paracetamol",
    "asthma": None,
    "epilepsy": None,
}


def load_cases(path: Path = FIXTURE, *, profile: str = "medical-no-folded-v1") -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                raise ValueError(f"Blank fixture line at {line_number}")
            try:
                case = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON at line {line_number}: {error}") from error
            if not isinstance(case, dict):
                raise ValueError(f"Fixture line {line_number} must contain a JSON object")
            cases.append(case)
    validate_fixture(cases, profile=profile)
    return cases


def _validate_expectation(case: dict[str, Any], field: str, allowed_fields: set[str] | None = None) -> None:
    groups = case.get(field)
    if not isinstance(groups, list):
        raise ValueError(f"{case['case_id']}: {field} must be a list")
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError(f"{case['case_id']}: {field} entries must be objects")
        fields = group.get("fields")
        alternatives = group.get("one_of")
        accepted_fields = allowed_fields if allowed_fields is not None else FIELDS
        if not isinstance(fields, list) or not fields or not set(fields) <= accepted_fields:
            raise ValueError(f"{case['case_id']}: invalid fields in {field}")
        if not isinstance(alternatives, list) or not alternatives:
            raise ValueError(f"{case['case_id']}: {field} needs at least one accepted form")
        for sequence in alternatives:
            if not isinstance(sequence, list) or not sequence or any(not isinstance(token, str) or not token for token in sequence):
                raise ValueError(f"{case['case_id']}: alternatives must be non-empty token sequences")
            if any(any(char.isspace() for char in token) for token in sequence):
                raise ValueError(f"{case['case_id']}: each expected token must be whitespace-free")


def validate_fixture(cases: list[dict[str, Any]], *, profile: str = "medical-no-folded-v1") -> None:
    if profile not in {"medical-no-folded-v1", "folded-v0"}:
        raise ValueError(f"Unknown analyzer fixture profile: {profile}")
    allowed_fields = FIELDS if profile == "medical-no-folded-v1" else LEGACY_FIELDS
    if len(cases) != 90:
        raise ValueError(f"Expected 90 cases, got {len(cases)}")
    ids = [case.get("case_id") for case in cases]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("case_id values must be non-empty and unique")

    language_counts = Counter(case.get("language") for case in cases)
    if language_counts != Counter({language: 30 for language in LANGUAGES}):
        raise ValueError(f"Expected 30 cases per language, got {dict(language_counts)}")

    risk_counts: dict[str, Counter[str]] = defaultdict(Counter)
    style_counts: dict[str, Counter[str]] = defaultdict(Counter)
    pair_cases: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        required = ("case_id", "language", "risk_group", "input_style", "text", "status", "source", "rationale")
        missing = [key for key in required if key not in case]
        if missing:
            raise ValueError(f"{case.get('case_id', '<unknown>')}: missing {', '.join(missing)}")
        if case["language"] not in LANGUAGES:
            raise ValueError(f"{case['case_id']}: unsupported language")
        if case["risk_group"] not in RISK_GROUPS:
            raise ValueError(f"{case['case_id']}: unsupported risk_group")
        if case["input_style"] not in INPUT_STYLES:
            raise ValueError(f"{case['case_id']}: unsupported input_style")
        if case["status"] not in {"contract", "challenge"}:
            raise ValueError(f"{case['case_id']}: status must be contract or challenge")
        if case["source"] != "synthetic" or not isinstance(case["text"], str) or not case["text"].strip():
            raise ValueError(f"{case['case_id']}: text must be non-empty synthetic input")
        if not isinstance(case["rationale"], str) or not case["rationale"].strip():
            raise ValueError(f"{case['case_id']}: rationale must be non-empty")
        if not isinstance(case.get("required_exact"), list):
            raise ValueError(f"{case['case_id']}: required_exact must be a list")
        if any(not isinstance(token, str) or not token or any(char.isspace() for char in token) for token in case["required_exact"]):
            raise ValueError(f"{case['case_id']}: required_exact must contain whitespace-free tokens")
        if not isinstance(case.get("anchors_include"), list) or not isinstance(case.get("anchors_exclude"), list):
            raise ValueError(f"{case['case_id']}: anchor expectations must be lists")
        if not isinstance(case.get("required_any"), list):
            raise ValueError(f"{case['case_id']}: required_any must be a list")
        if not case["required_any"] and not (profile == "medical-no-folded-v1" and case.get("known_limitation")):
            raise ValueError(f"{case['case_id']}: empty lexical expectations need an explicit known_limitation")
        _validate_expectation(case, "required_any", allowed_fields)
        if "required_none" in case:
            _validate_expectation(case, "required_none", allowed_fields)
        risk_counts[case["language"]][case["risk_group"]] += 1
        style_counts[case["language"]][case["input_style"]] += 1
        if "paired_concept" in case:
            pair_cases[case["paired_concept"]].append(case)

    expected_risks = set(RISK_GROUPS) - {"cross_language"}
    for language in LANGUAGES:
        actual = risk_counts[language]
        if set(actual) != set(RISK_GROUPS) or actual["cross_language"] != 6:
            raise ValueError(f"{language}: expected 4 cases per risk group and 6 paired cases, got {dict(actual)}")
        if any(actual[group] != 4 for group in expected_risks):
            raise ValueError(f"{language}: expected four cases in each non-paired risk group, got {dict(actual)}")
        styles = style_counts[language]
        if set(styles) != set(INPUT_STYLES) or any(styles[style] != 5 for style in INPUT_STYLES):
            raise ValueError(f"{language}: expected five cases per input style, got {dict(styles)}")
        if max(styles.values()) > 0.25 * language_counts[language]:
            raise ValueError(f"{language}: one input style exceeds 25% of cases")

    if set(pair_cases) != set(PAIRED_CONCEPTS):
        raise ValueError(f"Expected paired concepts {sorted(PAIRED_CONCEPTS)}, got {sorted(pair_cases)}")
    for concept, grouped in pair_cases.items():
        if len(grouped) != 3 or {case["language"] for case in grouped} != set(LANGUAGES):
            raise ValueError(f"{concept}: expected one paired case per language")
        expected_anchor = PAIRED_CONCEPTS[concept]
        if expected_anchor:
            for case in grouped:
                if expected_anchor not in case["anchors_include"]:
                    raise ValueError(f"{case['case_id']}: paired concept must require anchor {expected_anchor}")
        elif any("anchors_include" in case and case["anchors_include"] for case in grouped):
            raise ValueError(f"{concept}: out-of-seed pair must not require a current seed anchor")


def _contains_sequence(tokens: tuple[str, ...], sequence: list[str]) -> bool:
    expected = tuple(sequence)
    width = len(expected)
    return any(tokens[index:index + width] == expected for index in range(len(tokens) - width + 1))


def check_case(case: dict[str, Any], fields: dict[str, tuple[str, ...]]) -> list[str]:
    failures: list[str] = []
    for group in case["required_any"]:
        matched = any(
            _contains_sequence(fields.get(field, ()), sequence)
            for field in group["fields"]
            for sequence in group["one_of"]
        )
        if not matched:
            choices = " OR ".join(" ".join(sequence) for sequence in group["one_of"])
            failures.append(f"missing one of [{choices}] in {group['fields']}")
    for group in case.get("required_none", []):
        matched = any(
            _contains_sequence(fields.get(field, ()), sequence)
            for field in group["fields"]
            for sequence in group["one_of"]
        )
        if matched:
            choices = " OR ".join(" ".join(sequence) for sequence in group["one_of"])
            failures.append(f"unexpected [{choices}] in {group['fields']}")
    exact = set(fields.get("exact", ()))
    missing_exact = sorted(set(case["required_exact"]) - exact)
    if missing_exact:
        failures.append(f"missing exact literals {missing_exact}")
    anchors = set(fields.get("anchors", ()))
    missing_anchors = sorted(set(case["anchors_include"]) - anchors)
    if missing_anchors:
        failures.append(f"missing anchors {missing_anchors}")
    unexpected_anchors = sorted(set(case["anchors_exclude"]) & anchors)
    if unexpected_anchors:
        failures.append(f"unexpected anchors {unexpected_anchors}")
    return failures


def run_diagnostics(cases: list[dict[str, Any]], analyzer: MedicalAnalyzer) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    case_passes: dict[str, bool] = {}
    for case in cases:
        outputs = {
            mode: analyzer.analyze(case["text"], case["language"], index_mode=mode).fields
            for mode in (False, True)
        }
        failures: list[dict[str, Any]] = []
        for mode, fields in outputs.items():
            for detail in check_case(case, fields):
                failures.append({"mode": "index" if mode else "query", "detail": detail})
        for field in ("contents", "exact", "anchors"):
            if outputs[False].get(field, ()) != outputs[True].get(field, ()):
                failures.append({"mode": "parity", "detail": f"{field} differs between index and query modes"})
        case_passes[case["case_id"]] = not failures
        if failures:
            mismatches.append({
                "case_id": case["case_id"],
                "language": case["language"],
                "risk_group": case["risk_group"],
                "input_style": case["input_style"],
                "status": case["status"],
                "paired_concept": case.get("paired_concept"),
                "text": case["text"],
                "rationale": case["rationale"],
                "failures": failures,
                "observed": {mode_name: {key: list(value) for key, value in fields.items()} for mode_name, fields in (("query", outputs[False]), ("index", outputs[True]))},
            })

    summaries: dict[str, dict[str, dict[str, int]]] = {}
    for dimension in ("language", "risk_group", "input_style"):
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in cases:
            groups[str(case[dimension])].append(case)
        summaries[dimension] = {
            key: {
                "cases": len(group),
                "contract_cases": sum(case["status"] == "contract" for case in group),
                "contract_passed": sum(case["status"] == "contract" and case_passes[case["case_id"]] for case in group),
                "contract_mismatched": sum(case["status"] == "contract" and not case_passes[case["case_id"]] for case in group),
                "challenge_cases": sum(case["status"] == "challenge" for case in group),
                "challenge_mismatched": sum(case["status"] == "challenge" and not case_passes[case["case_id"]] for case in group),
            }
            for key, group in sorted(groups.items())
        }
    contract_mismatches = [item for item in mismatches if item["status"] == "contract"]
    challenge_mismatches = [item for item in mismatches if item["status"] == "challenge"]
    summaries["status"] = {
        status: {
            "cases": sum(case["status"] == status for case in cases),
            "mismatched": sum(not case_passes[case["case_id"]] for case in cases if case["status"] == status),
        }
        for status in ("contract", "challenge")
    }
    return {
        "fixture_cases": len(cases),
        "analyzer_runs": len(cases) * 2,
        "mismatch_cases": len(mismatches),
        "contract_mismatch_cases": len(contract_mismatches),
        "challenge_mismatch_cases": len(challenge_mismatches),
        "known_limitations": [
            {"case_id": case["case_id"], "limitation": case["known_limitation"]}
            for case in cases if case.get("known_limitation")
        ],
        "summaries": summaries,
        "mismatches": mismatches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit non-zero when a contract case mismatches")
    parser.add_argument("--profile", choices=("medical-no-folded-v1", "folded-v0"), default="medical-no-folded-v1")
    parser.add_argument("--fixture", type=Path, help="JSONL fixture path; defaults to the selected profile fixture")
    parser.add_argument("--json-report", type=Path, help="write full diagnostic report to this path")
    args = parser.parse_args(argv)

    fixture = args.fixture or (FIXTURE if args.profile == "medical-no-folded-v1" else LEGACY_FIXTURE)
    cases = load_cases(fixture, profile=args.profile)
    report = run_diagnostics(cases, MedicalAnalyzer(Lexicon()))
    print(f"Cases: {report['fixture_cases']} | analyzer runs: {report['analyzer_runs']}")
    print(f"Mismatch cases: {report['mismatch_cases']} | contract mismatches: {report['contract_mismatch_cases']}")
    for item in report["known_limitations"]:
        print(f"Known limitation {item['case_id']}: {item['limitation']}")
    for dimension in ("language", "risk_group", "input_style", "status"):
        print(f"\nBy {dimension}:")
        for name, counts in report["summaries"][dimension].items():
            if dimension == "status":
                print(f"  {name}: {counts['cases']} cases, {counts['mismatched']} mismatches (challenge results are diagnostic, not passes)")
            else:
                print(
                    f"  {name}: contract {counts['contract_passed']}/{counts['contract_cases']} pass, "
                    f"{counts['contract_mismatched']} contract mismatches; "
                    f"challenge {counts['challenge_cases']} cases, {counts['challenge_mismatched']} mismatches (not scored as passes)"
                )
    for item in report["mismatches"]:
        print(f"\n{item['case_id']} [{item['status']}; {item['language']}/{item['risk_group']}/{item['input_style']}]")
        print(f"  input: {item['text']}")
        for failure in item["failures"]:
            print(f"  {failure['mode']}: {failure['detail']}")
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nFull report: {args.json_report}")
    if not args.strict:
        print("\nDiagnostic mode: mismatches are reported, not suppressed. Use --strict to gate contract cases.")
    return 1 if args.strict and report["contract_mismatch_cases"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
