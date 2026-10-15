"""The dictionary of the window: every Russian text the window shows has its English pair.

    runtime\\python.exe tests\\test_window_i18n.py

The window on Avalonia is written in Russian and speaks English by Source\\config\\i18n.json. A text
with no pair is shown in Russian in the English window, and nothing else fails - so the watchman
of the dictionary (Source\\Tools\\check_i18n.py) is run here, with the other tests.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Source" / "Tools"))

import check_i18n  # noqa: E402


class Dictionary(unittest.TestCase):
    def test_every_russian_text_of_the_window_has_its_english_pair(self) -> None:
        self.assertEqual(check_i18n.problems(), [])
        self.assertGreater(len(check_i18n.shown()), 100)

    def test_the_watchman_tells_a_missing_pair_and_a_wrong_one(self) -> None:
        entries = json.loads(check_i18n.DICTIONARY.read_text(encoding="utf-8"))
        del entries["Отменено."]
        entries["Готово: {0}"] = {"en": "Done"}  # the hole is lost
        entries["СТОП"] = {"en": "СТОП"}  # not translated
        kept = check_i18n.DICTIONARY
        with tempfile.TemporaryDirectory() as temp:
            check_i18n.DICTIONARY = Path(temp) / "i18n.json"
            check_i18n.DICTIONARY.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
            try:
                found = "\n".join(check_i18n.problems())
            finally:
                check_i18n.DICTIONARY = kept
        for words in ("no pair: 'Отменено.'", "the holes of the pair differ: 'Готово: {0}'", "the English text holds Russian letters: 'СТОП'"):
            self.assertIn(words, found)

    def test_a_text_is_paired_as_the_window_looks_it_up(self) -> None:
        pairs = check_i18n.Pairs({"Готово.": {"en": "Ready."}, "Идёт «{0}».": {"en": '"{0}" is running.'}, "{0} из {1}": {"en": "{0} of {1}"}})
        self.assertTrue(pairs.has("Готово."))
        self.assertTrue(pairs.has("Идёт «Скачать»."))  # a template
        self.assertTrue(pairs.has("3 из 40"))
        self.assertTrue(pairs.has("Готово.\nИдёт «x»."))  # line by line, as a tooltip
        self.assertTrue(pairs.has("no Russian here"))
        self.assertFalse(pairs.has("Не готово."))

    def test_a_string_of_the_code_is_read_as_it_is_shown(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "Sample.cs"
            file.write_text('// "Комментарий" не читается\nvar a = "Путь report\\\\links.txt готов";\nvar b = $"Идёт {name}: {count} шт.";\n'
                            'var c = @"Дословная ""строка""";\nvar d = "no Russian";\n', encoding="utf-8")
            self.assertEqual(check_i18n.csharp_texts(file), ["Путь report\\links.txt готов", "Идёт {0}: {1} шт.", 'Дословная "строка"'])


if __name__ == "__main__":
    unittest.main()
