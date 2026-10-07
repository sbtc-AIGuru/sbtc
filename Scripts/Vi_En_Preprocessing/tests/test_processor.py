"""Verify the Python API and its existing C++ preprocessing behavior."""

import unittest

from processor import Processor


class ProcessorTests(unittest.TestCase):
    """Exercise Unicode conversion, validation, and reusable native instances."""

    def setUp(self) -> None:
        self.processor = Processor()

    def test_existing_cleaning_behavior(self) -> None:
        cases = [
            ("", ""),
            ("Hello! Some  text.", "Some text."),
            ("xin chào! Nội  dung.", "Nội dung."),
            ("hello", ""),
            ("Bệnh nh\ufffdn bị sốt.", "Bệnh nh n bị sốt."),
            ("<b>Nội dung</b>", "Nội dung "),
            ('<a title="x > y">Nội dung</a>', "Nội dung "),
            ("Nội dung tiếng Việt có dấu.", "Nội dung tiếng Việt có dấu."),
            ("alpha\x00beta", "alpha\x00beta"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.processor.clean_text(text), expected)

    def test_input_is_unchanged(self) -> None:
        text = "Hello! Some  text."
        self.assertEqual(self.processor.clean_text(text=text), "Some text.")
        self.assertEqual(text, "Hello! Some  text.")

    def test_rejects_non_string_inputs(self) -> None:
        for value in (None, 123, b"text", ["text"]):
            with self.subTest(value=value), self.assertRaises(TypeError):
                self.processor.clean_text(value)

    def test_rejects_invalid_arguments(self) -> None:
        with self.assertRaises(TypeError):
            Processor("unexpected")
        with self.assertRaises(TypeError):
            Processor(text="unexpected")
        with self.assertRaises(TypeError):
            self.processor.clean_text()
        with self.assertRaises(TypeError):
            self.processor.clean_text("text", "extra")

    def test_invalid_unicode_raises_python_exception(self) -> None:
        with self.assertRaises(UnicodeEncodeError):
            self.processor.clean_text("\ud800")

    def test_instances_have_independent_lifetimes(self) -> None:
        for _ in range(1000):
            other = Processor()
            self.assertEqual(other.clean_text("hello"), "")
        self.assertEqual(self.processor.clean_text("Some  text."), "Some text.")


if __name__ == "__main__":
    unittest.main()
