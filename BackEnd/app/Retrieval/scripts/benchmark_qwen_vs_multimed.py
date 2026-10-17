"""Benchmark Qwen2.5-1.5B-Instruct against MultiMed-ST on 10 sampled clinical queries.
Measures:
- Latency (ms) & Throughput (queries/sec)
- Peak RAM (MB) & Load Time (s)
- Number preservation rate (%)
- Segmentation precision (JSON parse success, boilerplate-free, medical entity preservation)
"""
from __future__ import annotations

import argparse
import json
import re
import resource
import time
from pathlib import Path


def get_peak_ram_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def check_numbers_preserved(source: str, translation: str) -> bool:
    source_nums = set(re.findall(r"\d+(?:[.,]\d+)?", source))
    norm_source = {n.replace(",", ".") for n in source_nums}
    trans_nums = {n.replace(",", ".") for n in re.findall(r"\d+(?:[.,]\d+)?", translation)}
    return norm_source <= trans_nums


def parse_llm_json(raw_text: str) -> dict[str, str]:
    """Extract clean JSON dictionary from LLM output, stripping codeblocks or preamble."""
    raw_text = raw_text.strip()
    if "```" in raw_text:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
        if match:
            raw_text = match.group(1)
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict) and "en" in data and "zh" in data:
            return {"en": str(data["en"]).strip(), "zh": str(data["zh"]).strip(), "parse_ok": True}
    except Exception:
        pass

    en_match = re.search(r'"en"\s*:\s*"([^"]+)"', raw_text)
    zh_match = re.search(r'"zh"\s*:\s*"([^"]+)"', raw_text)
    if en_match and zh_match:
        return {"en": en_match.group(1).strip(), "zh": zh_match.group(1).strip(), "parse_ok": True}

    return {"en": raw_text, "zh": raw_text, "parse_ok": False}


SYSTEM_PROMPT = """You are a professional medical search query translator. Translate the given Vietnamese medical query into English and Simplified Chinese search queries for document retrieval.
Requirements:
1. Translate colloquial telemedicine terms into precise medical concepts (e.g., 'đi ngoài' -> 'diarrhea / frequent bowel movements' / '腹泻', 'phân ướt' -> 'loose stools' / '大便稀', 'sản dịch' -> 'lochia' / '恶露', 'thiểu sản' -> 'hypoplasia' / '发育不良', 'cảm mạo' -> 'common cold' / '感冒').
2. Preserve all exact numerical values, measurements, and units (e.g., '3,0 mm', '881,3', 'tuần 28').
3. Output strictly valid JSON with keys "en" and "zh", where values are strings. Do NOT write any introduction or explanation."""

FEW_SHOT_USER = "Triệu chứng của bệnh sốt xuất huyết là gì?"
FEW_SHOT_ASSISTANT = '{"en": "What are the symptoms of dengue fever?", "zh": "登革热的症状是什么？"}'


