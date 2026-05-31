import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import main


class WatchlistPathTests(unittest.TestCase):
    def test_watchlist_file_is_anchored_to_backend_directory(self):
        self.assertTrue(Path(main.WATCHLIST_FILE).is_absolute())
        self.assertEqual(Path(main.WATCHLIST_FILE).name, "watchlist.json")

        original_cwd = os.getcwd()
        try:
            with TemporaryDirectory() as tmpdir:
                os.chdir(tmpdir)
                groups = main.load_watchlist()
        finally:
            os.chdir(original_cwd)

        symbols = {item["symbol"] for group in groups for item in group.get("symbols", [])}
        self.assertIn("159326.SZ", symbols)


if __name__ == "__main__":
    unittest.main()
