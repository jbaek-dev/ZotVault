import unittest

from paperflow.related import blob_to_vec, cosine, top_similar, vec_to_blob


class TestVectors(unittest.TestCase):
    def test_blob_roundtrip(self):
        v = [0.1, -0.5, 2.25, 0.0]
        out = blob_to_vec(vec_to_blob(v))
        for a, b in zip(v, out):
            self.assertAlmostEqual(a, b, places=5)

    def test_cosine(self):
        self.assertAlmostEqual(cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)
        self.assertAlmostEqual(cosine([1, 1], [-1, -1]), -1.0)
        self.assertEqual(cosine([], [1]), 0.0)
        self.assertEqual(cosine([0, 0], [1, 1]), 0.0)

    def test_top_similar(self):
        vecs = {
            "A": [1.0, 0.0],
            "B": [0.9, 0.1],
            "C": [0.0, 1.0],
            "D": [1.0, 0.05],
        }
        top = top_similar("A", vecs, k=2, threshold=0.5)
        self.assertEqual([c for c, _ in top], ["D", "B"])
        self.assertTrue(all(s >= 0.5 for _, s in top))
        self.assertEqual(top_similar("missing", vecs), [])


if __name__ == "__main__":
    unittest.main()
