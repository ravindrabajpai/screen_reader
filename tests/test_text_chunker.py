import unittest

from text_chunker import chunk_text, normalize_text, sentences


class ChunkerTests(unittest.TestCase):
    def test_sentence_boundaries(self):
        text = 'Dr. Smith met Mr. Jones and A. B. Cole in the U.S. today. "It costs 3.14," she said. Is that right? Yes!'
        self.assertEqual(sentences(text), [
            'Dr. Smith met Mr. Jones and A. B. Cole in the U.S. today.',
            '"It costs 3.14," she said.', 'Is that right?', 'Yes!'])
        self.assertEqual(sentences('Try e.g. apples (or pears.) Next.'), ['Try e.g. apples (or pears.)', 'Next.'])

    def test_short_and_empty(self):
        self.assertEqual(chunk_text(" \n\t"), [])
        self.assertEqual(chunk_text("Hello. Goodbye!"), ["Hello. Goodbye!"])

    def test_caps_and_reconstruction(self):
        corpus = [" ".join(f"word{i}" for i in range(700)),
                  " ".join(f"Sentence {i} has several words." for i in range(100)),
                  ('First paragraph.\nWrapped line.\n\nNext paragraph! ' * 30),
                  ('Long clause ' * 29) + '; ' + ('more text ' * 130),
                  '"Quoted text!" Next (really?) More… text.']
        for text in corpus:
            with self.subTest(text=text[:40]):
                chunks = chunk_text(text)
                self.assertLessEqual(len(chunks[0].split()), 60)
                self.assertTrue(all(0 < len(chunk.split()) <= 190 for chunk in chunks[1:]))
                self.assertEqual(" ".join(" ".join(chunks).split()), " ".join(normalize_text(text).split()))

    def test_sentence_limits_and_paragraph_preference(self):
        text = " ".join(f"Sentence {i}." for i in range(30))
        chunks = chunk_text(text)
        self.assertEqual(len(sentences(chunks[0])), 3)
        self.assertTrue(all(len(sentences(c)) <= 10 for c in chunks[1:]))
        self.assertEqual(chunk_text("First. Second.\n\nThird. Fourth."), ["First. Second.", "Third. Fourth."])
