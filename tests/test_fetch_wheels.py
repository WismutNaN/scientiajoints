import tempfile
import unittest
from pathlib import Path

from tools.fetch_wheels import drop_superseded_wheels


class WheelCleanupTests(unittest.TestCase):
    def test_platform_wheels_do_not_delete_one_another(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            windows = root / "matplotlib-3.11.1-cp313-cp313-win_amd64.whl"
            linux = root / "matplotlib-3.11.1-cp313-cp313-manylinux2014_x86_64.whl"
            windows.write_bytes(b"windows")
            linux.write_bytes(b"linux")

            kept = drop_superseded_wheels(root)

            self.assertEqual(set(kept), {windows, linux})
            self.assertTrue(windows.exists())
            self.assertTrue(linux.exists())

    def test_only_an_older_wheel_with_the_same_tags_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "matplotlib-3.10.0-cp313-cp313-win_amd64.whl"
            new = root / "matplotlib-3.11.1-cp313-cp313-win_amd64.whl"
            old.write_bytes(b"old")
            new.write_bytes(b"new")

            kept = drop_superseded_wheels(root)

            self.assertEqual(kept, (new,))
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())


if __name__ == "__main__":
    unittest.main()
