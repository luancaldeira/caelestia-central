# Installation and recovery

## Supported baseline

This repository contains the modified QML source for Caelestia Shell 2.3.0. Its separately installed `Caelestia` and `Caelestia.Config` C++ QML modules must match that shell version. The native compositor extension targets Hyprland 0.56.2, including its Lua dispatch API and exact native ABI. Quickshell and the system Qt libraries must be built for compatible versions.

Install Caelestia and its documented dependencies first. Install linux-wallpaperengine independently, following [its upstream instructions](https://github.com/Almamu/linux-wallpaperengine). Install Wallpaper Engine in Steam and download Workshop items you own or are entitled to use. The renderer needs Wallpaper Engine's `assets` directory.

The validated engine installation exposes `/usr/bin/linux-wallpaperengine` and places its library/binary under `/opt/linux-wallpaperengine`. The controller currently checks that installed layout. Other packaging layouts require adapting `wallpaperengine/controller.py` before use; the installer does not relocate engine files.

## Check and install

```sh
python3 scripts/install.py --check
python3 scripts/install.py
```

The check is read-only. Installation compiles the native plugin locally, snapshots configuration under `$XDG_STATE_HOME/caelestia-central/backups/` (normally `~/.local/state/caelestia-central/backups/`), and links the shell, controller, plugin source directory, Lua integration module, and systemd unit into the standard configuration locations. It adds `require("lua.caelestia-central")` to an existing `hyprland.lua`.

It disables Caelestia's static wallpaper layer so the live engine background remains visible. Wallpaper palette changes are scoped to Caelestia: native CLI theme writers for unrelated applications are disabled in `caelestia/cli.json`. Other configuration keys are preserved. It also installs an English desktop entry named **Steam Wallpapers**.

Keep the checkout at its installed location. Log out and back in to start the shell and controller in the same graphical session. This does not enable automatic session locking. Remove earlier custom central integrations before installing to avoid registering the same shortcuts twice.

Review the bindings in `hypr/lua/caelestia-central.lua`, especially **Super+M**, before installation. The optional `examples/animations.lua` supplies the compositor motion preset used on the development desktop; it is not automatically applied over your existing animation preferences. The shell's own dashboard-style motion is included in the QML.

## Steam library discovery

The controller discovers regular Steam locations, Flatpak Steam, and additional libraries declared in `steamapps/libraryfolders.vdf`. You can list extra library roots in `~/.config/wallpaperengine/settings.json`:

```json
{
  "steam_libraries": ["/path/to/SteamLibrary"],
  "transition": {
    "enabled": true,
    "duration_ms": 680,
    "reduce_motion": false
  }
}
```

Those paths are Steam library roots, **not arbitrary local wallpaper directories**. Local wallpaper import is not implemented. Existing downloaded items may remain browsable when subscription metadata is unavailable; an authoritative empty subscription list remains empty.

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

Preferences and favorites live under `~/.local/state/wallpaperengine/`; app favorites and minimized-window metadata live under `~/.local/state/caelestia/`. Caches are under `~/.cache/wallpaperengine/` and `~/.cache/caelestia/`. These personal files are not part of this repository.

## Application favorites

The initial favorite list comes from Caelestia's launcher configuration. The mini hub keeps its own persisted list after initialization. To add an application that is not currently in the mini row, use its desktop-entry ID:

```sh
qs -c caelestia ipc call appcentral list
qs -c caelestia ipc call appcentral favorite org.example.App
```

The `favorite` command toggles that entry. Right-clicking an icon in the mini hub also toggles it. Native launcher behavior and desktop-entry launch arguments are preserved.

## Updates and troubleshooting

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
