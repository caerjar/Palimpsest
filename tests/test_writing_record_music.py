"""The Writing Record's music engine keeps one sound path and safe defaults.

The page is JavaScript, so these are structural checks on the asset; what the
music does is exercised in the studio's Playwright specs.
"""
import re
import unittest
from pathlib import Path

PAGE = (Path(__file__).resolve().parent.parent
        / "palimpsest" / "engine" / "assets" / "writing-record.html").read_text(encoding="utf-8")


def body(name: str) -> str:
    """Source of a top-level `function name(...)` or `async function name(...)`."""
    m = re.search(rf"^(?:async )?function {name}\(.*?^}}", PAGE, re.S | re.M)
    assert m, f"no function {name}"
    return m.group(0)


class TestOneSoundPath(unittest.TestCase):
    def test_live_and_wav_both_schedule_through_scheduleStep(self):
        for fn in ("sound", "renderWAV"):
            src = body(fn)
            self.assertIn("scheduleStep(", src, fn)
            for old in ("playOrnament", "playMelody", "ornamentEvents"):
                self.assertNotIn(old, src, f"{fn} still calls {old}")

    def test_score_draws_deletions_from_noteEventsFor(self):
        src = body("glyphsFor")
        self.assertNotIn("ornamentEvents(", src)
        self.assertIn("noteEventsFor(it.e, it.step)", src)


class TestDefaults(unittest.TestCase):
    """The workbench and the demo sound as they did: every new option ships off."""

    def test_new_music_options_default_off(self):
        self.assertIn("paragraphKey:0, deleteFall:false, swell:{ on:false", PAGE)
        self.assertIn("toneMove:0 }", PAGE)


class TestSounds(unittest.TestCase):
    def setUp(self):
        m = re.search(r"^const SOUNDS = \{(.*?)^\};", PAGE, re.S | re.M)
        self.assertTrue(m)
        self.sounds = m.group(1)
        self.instruments = set(re.findall(r"^  (\w+):\{ oscs", PAGE, re.M))
        scales = re.search(r"^const SCALES = \{(.*?)^\};", PAGE, re.S | re.M).group(1)
        self.scales = {q or b for q, b in re.findall(r"(?:'([^']+)'|(\w+)):[\[{]", scales)} - {"cents"}

    def test_names_are_safe_to_share(self):
        names = re.findall(r"^  (?:'([^']+)'|(\w+)):\s*\{", self.sounds, re.M)
        self.assertEqual(len(names), 6)
        for quoted, bare in names:
            self.assertRegex(quoted or bare, r"^[^<>&\"'`\\]{1,64}$")

    def test_named_instruments_and_scales_exist(self):
        for inst in re.findall(r"instrument:'([^']+)'", self.sounds):
            self.assertIn(inst, self.instruments)
        for sc in re.findall(r"scale:'([^']+)'", self.sounds):
            self.assertIn(sc, self.scales)


if __name__ == "__main__":
    unittest.main()
