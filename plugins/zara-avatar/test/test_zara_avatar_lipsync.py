"""Audio-driven lip sync tests: viseme estimation, smoothing, modes."""

from __future__ import annotations

import math
import struct
import unittest

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()


def sine_pcm(frequency: float, seconds: float, sample_rate: int = 16000, amplitude: float = 0.6) -> bytes:
    total = int(sample_rate * seconds)
    samples = []
    for index in range(total):
        value = amplitude * math.sin(2.0 * math.pi * frequency * index / sample_rate)
        samples.append(int(max(-1.0, min(1.0, value)) * 32767))
    return struct.pack("<%dh" % total, *samples)


SILENCE = b"\x00\x00" * 320


def dominant(frame) -> str:
    weights = frame.visemes
    return max(weights, key=lambda key: weights[key])


class AnalyzedVisemesTest(unittest.TestCase):
    def test_all_visemes_present(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer()
        frame = analyzer.process(sine_pcm(700, 0.04))
        self.assertEqual(sorted(frame.visemes), sorted(AVATAR.VISEMES))
        self.assertTrue(0.0 <= frame.amplitude <= 1.0)

    def test_low_mid_frequency_reads_as_open_mouth(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer(smoothing=0.0)
        frame = analyzer.process(sine_pcm(700, 0.04))
        self.assertEqual(dominant(frame), "a")

    def test_frequency_bands_separate_vowels(self) -> None:
        expectations = {
            350: "u",
            500: "o",
            700: "a",
            1800: "e",
            2500: "i",
        }
        for frequency, viseme in expectations.items():
            analyzer = AVATAR.VisemeAnalyzer(smoothing=0.0)
            frame = analyzer.process(sine_pcm(frequency, 0.04))
            self.assertEqual(
                dominant(frame), viseme, f"{frequency}Hz should read as {viseme}"
            )

    def test_silence_resets_mouth(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer(smoothing=0.0)
        analyzer.process(sine_pcm(700, 0.04))
        frame = analyzer.process(SILENCE)
        for weight in frame.visemes.values():
            self.assertEqual(weight, 0.0)

    def test_odd_byte_count_does_not_crash(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer()
        frame = analyzer.process(b"\x01\x00\x02")
        self.assertEqual(sorted(frame.visemes), sorted(AVATAR.VISEMES))


class SmoothingTest(unittest.TestCase):
    def test_weights_approach_gradually(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer(smoothing=0.2)
        first = analyzer.process(sine_pcm(700, 0.04))
        self.assertLess(dominant(first) and first.visemes["a"], 1.0)
        self.assertGreater(first.visemes["a"], 0.0)

    def test_repeated_chunks_converge(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer(smoothing=0.2)
        first = analyzer.process(sine_pcm(700, 0.04))
        late = first
        for _ in range(30):
            late = analyzer.process(sine_pcm(700, 0.04))
        self.assertGreater(late.visemes["a"], first.visemes["a"])
        self.assertLessEqual(late.visemes["a"], 1.0)

    def test_reset_clears_history(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer(smoothing=0.2)
        for _ in range(5):
            analyzer.process(sine_pcm(2500, 0.04))
        analyzer.reset()
        frame = analyzer.process(sine_pcm(2500, 0.04))
        self.assertLess(frame.visemes["i"], 0.5)


class GainAndVolumeTest(unittest.TestCase):
    def test_gain_scales_weak_signals(self) -> None:
        weak = sine_pcm(700, 0.04, amplitude=0.08)
        plain = AVATAR.VisemeAnalyzer(smoothing=0.0).process(weak)
        boosted = AVATAR.VisemeAnalyzer(smoothing=0.0, gain=2.0).process(weak)
        self.assertGreater(boosted.visemes["a"], plain.visemes["a"])

    def test_volume_influence_scales_with_amplitude(self) -> None:
        loud = AVATAR.VisemeAnalyzer(
            smoothing=0.0, volume_influence=1.0
        ).process(sine_pcm(700, 0.04, amplitude=0.8))
        quiet = AVATAR.VisemeAnalyzer(
            smoothing=0.0, volume_influence=1.0
        ).process(sine_pcm(700, 0.04, amplitude=0.2))
        self.assertGreater(loud.visemes["a"], quiet.visemes["a"])

    def test_zero_volume_influence_removes_amplitude_effect(self) -> None:
        loud = AVATAR.VisemeAnalyzer(
            smoothing=0.0, volume_influence=0.0
        ).process(sine_pcm(700, 0.04, amplitude=0.8))
        quiet = AVATAR.VisemeAnalyzer(
            smoothing=0.0, volume_influence=0.0
        ).process(sine_pcm(700, 0.04, amplitude=0.2))
        self.assertEqual(loud.visemes["a"], quiet.visemes["a"])


class ModesTest(unittest.TestCase):
    def test_direct_mode_uses_provided_visemes(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer(mode="direct", smoothing=0.0)
        frame = analyzer.process(
            sine_pcm(700, 0.04),
            visemes={"a": 0.1, "i": 0.9, "u": 0.0, "e": 0.0, "o": 0.0},
        )
        self.assertEqual(dominant(frame), "i")

    def test_direct_mode_silence_still_closes_mouth(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer(mode="direct", smoothing=0.0)
        frame = analyzer.process(
            SILENCE, visemes={"a": 1.0, "i": 0.0, "u": 0.0, "e": 0.0, "o": 0.0}
        )
        for weight in frame.visemes.values():
            self.assertEqual(weight, 0.0)

    def test_hybrid_mode_blends_estimated_and_provided(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer(mode="hybrid", smoothing=0.0)
        frame = analyzer.process(
            sine_pcm(700, 0.04),
            visemes={"a": 0.0, "i": 1.0, "u": 0.0, "e": 0.0, "o": 0.0},
        )
        self.assertTrue(frame.visemes["i"] > 0.0)
        self.assertTrue(frame.visemes["a"] > 0.0)

    def test_invalid_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AVATAR.VisemeAnalyzer(mode="telepathy")

    def test_sample_rate_override(self) -> None:
        analyzer = AVATAR.VisemeAnalyzer(smoothing=0.0)
        frame = analyzer.process(sine_pcm(700, 0.04, sample_rate=48000), sample_rate=48000)
        self.assertEqual(dominant(frame), "a")


if __name__ == "__main__":
    unittest.main()
