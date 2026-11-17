"""升级包替换逻辑：换掉程序文件夹、保留旧版本、失败时回滚。"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import upgrade  # noqa: E402


class UpgradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = self.root / "install" / "质量节点"
        self.build = self.root / "pkg" / "新版本" / "质量节点"
        self.target.mkdir(parents=True)
        self.build.mkdir(parents=True)
        (self.target / "质量节点.exe").write_text("old", encoding="utf-8")
        (self.target / "旧文件.txt").write_text("old", encoding="utf-8")
        (self.build / "质量节点.exe").write_text("new", encoding="utf-8")
        (self.build / "新文件.txt").write_text("new", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_swap_replaces_program_and_keeps_backup(self):
        backup = upgrade.swap_folder(self.target, self.build, "质量节点.exe")
        self.assertTrue((self.target / "新文件.txt").is_file())
        self.assertFalse((self.target / "旧文件.txt").exists())
        self.assertEqual((self.target / "质量节点.exe").read_text(encoding="utf-8"), "new")
        self.assertTrue((backup / "旧文件.txt").is_file())
        self.assertTrue(backup.name.startswith("质量节点-旧-"))

    def test_swap_restores_old_folder_when_copy_fails(self):
        with mock.patch.object(upgrade.shutil, "copytree", side_effect=OSError("模拟失败")):
            with self.assertRaises(OSError):
                upgrade.swap_folder(self.target, self.build, "质量节点.exe")
        self.assertTrue((self.target / "旧文件.txt").is_file())
        self.assertFalse((self.target / "新文件.txt").exists())

    def test_manifest_falls_back_when_missing(self):
        self.assertEqual(upgrade.read_manifest(self.root / "pkg"), {})

    def test_package_inside_target_is_detected(self):
        self.assertTrue(upgrade.is_inside(self.target / "升级包" / "x", self.target))
        self.assertFalse(upgrade.is_inside(self.build, self.target))

    def test_find_target_uses_explicit_path(self):
        self.assertEqual(upgrade.find_target(self.target), self.target)


if __name__ == "__main__":
    unittest.main()
