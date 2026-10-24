# Installation and recovery

## Supported baseline

This repository contains the modified QML source for Caelestia Shell 2.3.0. Its separately installed `Caelestia` and `Caelestia.Config` C++ QML modules must match that shell version. The native compositor extension targets Hyprland 0.56.2, including its Lua dispatch API and exact native ABI. Quickshell and the system Qt libraries must be built for compatible versions.

Install Caelestia and its documented dependencies first. For local image/GIF folders, install **awww** (client and daemon; validated with 0.12.1). Steam and Wallpaper Engine are not needed for this source.

For optional Workshop playback, install linux-wallpaperengine independently, following [its upstream instructions](https://github.com/Almamu/linux-wallpaperengine). Install Wallpaper Engine in Steam and download Workshop items you own or are entitled to use. The renderer needs Wallpaper Engine's `assets` directory.

The validated engine installation exposes `/usr/bin/linux-wallpaperengine` and places its library/binary under `/opt/linux-wallpaperengine`. The controller currently checks that installed layout. Other packaging layouts require adapting `wallpaperengine/controller.py` before use; the installer does not relocate engine files.

## Check and install

```sh
python3 scripts/install.py --check
python3 scripts/install.py
```

The check is read-only. Installation compiles the native plugin locally, snapshots configuration under `$XDG_STATE_HOME/caelestia-central/backups/` (normally `~/.local/state/caelestia-central/backups/`), and links the shell, controller, plugin source directory, Lua integration module, and systemd unit into the standard configuration locations. It adds `require("lua.caelestia-central")` to an existing `hyprland.lua`.

It disables Caelestia's static wallpaper layer so the managed wallpaper background remains visible. Wallpaper palette changes are scoped to Caelestia: native CLI theme writers for unrelated applications are disabled in `caelestia/cli.json`. Other configuration keys are preserved. It also installs an English desktop entry named **Wallpapers**.

Keep the checkout at its installed location. Log out and back in to start the shell and controller in the same graphical session. This does not enable automatic session locking. Remove earlier custom central integrations before installing to avoid registering the same shortcuts twice.

Review the bindings in `hypr/lua/caelestia-central.lua`, especially **Super+M**, before installation. The optional `examples/animations.lua` supplies the compositor motion preset used on the development desktop; it is not automatically applied over your existing animation preferences. The shell's own dashboard-style motion is included in the QML.

## Local wallpaper folders

Open the central's **Wallpapers** view, click the folder icon, then **Add folder**. The separate wallpaper picker also has a **Folders** button. You can add multiple folders, including mounted drives, and remove them from the library without deleting their contents. JPG/JPEG, PNG, WebP, BMP and GIF files are included recursively. Hidden entries, directory symlinks and file links escaping the selected root are skipped. Local video files are not supported by this source.

The controller watches for additions, replacements and deletions. Missing drives remain listed as unavailable; their parent directory is watched for reconnection and periodic rescanning remains a fallback. A file keeps its favorite identity when its contents change at the same path. Paths containing spaces and non-ASCII characters are supported.

Equivalent commands:

```sh
~/.config/wallpaperengine/wallpaperctl folder-add "$HOME/Pictures/Wallpapers"
~/.config/wallpaperengine/wallpaperctl folders
~/.config/wallpaperengine/wallpaperctl folder-remove "$HOME/Pictures/Wallpapers"
```

Folders are persisted as a `local_folders` list in `~/.config/wallpaperengine/settings.json`. Other settings are preserved. No directory is imported automatically. A fresh local-only installation exposes the picker even when the library is empty.

## Steam library discovery

The controller discovers regular Steam locations, Flatpak Steam, and additional libraries declared in `steamapps/libraryfolders.vdf`. You can list extra library roots in `~/.config/wallpaperengine/settings.json`:

```json
{
  "local_folders": ["/path/to/Pictures/Wallpapers"],
  "steam_libraries": ["/path/to/SteamLibrary"],
  "transition": {
    "enabled": true,
    "duration_ms": 680,
    "reduce_motion": false
  }
}
```

`steam_libraries` contains Steam library roots; `local_folders` contains ordinary image folders. Existing downloaded items may remain browsable when subscription metadata is unavailable; an authoritative empty subscription list remains empty.

## Runtime commands

```sh
~/.config/wallpaperengine/wallpaperctl session
~/.config/wallpaperengine/wallpaperctl status
~/.config/wallpaperengine/wallpaperctl refresh
~/.config/wallpaperengine/wallpaperctl ui
qs -c caelestia ipc call minimized info
qs -c caelestia ipc call minimized list
journalctl --user -u wallpaperengine.service
```

The wallpaper service starts with the Hyprland session. It watches the compositor connection and exits when that session ends. It serializes changes and maintains one managed renderer. If a new wallpaper fails, it attempts to restore the previous selection. A theme failure preserves the last working colors.

Startup waits for the current compositor's sockets and an enabled monitor, resolves its actual Wayland display, and imports that environment before starting the service. Both initial configuration load and `hyprland.start` invoke the bootstrap. Subsequent configuration reloads keep a healthy renderer in the same session. A user service that has not been loaded yet can start normally; no `reset-failed` operation is required.

If a wallpaper appears only after opening the hub, inspect `~/.local/state/wallpaperengine/logs/session.log` alongside the service journal. `systemctl --user is-enabled` reporting `linked` describes the installed unit file, rather than proving that the session bootstrap executed.

Preferences and favorites live under `~/.local/state/wallpaperengine/`; app favorites and minimized-window metadata live under `~/.local/state/caelestia/`. Caches are under `~/.cache/wallpaperengine/` and `~/.cache/caelestia/`. These personal files are not part of this repository.

## Optional Caelestia greetd export

The desktop renderer starts after login. The login greeter displays a static still from the selected wallpaper. The controller now publishes a separate full-size still through `caelestia/wallpaper/path.txt`, keeping the 384 px colour sample out of the login background. Native video frames and available scene captures are capped at 2560×1440; small source images are never enlarged to fake detail.

For an existing Caelestia greetd installation that uses `/usr/local/bin/caelestia-greeter-profile-sync` and `/run/caelestia-greeter/profile.env`, install the optional export:

```sh
sudo python3 scripts/install-greeter-export.py --user "$(id -un)"
```

For custom XDG locations, also supply `--config-home /absolute/config/path` and `--state-home /absolute/state/path`. The normal user installer does not enable this system integration automatically.

The optional installer creates `/var/cache/caelestia-central/login-<uid>/`, configures `greeter.export_directory` in the user's wallpaper settings, and adds a greetd pre-start hook after the existing profile synchronizer. The root-owned hook points the profile at stable export URLs; wallpaper reads and export writes run as the desktop user. Only the chosen static image and shell colour scheme are exported as readable files. New graphical login screens use those URLs without needing to restart the display manager or run a privileged copy operation on every wallpaper change.

Other greeters can consume the same optional files, `wallpaper` (image type detected from its contents) and `scheme.json`, by configuring their own background source. A greeter configured only to copy an image at display-manager boot will retain that old copy across graphical session restarts until its configuration is adapted.

Remove the optional system hook with:

```sh
sudo python3 scripts/install-greeter-export.py --user "$(id -un)" --uninstall
```

This preserves exported files and user preferences. Remove `greeter.export_directory` from wallpaper settings to stop exporting. The original greeter profile synchronizer takes over at the next display-manager service start.

## Application favorites

The initial favorite list comes from Caelestia's launcher configuration. The mini hub keeps its own persisted list after initialization. To add an application that is not currently in the mini row, use its desktop-entry ID:

```sh
qs -c caelestia ipc call appcentral list
qs -c caelestia ipc call appcentral favorite org.example.App
```

The `favorite` command toggles that entry. Right-clicking an icon in the mini hub also toggles it. Native launcher behavior and desktop-entry launch arguments are preserved.

## Updates and troubleshooting

For this wallpaper startup fix, existing installations linked to this checkout can update and reload their Lua integration:

```sh
git pull --ff-only
hyprctl reload config-only
```

The session bootstrap will restart an older controller that does not report the current compositor identity. A full logout/login check remains useful to confirm the installation's session launcher. The optional greeter export is configured separately as described above; no display-manager restart is performed by its installer.

Rebuild the native plugin after changing Hyprland versions; the current source must first be ported if the native API changes. An ABI mismatch is rejected instead of loading incompatible code. The loader can rebuild with matching installed headers, but cannot repair an API break. Plugin startup errors appear in `hypr/plugins/caelestia-minimize/build.log`.

The shell intentionally disables live file watching. After editing QML, restart only your Caelestia instance while the session is unlocked, or log out and back in. Never restart the shell while it owns the session lock.

Reduced-motion wallpaper transitions use a short fade. Set `transition.reduce_motion` in the settings above, or `CAELESTIA_REDUCED_MOTION=1` in the service environment. Locking the session or switching workspaces cancels a running splash and removes its temporary capture.

## Uninstall

```sh
python3 scripts/uninstall.py
# Or select a specific installation snapshot:
python3 scripts/uninstall.py --backup /path/to/snapshot
```

The rollback restores configuration paths that still match the installed links/hashes. Later edits are preserved and reported for manual comparison. Log out and back in before deleting the checkout, so the compositor releases the extension and the restored shell starts normally. Steam content, saved favorites, caches, and the separately installed engine are retained.
