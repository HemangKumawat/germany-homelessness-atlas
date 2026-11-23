import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from verify import scaled_numbers  # noqa: E402


class ScaledAmounts(unittest.TestCase):
    def test_scale_words_read_exactly(self):
        self.assertIn(1e10, scaled_numbers("Bund trägt jährlich KdU-Leistungen von 10 Mrd. Euro"))
        self.assertIn(9.8e6, scaled_numbers("einen Nachteil von 9,8 Mio. Euro."))
        self.assertIn(180_404_000.0, scaled_numbers("in Höhe von 180.404 Tsd. Euro"))
        self.assertIn(232_000.0, scaled_numbers("in Höhe von rd. 232 T€"))
        self.assertIn(127_400_000.0, scaled_numbers("Mehrbedarf in Höhe von 127,4 Mio. Euro"))

    def test_no_scale_word_no_match(self):
        self.assertEqual(scaled_numbers("10 Euro im Jahr 2024"), set())
        self.assertNotIn(1e7, scaled_numbers("10 Mrd. Euro"))           # the scale is not guessed
        self.assertEqual(scaled_numbers("Mio. Euro 10"), set())         # number must precede the word
        self.assertEqual(scaled_numbers("10 Mion"), set())


if __name__ == "__main__":
    unittest.main()
