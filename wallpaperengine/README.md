# Local and Workshop wallpaper integration

This is the wallpaper subsystem of [Caelestia Central](../README.md). Local images and GIFs use [awww](https://codeberg.org/LGFae/awww), independently of Steam. The optional Workshop backend is an independent integration/extension of [Almamu/linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine), whose separately installed renderer supplies Workshop scene/video playback. This layer supplies folder and Steam subscription synchronization, favorites, cached high-quality posters, color generation, a picker, and the live wallpaper splash.

Choose **Wallpapers → folder icon → Add folder**, or **Folders** in the separate picker. Supported local formats: JPG/JPEG, PNG, WebP, BMP and GIF. Subfolders are included; hidden entries, directory symlinks and file symlinks outside the chosen folder are excluded. Arbitrary local videos are not imported. Removing a folder never deletes its files. No default folder is scanned without your selection.

Commands (the historical `wallpaperengine` config/state paths remain compatible):

```sh
~/.config/wallpaperengine/wallpaperctl session
~/.config/wallpaperengine/wallpaperctl ui
~/.config/wallpaperengine/wallpaperctl folder-add "$HOME/Pictures/Wallpapers"
~/.config/wallpaperengine/wallpaperctl folders
~/.config/wallpaperengine/wallpaperctl folder-remove "$HOME/Pictures/Wallpapers"
~/.config/wallpaperengine/wallpaperctl refresh
~/.config/wallpaperengine/wallpaperctl next
~/.config/wallpaperengine/wallpaperctl random
~/.config/wallpaperengine/wallpaperctl status
journalctl --user -u wallpaperengine.service
```

The controller maintains one managed renderer, detects library changes, restores the saved selection at session startup, and recovers from temporary renderer failures. Local playback requires `awww` and `awww-daemon`; Workshop playback separately requires linux-wallpaperengine, Workshop content and Wallpaper Engine assets. A fresh installation starts the library service with no images configured, so you can choose a folder. Compatibility of Workshop content depends on its renderer; automatic selection excludes web wallpapers and unavailable backends.

`wallpaperctl session` waits for the current Hyprland instance's IPC, Wayland socket and monitor before importing its display into the user service. Initial configuration load and compositor start can both invoke it: a session lock and controller identity prevent duplicate restarts. It starts unloaded units directly rather than treating `reset-failed` as a prerequisite. Bootstrap diagnostics are recorded under `~/.local/state/wallpaperengine/logs/session.log`.

Colour sampling remains small and cached. A separate still, capped at 2560×1440 without upscaling, supplies the shell's wallpaper source and optional login export. Its preparation runs outside the live wallpaper transition; delayed scene captures upgrade the initial preview, and superseded decodes cannot publish an old selection. See [optional greeter export](../docs/INSTALLATION.md#optional-caelestia-greetd-export).

Color generation uses actual video samples or rendered scene captures when available, with Workshop previews as fallback. It writes Caelestia shell color roles without applying a global application theme. Poster preparation is cached separately from palette generation.

The circular splash uses a short-lived private runtime capture, a GPU shader, cancellation on workspace/lock changes, and a safety timeout. It reveals the live background and newly themed UI in the same region. Reduced motion uses a short fade. Settings and runtime paths are documented in the installation guide.

Run the wallpaper tests with `python3 -m unittest discover -s wallpaperengine/tests -v` from the repository root.
