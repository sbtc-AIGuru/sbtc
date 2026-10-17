"""Verify multilingual chunk cleaning without losing medical content."""

from pathlib import Path
import sys
import unicodedata

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Scripts.ETL_Pipeline.data_preprocess import ETL


@pytest.mark.parametrize(("text", "expected"), [
    (
        "  Bệnh nhân\u00a0uống  5 mg/kg. 🚀\r\n((Ảnh: minh họa))\nTái khám.  ",
        "Bệnh nhân uống 5 mg/kg.\nTái khám.",
    ),
    (
        "  Patients\t receive 5 mg/kg. 🩺 (Photo: Example)\nFollow-up in 2 weeks.",
        "Patients receive 5 mg/kg.\nFollow-up in 2 weeks.",
    ),
    (
        "患者体温 ≥ 38°C。🩺\n（图片来源：示例）\n\u3000建议及时就医。",
        "患者体温 ≥ 38°C。\n建议及时就医。",
    ),
    (
        "繁體中文：體溫 38°C。\n圖片來源：醫院\n建議就醫。",
        "繁體中文：體溫 38°C。\n建議就醫。",
    ),
    (
        "Liều dùng / Dosage / 用量：5 mg/kg。\nHPV阳性; CIN I-II; không sốt.",
        "Liều dùng / Dosage / 用量：5 mg/kg。\nHPV阳性; CIN I-II; không sốt.",
    ),
])
def test_multilingual_chunks(text: str, expected: str) -> None:
    assert ETL().ETL_Pipeline(text) == expected


@pytest.mark.parametrize("credit", [
    "(Ảnh: minh họa)", "((Ảnh: minh họa))", "（Nguồn ảnh：bệnh viện）",
    "(PHOTO CREDIT: Example)", "(Image credits: Example)",
    "（图片来源：医院）", "(图源: 医院)", "（圖片來源：醫院）", "（攝影：作者）",
    "Ảnh: minh họa", "Photo: Example", "图片来源：医院", "圖片來源：醫院",
])
def test_image_credits_in_three_languages(credit: str) -> None:
    assert ETL().ETL_Pipeline(f"First line.\n{credit}\n最后一行。") == "First line.\n最后一行。"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r", "\u2028"])
def test_standalone_credit_with_different_line_endings(newline: str) -> None:
    text = newline.join(["First line.", "Photo: Example", "最后一行。"])
    assert ETL().ETL_Pipeline(text) == "First line.\n最后一行。"


def test_unicode_and_medical_notation_are_preserved() -> None:
    text = "Tiếng Việt có dấu; 中文；繁體中文; English.\n"
    text += "H₂O; μg; SpO₂ < 90%; ≥ 38°C; ± 0.5; 10⁹/L; 120/80 mmHg.\n"
    text += "♀ ♂ ↔; (n=30); [12]; 2024-01-02; E11.9; p < 0.05."
    assert ETL().ETL_Pipeline(unicodedata.normalize("NFD", text)) == text


def test_invisible_characters_and_whitespace() -> None:
    text = "\ufeffTiếng\u200bViệt\x00 có\u202f dấu\r\n\r\n"
    text += "inter\u00advention\u2060\tworks.\n\u3000中文。"
    assert ETL().ETL_Pipeline(text) == "Tiếng Việt có dấu\nintervention works.\n中文。"


def test_emoji_sequences_and_keycap_numbers() -> None:
    assert ETL().ETL_Pipeline("👩🏽‍⚕️ 1️⃣ dose; 2️⃣ doses. 🇻🇳") == "1 dose; 2 doses."


def test_sentence_punctuation_and_first_sentence_are_preserved() -> None:
    text = "First sentence! Second sentence? 中文句子。\nCâu đầu tiên. Câu tiếp theo!"
    assert ETL().ETL_Pipeline(text) == text


def test_normal_parentheses_and_credit_words_are_preserved() -> None:
    text = "MRI (2024); 对照组（n=30）；Ảnh hưởng của thuốc.\nPhoto sensitivity is a symptom."
    assert ETL().ETL_Pipeline(text) == text


@pytest.mark.parametrize("text", ["", " \t\r\n\u3000", "🚀\n（图片来源：医院）"])
def test_empty_chunks(text: str) -> None:
    assert ETL().ETL_Pipeline(text) == ""


@pytest.mark.parametrize("text", [None, 123, b"chunk", {"chunk_text": "text"}])
def test_requires_a_chunk_string(text: object) -> None:
    with pytest.raises(TypeError, match="string"):
        ETL().ETL_Pipeline(text)
