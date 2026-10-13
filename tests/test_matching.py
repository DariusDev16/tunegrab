"""Testes do nucleo de matching do TuneGrab (match, normalizacao, filenames).

Roda so com a stdlib:
    python -m unittest discover tests
    python tests/test_matching.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tunegrab import (  # noqa: E402
    Track, clean_title, norm, sanitize, score_candidate, version_tags,
)


class TestNorm(unittest.TestCase):
    def test_strips_boilerplate(self):
        cases = [
            ("Richie Campbell (ft. Plutonio) - C'est La Vie (Official Video)",
             "richie campbell c est la vie"),
            ("The Game - Hate It Or Love It feat. 50 Cent", "the game hate it or love it"),
            ("King Von - Block (Lyrics)", "king von block"),
            ("NEFFEX - Fight Back (Official Music Video)", "neffex fight back"),
            ("50 Cent - P.I.M.P.", "50 cent p i m p"),
            ("G-Unit - Poppin' Them Thangs", "g unit poppin them thangs"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(norm(raw), expected)

    def test_feat_does_not_eat_the_title(self):
        """Regressao: um 'feat' guloso ate o fim da string apagava o titulo."""
        got = norm("C'est La Vie (ft. Plutonio)")
        self.assertIn("vie", got)
        self.assertNotEqual(got, "richie campbell")

    def test_strips_accents(self):
        self.assertEqual(norm("Plutónio - Acordar"), norm("Plutonio - Acordar"))


class TestCleanTitle(unittest.TestCase):
    def test_removes_feature_and_suffixes(self):
        cases = {
            "C'est La Vie (feat. Plutonio)": "C'est La Vie",
            "Save That Shit [Official Video]": "Save That Shit",
            "Message (feat. NLE Choppa)": "Message",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(clean_title(raw), expected)


class TestVersionTags(unittest.TestCase):
    def test_detects_alternative_versions(self):
        self.assertEqual(version_tags("X - Y (Ao Vivo)"), {"vivo"})
        self.assertEqual(version_tags("Z - Remix"), {"remix"})
        self.assertEqual(version_tags("Q - Song (Acoustic)"), {"acoustic"})
        self.assertEqual(version_tags("King Von - Block"), set())


class TestScore(unittest.TestCase):
    def test_prefers_correct_over_wrong_song(self):
        """Regressao real: o match correto de C'est La Vie perdia para um
        video errado porque o limpador de ruido apagava o titulo."""
        t = Track(2, "C'est La Vie (feat. Plutonio)", ["Richie Campbell", "Plutonio"], 189)
        right = score_candidate("Richie Campbell - C'est La Vie (Official Video)", 226, t)
        wrong = score_candidate("Richie Campbell - Look What You've Done", 218, t)
        self.assertGreater(right, wrong)
        self.assertGreater(right, 0.55)

    def test_penalises_unrequested_live_version(self):
        t = Track(1, "Acordar", ["Plutonio"], 197)
        live = score_candidate("Plutonio - Acordar (Ao Vivo)", 260, t)
        studio = score_candidate("Plutonio - Acordar", 196, t)
        self.assertGreater(studio, live)

    def test_does_not_penalise_requested_live_version(self):
        t = Track(9, "Hurt (Live)", ["NIN"], 260)
        live = score_candidate("NIN - Hurt (Live)", 260, t)
        studio = score_candidate("NIN - Hurt (Official Video)", 247, t)
        self.assertGreaterEqual(live, studio)

    def test_tolerates_duration_mismatch(self):
        """O YouTube raramente tem a duracao do Spotify; o titulo deve vencer."""
        t = Track(1, "Acordar", ["Plutonio"], 197)
        near = score_candidate("Plutonio - Acordar", 196, t)
        far = score_candidate("Plutonio - Acordar (Video Oficial)", 230, t)
        self.assertGreater(near, far)
        self.assertGreater(far, 0.55)

    def test_unrelated_track_scores_low(self):
        t = Track(1, "Acordar", ["Plutonio"], 197)
        self.assertLess(score_candidate("completely different song", 200, t), 0.55)

    def test_empty_candidate_scores_zero(self):
        t = Track(1, "Acordar", ["Plutonio"], 197)
        self.assertEqual(score_candidate("", None, t), 0.0)


class TestSanitize(unittest.TestCase):
    def test_strips_windows_illegal_chars(self):
        self.assertEqual(sanitize('AC/DC: Back? *Black*'), "ACDC Back Black")

    def test_reserved_names(self):
        self.assertEqual(sanitize("CON"), "_CON")
        self.assertEqual(sanitize("LPT1"), "_LPT1")

    def test_trailing_dots_and_spaces(self):
        self.assertEqual(sanitize("Trailing dots..."), "Trailing dots")

    def test_empty_falls_back(self):
        self.assertEqual(sanitize("   "), "untitled")

    def test_respects_max_length(self):
        self.assertLessEqual(len(sanitize("a" * 500, max_len=60)), 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)