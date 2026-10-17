"""Clean individual Vietnamese, English, and Chinese chunk strings."""

import re
import unicodedata

import emoji
from whitespace_normalizer import normalize_whitespace


class ETL:
    """Normalize chunk text without changing its language or medical notation."""

    def __init__(self) -> None:
        credit_label = (
            r"(?:ảnh|nguồn ảnh|hình ảnh|photos?|photo credits?|image credits?|"
            r"picture credits?|图片来源|圖片來源|图源|圖源|图片|圖片|照片|摄影|攝影)"
        )
        credit = rf"{credit_label}\s*[:：]\s*[^()（）\r\n]{{1,150}}"
        self.PHOTO_PATTERN = re.compile(
            rf"\(\(\s*{credit}\)\)|\(\s*{credit}\)|（\s*{credit}）",
            flags=re.IGNORECASE,
        )
        self.PHOTO_LINE_PATTERN = re.compile(
            rf"\s*{credit}\s*",
            flags=re.IGNORECASE,
        )

    def _remove_icon(self, text: str) -> str:
        def replace_icon(icon: str, _match: dict) -> str:
            symbol = icon.replace("\ufe0f", "").replace("\ufe0e", "")
            # Emoji recognition also includes scientific symbols and keycap digits.
            if symbol in {"♀", "♂", "⚕", "↔", "↕", "↖", "↗", "↘", "↙", "©", "®", "™"}:
                return symbol
            if symbol.endswith("\u20e3"):
                return symbol[:-1]
            return ""

        return emoji.replace_emoji(text, replace=replace_icon)

    def _whitespace_normalization(self, text: str) -> str:
        text = "\n".join(re.sub(r"\s+", " ", line) for line in text.splitlines())
        return normalize_whitespace(text=text)

    def _remove_image_citation(self, text: str) -> str:
        text = self.PHOTO_PATTERN.sub(" ", text)
        return "\n".join(
            line for line in text.splitlines()
            if not self.PHOTO_LINE_PATTERN.fullmatch(line)
        )

    def _normalize_unicode(self, text: str) -> str:
        text = text.replace("\u200b", " ")
        text = re.sub(r"[\ufeff\u00ad\u200c\u200d\u2060]", "", text)
        return re.sub(r"[\x00-\x08\x0e-\x1f\x7f-\x84\x86-\x9f]", " ", text)

    def ETL_Pipeline(self, text: str) -> str:
        """Return cleaned text, preserving nonempty lines and medical content.

        Accept a single chunk string in any of the three languages, including
        mixed-language text. No language detection or word segmentation is needed.
        """
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        # NFC keeps Vietnamese accents, Chinese characters, and units like H₂O.
        text = unicodedata.normalize("NFC", text)
        # Remove whole emoji sequences before removing invisible joiners.
        text = self._remove_icon(text)
        text = self._normalize_unicode(text)
        text = self._remove_image_citation(text)
        return self._whitespace_normalization(text)


if __name__ == "__main__":
    etl = ETL()
    samples = [
        "Bệnh nhân uống  5 mg/kg. 🚀\n((Ảnh: minh họa))",
        "Patients receive  5 mg/kg; SpO₂ < 90%. 🩺 (Photo: Example)",
        "患者体温 ≥ 38°C。🩺\n（图片来源：示例）\n建议及时就医。",
    ]
    for text in samples:
        print(etl.ETL_Pipeline(text))
