from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import content_variety as cv  # noqa: E402


class FindRepetitionsTests(unittest.TestCase):
    def test_same_opening_similar_topic_and_overused_cta(self):
        items = [
            {"title": "Como escolher o perfume certo para o verão", "hook": "Você sabia que o calor muda tudo?", "caption_draft": "Texto. Comenta aqui embaixo!"},
            {"title": "Perfume para o verão: como escolher o certo", "hook": "Calor e fixação andam juntos", "caption_draft": "Texto. Comenta aqui embaixo!"},
            {"title": "Bastidor da curadoria em Paris", "hook": "Você sabia que o calor de Paris", "caption_draft": "Texto. Comenta aqui embaixo!"},
            {"title": "Notas amadeiradas explicadas", "hook": "Madeira não é tudo igual", "caption_draft": "Outro texto. Salva este post"},
        ]
        reps = cv.find_repetitions(items)
        self.assertNotIn(0, reps)
        self.assertTrue(any("parecida" in r for r in reps[1]))
        self.assertTrue(any("começa igual" in r for r in reps[2]))
        self.assertTrue(any("chamada para ação" in r for r in reps[2]))
        self.assertNotIn(3, reps)

    def test_repeats_recent_content(self):
        reps = cv.find_repetitions([{"title": "Como escolher o perfume certo para o verão", "hook": "x", "caption_draft": ""}],
                                   [{"title": "Perfume certo para o verão: como escolher", "hook": "y"}])
        self.assertTrue(any("conteúdo recente" in r for r in reps[0]))

    def test_helpers(self):
        self.assertEqual(cv.opening("Você SABIA que..."), "voce sabia que")
        self.assertEqual(cv.cta_of("Linha 1.\nComenta aqui embaixo! #ruah #perfume"), "comenta aqui embaixo")
        self.assertGreaterEqual(cv.similarity("perfume verão escolher", "escolher perfume verão"), 0.99)


if __name__ == "__main__":
    unittest.main()
