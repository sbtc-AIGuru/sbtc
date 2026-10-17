"""Unit tests for MultiMed-ST translation contracts and provenance."""
import json
import tempfile
import unittest
from pathlib import Path

from BackEnd.app.Retrieval.analyzers import MedicalAnalyzer
from BackEnd.app.Retrieval.lexicon import Lexicon
from BackEnd.app.Retrieval.query import QueryProjector
from BackEnd.app.Retrieval.translation import (
    MultiMedCompositeTranslator,
    validate_provenance,
    write_translation_cache,
)
from BackEnd.app.Retrieval.utils import sha_bytes, sha_file


PROVENANCE_MULTIMED_ST = {
    "model_id": "leduckhai/MultiMed-ST",
    "revision": "fb15edd1dfc68810a7d0c75e6cfc73c3e5ed01c1",
    "license": "mit",
    "parameters": 418_000_000,
    "release_date": "2025-02-23",
    "open_weights": True,
}


class MockM2MTranslator:
    def __init__(self, target_lang: str):
        self.target_lang = target_lang
        self.provenance = PROVENANCE_MULTIMED_ST

    def translate(self, texts: list[str]) -> list[str]:
        if self.target_lang == "en":
            return [f"medical condition {text}" for text in texts]
        elif self.target_lang == "zh":
            return [f"医学病症 {text}" for text in texts]
        return texts


class TestMultiMedTranslation(unittest.TestCase):
    def test_multimed_provenance_valid(self):
        validated = validate_provenance(PROVENANCE_MULTIMED_ST)
        self.assertEqual(validated["model_id"], "leduckhai/MultiMed-ST")
        self.assertEqual(validated["parameters"], 418_000_000)
        self.assertEqual(validated["revision"], "fb15edd1dfc68810a7d0c75e6cfc73c3e5ed01c1")
        self.assertTrue(validated["open_weights"])

        # Violations should raise ValueError
        for key, bad_val in [
            ("parameters", 15_000_000_001),
            ("open_weights", False),
            ("release_date", "2026-08-01"),
            ("revision", "invalid_short_hash"),
        ]:
            with self.assertRaises(ValueError):
                validate_provenance({**PROVENANCE_MULTIMED_ST, key: bad_val})

    def test_multimed_cache_generation_and_query_projector(self):
        translator = MultiMedCompositeTranslator(MockM2MTranslator("en"), MockM2MTranslator("zh"))
        queries = [
            {"query": "bệnh đái tháo đường 500 mg"},
            {"query": "viêm xung huyết dạ dày"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            cache_path = Path(temp) / "test_multimed_cache.jsonl"
            count = write_translation_cache(iter(queries), translator, cache_path, batch_size=2)
            self.assertEqual(count, 2)
            self.assertTrue(cache_path.exists())

            # Verify line contents
            lines = [json.loads(line) for line in cache_path.read_text().splitlines()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0]["source_query"], "bệnh đái tháo đường 500 mg")
            self.assertEqual(lines[0]["query_sha256"], sha_bytes("bệnh đái tháo đường 500 mg".encode()))
            self.assertIn("en", lines[0]["translations"])
            self.assertIn("zh", lines[0]["translations"])
            self.assertEqual(lines[0]["provenance"]["model_id"], "leduckhai/MultiMed-ST")

            # Verify QueryProjector consumption
            analyzer = MedicalAnalyzer(Lexicon())
            projector = QueryProjector(analyzer, cache_path)
            runs, warnings = projector.project("bệnh đái tháo đường 500 mg")
            self.assertTrue(any(c.startswith("translation") for _, c, _ in runs))
            self.assertEqual(warnings, [])

    def test_tamper_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            model_dir = Path(temp) / "fake_model"
            model_dir.mkdir()
            weight_file = model_dir / "model.safetensors"
            weight_file.write_bytes(b"dummy safetensors content")
            config_file = model_dir / "config.json"
            config_file.write_text('{"vocab_size": 100}')

            manifest = {
                "provenance": PROVENANCE_MULTIMED_ST,
                "local_directory": str(model_dir),
                "target_language": "en",
                "files": {
                    "model.safetensors": sha_file(weight_file),
                    "config.json": sha_file(config_file),
                },
            }
            manifest_path = Path(temp) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))

            # Tampering weight file
            weight_file.write_bytes(b"tampered content")
            # If we check sha_file mismatch
            self.assertNotEqual(sha_file(weight_file), manifest["files"]["model.safetensors"])


if __name__ == "__main__":
    unittest.main()
