# Steam Wallpaper Engine integration

This is the wallpaper subsystem of [Caelestia Central](../README.md), an independent integration/extension of [Almamu/linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine). The separately installed upstream renderer supplies scene/video playback. This layer supplies Steam subscription synchronization, favorites, cached high-quality posters, color generation, a picker, and the live wallpaper splash.

**Arbitrary local wallpapers are not supported yet.** The library indexes downloaded Wallpaper Engine Steam Workshop projects for app `431960`. Files elsewhere on your computer cannot be imported into this UI. This is the current integration scope, not a general restriction claimed for every upstream renderer mode.

Install the whole extension with `python3 scripts/install.py` from the repository root. See [installation](../docs/INSTALLATION.md), [architecture](../docs/ARCHITECTURE.md), and [testing](../docs/TESTING.md).

```sh
~/.config/wallpaperengine/wallpaperctl session
~/.config/wallpaperengine/wallpaperctl ui
~/.config/wallpaperengine/wallpaperctl refresh
~/.config/wallpaperengine/wallpaperctl next
~/.config/wallpaperengine/wallpaperctl random
~/.config/wallpaperengine/wallpaperctl status
journalctl --user -u wallpaperengine.service
```

The controller maintains one managed renderer, detects library changes, restores the saved selection at session startup, and recovers from temporary renderer failures. Workshop content and Wallpaper Engine assets must already exist in your Steam libraries. Compatibility depends on the renderer; automatic selection excludes web wallpapers.

`wallpaperctl session` waits for the current Hyprland instance's IPC, Wayland socket and monitor before importing its display into the user service. Initial configuration load and compositor start can both invoke it: a session lock and controller identity prevent duplicate restarts. It starts unloaded units directly rather than treating `reset-failed` as a prerequisite. Bootstrap diagnostics are recorded under `~/.local/state/wallpaperengine/logs/session.log`.

Colour sampling remains small and cached. A separate still, capped at 2560×1440 without upscaling, supplies the shell's wallpaper source and optional login export. Its preparation runs outside the live wallpaper transition; delayed scene captures upgrade the initial preview, and superseded decodes cannot publish an old selection. See [optional greeter export](../docs/INSTALLATION.md#optional-caelestia-greetd-export).

Color generation uses actual video samples or rendered scene captures when available, with Workshop previews as fallback. It writes Caelestia shell color roles without applying a global application theme. Poster preparation is cached separately from palette generation.

The circular splash uses a short-lived private runtime capture, a GPU shader, cancellation on workspace/lock changes, and a safety timeout. It reveals the live background and newly themed UI in the same region. Reduced motion uses a short fade. Settings and runtime paths are documented in the installation guide.

Run the wallpaper tests with `python3 -m unittest discover -s wallpaperengine/tests -v` from the repository root.
