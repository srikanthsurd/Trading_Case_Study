import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


class OutputDirectoryTests(unittest.TestCase):
    def test_outputs_directory_has_explanation(self):
        self.assertTrue((OUT / "README.md").exists())


if __name__ == "__main__":
    unittest.main()