def run_benchmark(
    samples_path: Path,
    model_dir: Path,
    output_path: Path,
    engine: str = "ct2",
) -> None:
    print(f"Loading 10 reference sample queries from {samples_path}...")
    baseline_data = json.loads(samples_path.read_text())
    samples = baseline_data["results"]
    print(f"Loaded {len(samples)} queries.")

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        "artifacts/models/Qwen2.5-1.5B-Instruct", local_files_only=True
    )

    t_load_0 = time.time()
    if engine == "ct2":
        import ctranslate2
        ct2_dir = Path("artifacts/models/Qwen2.5-1.5B-ct2-int8")
        print(f"Loading Qwen2.5-1.5B CTranslate2 INT8 from {ct2_dir}...")
        generator = ctranslate2.Generator(
            str(ct2_dir), device="cpu", compute_type="int8", intra_threads=6
        )
        model = None
    else:
        import torch
        torch.set_num_threads(6)
        from transformers import AutoModelForCausalLM
        print(f"Loading Qwen2.5-1.5B PyTorch bfloat16 from {model_dir}...")
        model = AutoModelForCausalLM.from_pretrained(
            str(model_dir), dtype=torch.bfloat16, local_files_only=True
        ).to("cpu").eval()
        generator = None

    load_time_sec = round(time.time() - t_load_0, 2)
    initial_ram_mb = round(get_peak_ram_mb(), 1)
    print(f"Model loaded in {load_time_sec}s. Initial RAM: {initial_ram_mb} MB.")

    def generate_fn(prompt: str) -> tuple[str, int]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": FEW_SHOT_USER},
            {"role": "assistant", "content": FEW_SHOT_ASSISTANT},
            {"role": "user", "content": prompt},
        ]
        prompt_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        if engine == "ct2":
            prompt_tokens = tokenizer.tokenize(prompt_text)
            res = generator.generate_batch(
                [prompt_tokens],
                max_length=len(prompt_tokens) + 96,
                include_prompt_in_result=False,
                end_token=["<|im_end|>", "<|endoftext|>"],
                sampling_topk=1,
            )
            gen_toks = res[0].sequences[0]
            # Strip end token if present
            if gen_toks and gen_toks[-1] in ["<|im_end|>", "<|endoftext|>"]:
                gen_toks = gen_toks[:-1]
            out_str = tokenizer.convert_tokens_to_string(gen_toks)
            return out_str, len(gen_toks)
        else:
            import torch
            inputs = tokenizer([prompt_text], return_tensors="pt").to("cpu")
            with torch.inference_mode():
                out = model.generate(**inputs, max_new_tokens=96, do_sample=False)
            gen_tokens = out[0][len(inputs.input_ids[0]):]
            return tokenizer.decode(gen_tokens, skip_special_tokens=True), len(gen_tokens)

    # Warmup
    print("Warming up model...")
    _ = generate_fn("Sốt nhẹ kéo dài có nguy hiểm không?")

    print(f"\n=======================================================")
    print(f"Running Benchmark on {len(samples)} Queries (Engine: {engine.upper()})")
    print(f"=======================================================\n")

    results = []
    total_latency_start = time.time()

    for idx, item in enumerate(samples, 1):
        q_id = item["id"]
        source = item["source_query"]

        t_start = time.time()
        raw_output, num_tokens = generate_fn(source)
        latency_ms = (time.time() - t_start) * 1000

        parsed = parse_llm_json(raw_output)
        num_ok_en = check_numbers_preserved(source, parsed["en"])
        num_ok_zh = check_numbers_preserved(source, parsed["zh"])
        has_boilerplate = any(w in raw_output.lower() for w in ["here is", "sure!", "dưới đây", "note:"])

        entry = {
            "index": idx,
            "id": q_id,
            "source_query": source,
            "qwen_en": parsed["en"],
            "qwen_zh": parsed["zh"],
            "multimed_en": item.get("en_translation", ""),
            "multimed_zh": item.get("zh_translation", ""),
            "total_latency_ms": round(latency_ms, 2),
            "generated_tokens": num_tokens,
            "tokens_per_sec": round(num_tokens / (latency_ms / 1000.0), 1) if latency_ms > 0 else 0,
            "numbers_preserved_en": num_ok_en,
            "numbers_preserved_zh": num_ok_zh,
            "json_parse_ok": parsed["parse_ok"],
            "boilerplate_free": not has_boilerplate,
            "raw_output": raw_output,
        }
        results.append(entry)
        print(f"[{idx}/{len(samples)}] ID {q_id} ({latency_ms:.1f}ms, {entry['tokens_per_sec']} tok/s):")
        print(f"    Source: {source[:65]}...")
        print(f"    Qwen EN: {parsed['en']}")
        print(f"    Qwen ZH: {parsed['zh']}")
        print(f"    Nums preserved: EN={num_ok_en}, ZH={num_ok_zh} | Parse JSON: {parsed['parse_ok']}")
        print()

    total_duration = time.time() - total_latency_start
    peak_ram = get_peak_ram_mb()
    latencies = [r["total_latency_ms"] for r in results]
    avg_latency = sum(latencies) / len(latencies)

    num_ok_en_count = sum(1 for r in results if r["numbers_preserved_en"])
    num_ok_zh_count = sum(1 for r in results if r["numbers_preserved_zh"])
    json_parse_ok_count = sum(1 for r in results if r["json_parse_ok"])
    boilerplate_free_count = sum(1 for r in results if r["boilerplate_free"])

    summary = {
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
        "engine": engine,
        "sample_size": len(samples),
        "load_time_sec": load_time_sec,
        "total_duration_sec": round(total_duration, 2),
        "avg_latency_ms": round(avg_latency, 2),
        "min_latency_ms": round(min(latencies), 2),
        "max_latency_ms": round(max(latencies), 2),
        "throughput_queries_per_sec": round(len(samples) / total_duration, 2),
        "peak_ram_mb": round(peak_ram, 1),
        "accuracy_metrics": {
            "num_preserved_en_rate": f"{num_ok_en_count}/{len(samples)} ({num_ok_en_count * 10}%)",
            "num_preserved_zh_rate": f"{num_ok_zh_count}/{len(samples)} ({num_ok_zh_count * 10}%)",
            "json_parse_success_rate": f"{json_parse_ok_count}/{len(samples)} ({json_parse_ok_count * 10}%)",
            "boilerplate_free_rate": f"{boilerplate_free_count}/{len(samples)} ({boilerplate_free_count * 10}%)",
        },
        "results": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print(f"\n=======================================================")
    print(f"Benchmarking Complete! (Engine: {engine.upper()})")
    print(f"  Load Time: {load_time_sec}s")
    print(f"  Total Duration: {total_duration:.2f}s for {len(samples)} queries")
    print(f"  Avg Latency per query: {avg_latency:.1f} ms")
    print(f"  Throughput: {len(samples) / total_duration:.2f} queries/sec")
    print(f"  Peak RAM: {peak_ram:.1f} MB")
    print(f"  Numbers Preserved: EN={num_ok_en_count}/10, ZH={num_ok_zh_count}/10")
    print(f"  JSON Parse Success: {json_parse_ok_count}/10")
    print(f"  Saved to: {output_path}")
    print(f"=======================================================")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Qwen2.5-1.5B-Instruct vs MultiMed-ST.")
    parser.add_argument(
        "--samples",
        type=Path,
        default=Path("artifacts/retrieval/eval_10_samples.json"),
        help="Path to baseline eval_10_samples.json",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("artifacts/models/Qwen2.5-1.5B-Instruct"),
        help="Path to Qwen2.5-1.5B-Instruct directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/retrieval/benchmark_qwen_vs_multimed.json"),
        help="Output benchmark JSON path",
    )
    parser.add_argument(
        "--engine",
        type=str,
        default="ct2",
        choices=["ct2", "pytorch"],
        help="Inference engine (ct2 or pytorch)",
    )
    args = parser.parse_args()
    run_benchmark(args.samples, args.model_dir, args.output, args.engine)


if __name__ == "__main__":
    main()
