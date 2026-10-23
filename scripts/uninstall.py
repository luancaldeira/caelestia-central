#!/usr/bin/env python3
"""Restore the last installation snapshot without overwriting later edits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def restore(manifest):
    skipped = []
    for name, record in reversed(list(manifest.items())):
        path = Path(name)
        if "installed_link" in record:
            if not path.is_symlink() or os.readlink(path) != record["installed_link"]:
                skipped.append(name)
                continue
        elif "installed_hash" in record:
            if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record["installed_hash"]:
                skipped.append(name)
                continue
        else:
            continue
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        if "link" in record:
            path.symlink_to(record["link"])
        elif "copy" in record:
            shutil.copy2(record["copy"], path)
        elif "directory" in record:
            shutil.copytree(record["directory"], path, symlinks=True)
    return skipped


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--backup", type=Path)
    args = p.parse_args()
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "caelestia-central"
    directory = args.backup or Path((state / "last-backup.txt").read_text().strip())
    skipped = restore(json.loads((directory / "manifest.json").read_text()))
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print("Configuration restored. Log out and back in before removing the checkout.")
    for path in skipped:
        print("Preserved a later edit; compare with the backup: " + path)
    print("Steam content, favorites, caches and the separately installed renderer were preserved.")


if __name__ == "__main__":
    main()
