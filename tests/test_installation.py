"""Configuration snapshots must preserve existing files, links and later edits."""
from pathlib import Path
import importlib.util
import tempfile
import unittest


def module(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


install, uninstall = module("install"), module("uninstall")


class SnapshotTests(unittest.TestCase):
    def test_directory_is_restored_after_link_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original, target = root / "configuration", root / "checkout"
            original.mkdir()
            (original / "custom.qml").write_text("personal customization")
            target.mkdir()
            snapshot = install.Snapshot(root / "backup")
            snapshot.link(original, target)
            self.assertTrue(original.is_symlink())
            self.assertEqual(uninstall.restore(snapshot.records), [])
            self.assertFalse(original.is_symlink())
            self.assertEqual((original / "custom.qml").read_text(), "personal customization")

    def test_writing_a_link_does_not_modify_an_external_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            external, config = root / "external.json", root / "config.json"
            external.write_text('{"original": true}')
            config.symlink_to(external)
            snapshot = install.Snapshot(root / "backup")
            snapshot.write(config, '{"installed": true}')
            self.assertEqual(external.read_text(), '{"original": true}')
            self.assertEqual(uninstall.restore(snapshot.records), [])
            self.assertTrue(config.is_symlink())
            self.assertEqual(config.resolve(), external)

    def test_uninstall_preserves_later_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            config.write_text("original")
            snapshot = install.Snapshot(root / "backup")
            snapshot.write(config, "installed")
            config.write_text("later user edit")
            self.assertEqual(uninstall.restore(snapshot.records), [str(config)])
            self.assertEqual(config.read_text(), "later user edit")


if __name__ == "__main__":
    unittest.main()
