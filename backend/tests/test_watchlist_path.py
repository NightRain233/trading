import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import main


class WatchlistPathTests(unittest.TestCase):
    def test_resolve_shanghai_numeric_symbol_candidate(self):
        candidates = main.resolve_symbol_candidates("600519")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["symbol"], "600519.SS")
        self.assertEqual(candidates[0]["displayCode"], "600519.SH")
        self.assertEqual(candidates[0]["market"], "上海")

    def test_resolve_shenzhen_numeric_symbol_candidate(self):
        candidates = main.resolve_symbol_candidates("159915")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["symbol"], "159915.SZ")
        self.assertEqual(candidates[0]["displayCode"], "159915.SZ")
        self.assertEqual(candidates[0]["market"], "深圳")

    def test_resolve_000001_conflict_prefers_existing_shanghai_index(self):
        candidates = main.resolve_symbol_candidates("000001")

        self.assertGreaterEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["symbol"], "000001.SS")
        self.assertEqual(candidates[0]["name"], "上证指数")
        self.assertEqual(candidates[1]["symbol"], "000001.SZ")
        self.assertEqual(candidates[1]["name"], "平安银行")

    def test_normalize_watchlist_symbol_converts_sh_to_yahoo_ss(self):
        self.assertEqual(main.normalize_watchlist_symbol("600519.SH"), "600519.SS")

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
