"""Read-only paired comparison and a casebook for the approved test sample."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import hashlib
from itertools import zip_longest
import json
from pathlib import Path
import re

from sbtc.Scripts.Clawler.verbatim import clean_to_verbatim

ROOT = Path(__file__).resolve().parents[5]
REVIEW_IDS = {211401, 6333519, 5714388, 6480634, 7147848, 269380, 1067218,
              2335124, 279805, 5846763, 7156587, 6248072, 3078554, 2531165,
              2996442, 4265827, 4271202, 4050109, 264212, 6954391, 218831,
              1128713, 283585, 263670, 259400, 5467809, 223012, 244904,
              1138672, 5180531, 5294437, 7286850}
NOTES = {
    211401: "37,5 độ C: baseline cắt ở comma; bản mới giữ câu.",
    6333519: "Tỷ lệ randomisation (1:1) và câu >50 units được giữ nguyên.",
    5714388: "$10,100 không bị cắt ở thousands separator.",
    6480634: "11,6 và nội dung French/Spanish được giữ; không kế thừa en cho đoạn dài.",
    7147848: "Biểu thức ES/CI có ngoặc được giữ nguyên.",
    269380: "Cảm giác tội lỗi: đi cùng nội dung theo sau.",
    1067218: "病情分析/指导意见 gắn body; answer có question_span nguồn.",
    2335124: "Bio có marker đôi được exclude, câu trả lời vẫn index.",
    279805: "TOC/menu và title/date trùng có ledger; title giữ trong context metadata.",
    5846763: "Title dài 122 chars gắn với thân, không tạo child title riêng.",
    7156587: "Abstract EN/ZH có vùng riêng, không overlap qua transition.",
    6248072: "Entries O/P giữ record; đây là chương trình hội nghị, không phải full nghiên cứu.",
    3078554: "Menu ICD dày và các render copy được exclude bằng marker+shape.",
    2531165: "Hàng bảng bệnh–triệu chứng–khoa giữ cùng atom, không tự sinh cột.",
    2996442: "Navigation/attribution/footer sau body được exclude theo layout.",
    4265827: "Arrow lật trang exclude; nội dung B12 giữ nguyên.",
    4271202: "Giữ nguyên liệu/liều và quoted snippets; không xóa toàn tail theo 原文 →.",
    4050109: "Drug page sang catalogue; manufacturer/approval/package giữ record riêng.",
    264212: "24.7mg không phải heading số thứ tự.",
    6954391: "Regression: title + abstract ngắn vẫn một chunk.",
    218831: "Regression: câu đầy đủ, cuối tài liệu có dấu ! nguyên bản.",
    1128713: "Regression: QA ngắn vẫn một chunk đầy đủ.",
    283585: "Ngoặc MRSA qua anchors/newline giữ cùng atom.",
    263670: "Ngoặc tiêu chảy qua newline không tạo child bắt đầu bằng dấu đóng ngoặc.",
    259400: "2,2 không ăn G của Gợi ý vào numeric span.",
    5467809: "Ngoặc lỗi nguồn không ghép xuyên hai abstract; có warning review.",
    223012: "Câu dẫn dài kết colon phải đi cùng body.",
    244904: "Câu dẫn nguyên nhân ở trẻ không treo ở cuối child.",
    1138672: "Lời người hỏi chào bác sĩ nằm trong question, không gán vào answer.",
    5180531: "Koes et al. đi cùng [33] reviewed, không đóng child ở tên tác giả viết tắt.",
    5294437: "i.v. đi cùng tên thuốc Nytroglicerin nguyên bản.",
    7286850: "vs. giữ cùng vế so sánh laparoscopic theo sau.",
}


def rows(directory):
    for part in sorted(directory.glob("part-*.jsonl")):
        with part.open() as stream:
            for number, raw in enumerate(stream, 1):
                yield json.loads(raw), part, number


def metrics(output, source):
    children = output["children"]
    boundaries = sorted({c[k] for c in children for k in ("start_char", "end_char")})
    cuts = []
    # Independent numeric detector, rather than the production atom metadata.
    for match in re.finditer(r"\d+(?:[.,:]\d+)+", source):
        index = bisect_right(boundaries, match.start())
        if index < len(boundaries) and boundaries[index] < match.end():
            cuts.append(dict(start_char=match.start(), end_char=match.end(), text=match.group(), boundary=boundaries[index]))
    return dict(chunks=len(children), parents=len(output["parents"]),
                short_50=sum(c["unit_count"] < 50 for c in children),
                short_100=sum(c["unit_count"] < 100 for c in children),
                oversized=sum(c["unit_count"] > 300 for c in children),
                unit_sum=sum(c["unit_count"] for c in children), numeric_cuts=len(cuts),
                delimiter_end_flags=sum(c["chunk_text"].rstrip().endswith(tuple(",，:：;；、")) for c in children[:-1])), cuts


def evaluate(output_dir, baseline_dir, report_dir):
    source_path = ROOT / "data_final/test_20k.jsonl"
    profiles = defaultdict(lambda: {"documents": 0, "baseline": Counter(), "format": Counter()})
    overall = {"baseline": Counter(), "format": Counter()}
    cases, oversized, warnings, numeric_examples = [], [], [], []
    digest, records = hashlib.sha256(), 0
    with source_path.open("rb") as stream:
        for number, values in enumerate(zip_longest(stream, rows(baseline_dir), rows(output_dir)), 1):
            raw, before_item, after_item = values
            if any(v is None for v in values): raise AssertionError("Input/output counts differ")
            digest.update(raw)
            record, (before, before_path, before_line), (after, after_path, after_line) = json.loads(raw), before_item, after_item
            assert before["doc_id"] == after["doc_id"] == record["id"]
            assert before["url"] == after["url"] == record["url"]
            assert before["input_line"] == after["input_line"] == number
            records += 1
            if after["status"] != "ok":
                assert before["status"] == after["status"] == "skipped"
                continue
            source = clean_to_verbatim(record["text"])
            profile = profiles[after["profile"]]
            profile["documents"] += 1
            for name, output in (("baseline", before), ("format", after)):
                stats, numeric_cuts = metrics(output, source)
                profile[name].update(stats)
                overall[name].update(stats)
                if numeric_cuts: numeric_examples.append(dict(strategy=name, doc_id=record["id"], input_line=number, cuts=numeric_cuts))
            for child in after["children"]:
                if child["unit_count"] > 300:
                    oversized.append(dict(doc_id=record["id"], input_line=number, output_file=str(after_path), output_line=after_line,
                                          chunk_order=child["chunk_order"], units=child["unit_count"], reason=child["oversized_reason"],
                                          start_char=child["start_char"], end_char=child["end_char"], head=child["chunk_text"][:180]))
            if after["format_warnings"]:
                warnings.append(dict(doc_id=record["id"], input_line=number, warnings=after["format_warnings"]))
            if record["id"] in REVIEW_IDS:
                cases.append(dict(doc_id=record["id"], input_line=number, source=source, baseline=before, format=after,
                                  baseline_file=str(before_path), baseline_line=before_line, output_file=str(after_path), output_line=after_line))
    assert records == 20000
    assert digest.hexdigest() == "9fdacfb07ecc1757c53c5b03bd41d31358c4a0db74fea785a6a62f90cfe8bf43"
    assert overall["format"]["numeric_cuts"] == 0
    comparison = dict(records=records, input_sha256=digest.hexdigest(), overall=overall, profiles=profiles,
                      output_bytes=sum(p.stat().st_size for p in output_dir.glob("part-*.jsonl")),
                      baseline_bytes=sum(p.stat().st_size for p in baseline_dir.glob("part-*.jsonl")))
    report_dir.mkdir(exist_ok=True, parents=True)
    for name, value in (("comparison.json", comparison), ("review_cases.json", cases), ("oversized_review.json", oversized),
                        ("warnings_review.json", warnings), ("numeric_boundary_comparison.json", numeric_examples)):
        (report_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    lines = ["# Casebook trước–sau format chunking", "", "Các trích đoạn dưới đây là source nguyên bản. Dấu cắt trong snippet chỉ để trình bày; file output chứa đầy đủ source slice.", ""]
    for case in cases:
        doc_id, before, after = case["doc_id"], case["baseline"], case["format"]
        lines += [f"## doc_id {doc_id} — {after['profile']}", "", NOTES[doc_id], "",
                  f"[Nguồn dòng {case['input_line']}]({source_path}:{case['input_line']}) · [Baseline]({case['baseline_file']}:{case['baseline_line']}) · [Output mới]({case['output_file']}:{case['output_line']})", "",
                  f"Chunks {len(before['children'])} → {len(after['children'])}; sizes mới: {[c['unit_count'] for c in after['children']]}", "",
                  f"Languages: {sorted({s['language'] for s in after['content_language_spans']})}; exclusions: {[s['rule_id'] for s in after['excluded_spans']]}", ""]
        if doc_id in (211401, 6333519, 5714388, 6480634):
            expression = {211401: "37,5", 6333519: "(1:1)", 5714388: "$10,100", 6480634: "11,6"}[doc_id]
            position = case["source"].index(expression)
            old = next(c for c in before["children"] if c["start_char"] <= position < c["end_char"])
            new = next(c for c in after["children"] if c["start_char"] <= position < c["end_char"])
            lines += ["Baseline, đoạn cuối:", "```text", old["chunk_text"][-220:], "```", "", "Bản mới, source quanh biểu thức:", "```text",
                      case["source"][max(new["start_char"], position - 120):min(new["end_char"], position + 220)], "```", ""]
        else:
            lines += ["Child đầu tiên mới:", "```text", after["children"][0]["chunk_text"][:500], "```", ""]
    (report_dir / "CASEBOOK.md").write_text("\n".join(lines))
    print(json.dumps({"records": records, "overall": overall, "review_cases": len(cases), "oversized": len(oversized)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.output.resolve(), args.baseline.resolve(), args.report_dir.resolve())
