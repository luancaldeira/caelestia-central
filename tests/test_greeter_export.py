"""Optional greeter exports use user rights and retain unrelated configuration."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wallpaperengine"))
import greeter
spec = importlib.util.spec_from_file_location("greeter_installer", ROOT / "scripts/install-greeter-export.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ExportTests(unittest.TestCase):
    def test_disabled_export_changes_no_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            greeter.export("/missing/image", {}, {})
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_configure_preserves_existing_preferences_and_custom_xdg_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "custom config"
            path = config / "wallpaperengine/settings.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"steam_libraries":["/library"],"transition":{"enabled":false}}')
            result = greeter.configure(config, Path(tmp) / "shared export")
            self.assertEqual(result["steam_libraries"], ["/library"])
            self.assertFalse(result["transition"]["enabled"])
            self.assertEqual(json.loads(path.read_text()), result)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_export_replaces_target_symlink_without_writing_through_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, untouched, target = root / "source.jpg", root / "unrelated", root / "public"
            source.write_bytes(b"selected-image")
            untouched.write_bytes(b"preserve")
            target.mkdir()
            (target / "wallpaper").symlink_to(untouched)
            mask = os.umask(0o077)
            try:
                greeter.export(source, {"colours":{"primary":"123456"}}, {"greeter":{"export_directory":str(target)}})
            finally:
                os.umask(mask)
            self.assertEqual(untouched.read_bytes(), b"preserve")
            self.assertEqual((target / "wallpaper").read_bytes(), b"selected-image")
            self.assertEqual((target / "wallpaper").stat().st_mode & 0o777, 0o644)
            self.assertEqual(json.loads((target / "scheme.json").read_text())["colours"]["primary"], "123456")
            self.assertFalse(any(p.name.startswith(".central-") for p in target.iterdir()))

    def test_generated_profile_hook_preserves_other_profile_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "public export"
            target.mkdir()
            (target / "wallpaper").write_bytes(b"image")
            (target / "scheme.json").write_text("{}")
            profile = root / "profile.env"
            profile.write_text("CAELESTIA_GREETER_USER=fixture\nCAELESTIA_GREETER_WALLPAPER=/old/thumbnail.png\n")
            code = installer.profile_hook(target, profile, owner_uid=os.getuid())
            # The profile updater only publishes fixed URLs. It never opens an
            # image as root, even when a user replaces the export with a symlink.
            with patch.object(Path, "read_bytes", side_effect=AssertionError("no privileged image reads")):
                exec(compile(code, "generated-greeter-hook", "exec"), {})
            values = dict(line.split("=", 1) for line in profile.read_text().splitlines())
            self.assertEqual(values["CAELESTIA_GREETER_USER"], "fixture")
            self.assertEqual(shlex.split(values["CAELESTIA_GREETER_WALLPAPER"]), [str(target / "wallpaper")])
            self.assertEqual(shlex.split(values["CAELESTIA_GREETER_SCHEME_PATH"]), [str(target / "scheme.json")])

    def test_installer_refuses_unrelated_or_symlinked_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original, link = root / "original", root / "hook"
            original.write_text("unrelated")
            with self.assertRaises(SystemExit):
                installer.check_managed(original)
            link.symlink_to(original)
            with self.assertRaises(SystemExit):
                installer.check_managed(link)
