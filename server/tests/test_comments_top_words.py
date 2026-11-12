"""Nuvem de palavras: contagem por ocorrência e sentimento por comentário (cor da palavra)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest

from services.comments import top_words, word_tone


class TopWordsTests(unittest.TestCase):
    def test_counts_and_sentiment_split(self):
        rows = [
            {"text": "Amei o tecido, tecido perfeito", "sentiment": "positivo"},
            {"text": "Tecido rasgou na primeira lavagem", "sentiment": "negativo"},
            {"text": "Qual o tamanho do tecido?", "sentiment": None},
            {"text": "Amei demais", "sentiment": "positivo"},
        ]
        words = {w["word"]: w for w in top_words(rows, limit=10)}
        tecido = words["tecido"]
        self.assertEqual(tecido["count"], 4)  # ocorrências
        self.assertEqual(tecido["sentiment"], {"positivo": 1, "neutro": 0, "misto": 0, "negativo": 1, "sem_analise": 1})
        self.assertEqual(tecido["tone"], "negativo")  # empate: o tom sensível aparece
        self.assertEqual(words["amei"]["tone"], "positivo")
        self.assertIsNone(words["tamanho"]["tone"])  # só comentário sem análise

    def test_tone_rules(self):
        self.assertIsNone(word_tone({"sem_analise": 4}))
        self.assertEqual(word_tone({"positivo": 3, "negativo": 1}), "positivo")
        self.assertEqual(word_tone({"neutro": 2, "misto": 2}), "misto")


if __name__ == "__main__":
    unittest.main()
