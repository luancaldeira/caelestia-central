#!/usr/bin/env python3
"""Optionally connect an existing Caelestia greetd greeter to an unprivileged export."""
import argparse
import os
from pathlib import Path
import pwd
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MARKER = "# Managed by Caelestia Central greeter export."
HOOK = Path("/usr/local/lib/caelestia-central/greeter-profile-export.py")
DROPIN = Path("/etc/systemd/system/greetd.service.d/zz-caelestia-central-wallpaper.conf")
PROFILE = Path("/run/caelestia-greeter/profile.env")


def profile_hook(directory, profile=PROFILE, owner_uid=0):
    """Root changes only the root-owned profile; it never reads user image bytes."""
    return f'''#!/usr/bin/python3 -I
{MARKER}
from pathlib import Path
import os
import shlex
import tempfile

profile = Path({str(profile)!r})
directory = Path({str(directory)!r})
if not profile.is_file():
    raise SystemExit(0)
if (profile.is_symlink() or profile.stat().st_uid != {owner_uid}
        or profile.stat().st_mode & 0o022 or profile.parent.stat().st_uid != {owner_uid}
        or profile.parent.stat().st_mode & 0o022):
    raise SystemExit("Refusing to edit an untrusted greeter profile")
values = {{}}
for key, name in (("CAELESTIA_GREETER_WALLPAPER", "wallpaper"),
                  ("CAELESTIA_GREETER_SCHEME_PATH", "scheme.json")):
    if (directory / name).is_file():
        values[key] = str(directory / name)
lines = [line for line in profile.read_text().splitlines()
         if line.partition("=")[0] not in values]
lines += [key + "=" + shlex.quote(value) for key, value in values.items()]
fd, temp = tempfile.mkstemp(dir=profile.parent, prefix=".central-profile-")
try:
    with os.fdopen(fd, "w") as stream:
        stream.write("\\n".join(lines) + "\\n")
        os.fchmod(stream.fileno(), 0o644)
    os.replace(temp, profile)
finally:
    if os.path.exists(temp):
        os.unlink(temp)
'''


def dropin(hook=HOOK):
    return f"{MARKER}\n[Service]\nExecStartPre={hook}\n"


def check_managed(path):
    if path.is_symlink() or (path.exists() and (
            path.stat().st_uid != 0 or path.stat().st_mode & 0o022
            or MARKER not in path.read_text().splitlines()[:2])):
        raise SystemExit(f"Refusing to replace an unrelated file: {path}")


def trusted_directory(path):
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink() or (parent.exists() and (parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022)):
            raise SystemExit(f"A root-owned directory is required: {parent}")
    path.mkdir(parents=True, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True, help="desktop login account; never root")
    parser.add_argument("--config-home", type=Path, help="that user's XDG_CONFIG_HOME")
    parser.add_argument("--state-home", type=Path, help="that user's XDG_STATE_HOME")
    parser.add_argument("--uninstall", action="store_true", help="remove the optional greetd hook")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run this optional system integration with sudo.")
    account = pwd.getpwnam(args.user)
    if account.pw_uid == 0:
        raise SystemExit("Choose a non-root desktop account.")
    config = args.config_home or Path(account.pw_dir) / ".config"
    state = args.state_home or Path(account.pw_dir) / ".local/state"
    if not config.is_absolute() or not state.is_absolute():
        raise SystemExit("XDG directories must be absolute paths.")
    check_managed(HOOK)
    check_managed(DROPIN)
    if args.uninstall:
        HOOK.unlink(missing_ok=True)
        DROPIN.unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        print("Greeter hook removed; cached exports and user settings were preserved.")
        print("The greeter's original profile synchronizer takes over at its next service start.")
        return
    if not Path("/usr/local/bin/caelestia-greeter-profile-sync").is_file():
        raise SystemExit("This option needs the existing Caelestia greetd profile synchronizer.")
    parent = Path("/var/cache/caelestia-central")
    if parent.is_symlink() or (parent.exists() and (parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022)):
        raise SystemExit("The shared cache parent must be owned and writable only by root.")
    parent.mkdir(mode=0o755, exist_ok=True)
    directory = parent / f"login-{account.pw_uid}"
    if directory.is_symlink():
        raise SystemExit("Refusing a symlinked export directory.")
    directory.mkdir(mode=0o755, exist_ok=True)
    os.chown(directory, account.pw_uid, account.pw_gid)
    directory.chmod(0o755)
    # Configuration, source reads and public image writes all happen as the
    # target user. Root never follows a wallpaper path supplied by that user.
    code = '''import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import greeter
config, state, target = map(Path, sys.argv[2:])
settings = greeter.configure(config, target)
path = state / "caelestia/wallpaper/path.txt"
if path.is_file():
    scheme_file = state / "caelestia/scheme.json"
    scheme = json.loads(scheme_file.read_text()) if scheme_file.is_file() else None
    greeter.export(path.read_text().strip(), scheme, settings)
'''
    subprocess.run(["runuser", "-u", account.pw_name, "--", sys.executable, "-c", code,
                    str(ROOT / "wallpaperengine"), str(config), str(state), str(directory)], check=True)
    trusted_directory(HOOK.parent)
    HOOK.write_text(profile_hook(directory))
    HOOK.chmod(0o755)
    trusted_directory(DROPIN.parent)
    DROPIN.write_text(dropin())
    DROPIN.chmod(0o644)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run([str(HOOK)], check=True)
    print("Greeter export configured. New login screens read the current public image and colours.")
    print("The active graphical session and display manager were not restarted.")


if __name__ == "__main__":
    main()
