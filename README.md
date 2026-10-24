# Caelestia Central

A compact bottom-edge hub for favorite apps, minimized windows, and local or Steam Workshop wallpapers, built around Caelestia's native motion and translucent surfaces.

[Installation](docs/INSTALLATION.md) · [Architecture](docs/ARCHITECTURE.md)

## What it does

- Hover over the bottom center to reveal a small row of favorite application icons.
- Click the handle beneath the icons to slide into **Apps / Windows / Wallpapers**. The transition uses the same expressive `Anim` curve as Caelestia's dashboard and can reverse while moving.
- **Apps** opens Caelestia's native launcher. Clicking a favorite releases its window from the bottom drawer, or brings back an existing window without launching a duplicate.
- **Windows** shows minimized windows in a compact, finite horizontal list. It opens at the middle preview, with neighboring cards peeking in at the edges. Scroll in either direction; the ends do not wrap. Restoring a window releases it from the bottom bar and keeps the hub open for another selection.
- Launching from favorite icons or restoring from Windows first projects Caelestia's own translucent drawer surface out of the bottom bar. That surface peels away, takes the window's shape, and reveals its live content. Minimizing reverses the path and merges the surface back into the bar. Timing, easing and material deformation come from the same hover drawer. The motion can reverse while moving.
- Minimize buttons and **Super+M** send windows into the hub. Closing a minimized window closes only that window. Other minimized windows remain hidden, including when an X11 toolkit updates their state after a sibling closes.
- **Wallpapers** reads image folders you choose, with optional Steam Workshop integration. Open the folder button to add or remove folders without moving your files. It uses a rectangular Cover Flow carousel with perspective and reflections. Right-click to favorite; favorites appear first the next time the library opens.
- Wallpaper changes reveal the live wallpaper and the new shell colors through a soft circular splash originating at the pointer. Scene captures and video frames improve carousel preview quality.
- The saved wallpaper starts with the graphical session without opening the hub. Login backgrounds use a separate full-size still; compatible Caelestia greetd installations can opt into a persistent public export.
- Closing a visible application shrinks it upward, visually distinguishing closing from minimizing back into the bottom bar.

## Wallpaper sources

**Wallpaper Engine is optional.** Open **Wallpapers → folder icon → Add folder** and select any readable directory on your device. The hub indexes JPG/JPEG, PNG, WebP, BMP and GIF files, including subfolders. Local playback uses the separately installed [awww](https://codeberg.org/LGFae/awww) image/GIF renderer; no Steam installation or Wallpaper Engine assets are needed. Favorites, high-quality previews, theme colors, the splash and login stills work with both sources.

Folders are watched for new, replaced and deleted images. Removing a folder only removes its entries from the library; it never deletes your files. Hidden files/directories, directory symlinks and links escaping the selected folder are skipped. Local video files and Wallpaper Engine scene projects outside Steam libraries are not imported by the folder source.

The optional Workshop backend remains an independent **integration/extension of [Almamu/linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine)**. That project supplies Workshop scene/video rendering; this repository adds library synchronization, selection, favorites, previews, Caelestia colors and transitions. The renderer is not bundled or reimplemented here. This backend requires a legitimate Wallpaper Engine installation and its assets. Unsubscribed items disappear even if Steam leaves their folders behind. No Workshop content is downloaded or redistributed. Compatibility depends on the installed renderer; web wallpapers are excluded from automatic selection.

## Requirements

The validated combination is **Hyprland 0.56.2 with Lua configuration**, **Caelestia Shell 2.3.0**, and **Quickshell 0.3.1**, plus the installed Caelestia C++ QML modules and CLI. The native extension uses Hyprland internals and must be compiled against headers matching the running compositor. It checks the complete ABI hash before loading. Other Hyprland releases require porting and validation.

The controller also needs Python 3.11+, Pillow, materialyoucolor, the Caelestia Python package, FFmpeg/ffprobe, grim, systemd user services, and at least one renderer: `awww` + `awww-daemon` for local images (validated with 0.12.1), or `linux-wallpaperengine` for Workshop content. Build dependencies include a C++23 compiler, pkg-config, matching Hyprland headers, and ripgrep. See [installation and recovery](docs/INSTALLATION.md).

```sh
git clone https://github.com/luancaldeira/caelestia-central.git
cd caelestia-central
python3 scripts/install.py --check
python3 scripts/install.py
```

Keep the checkout in place: installation creates configuration symlinks and snapshots replaced configuration. Review shortcut conflicts first. Log out and back in after installation. The installer does not install the renderer, Steam content, Caelestia packages, or compositor dependencies.

## Controls

| Action | Input |
| --- | --- |
| Reveal the central | Hover at the bottom center, or Super+Shift+M |
| Switch favorite icons / options | Click the bottom handle; Tab in the mini hub |
| Minimize the active window | Its minimize button, or Super+M |
| Open the native application launcher | Apps in the options row; existing Super+W binding |
| Browse windows or wallpapers | Mouse wheel or Left/Right |
| Restore a window / apply a wallpaper | Click the selected preview, or Enter |
| Close the selected minimized window | Close button, or Delete |
| Toggle an app/wallpaper favorite | Right-click its icon/card; F also works for wallpapers |
| Back / close | Escape |
| Open the separate wallpaper library | Super+Alt+W |
| Add / remove local wallpaper folders | Folder icon in Wallpapers |
| Random / next wallpaper | Super+Shift+W / Super+Ctrl+W |

## Development

```sh
python3 -m unittest discover -s wallpaperengine/tests -v
python3 -m unittest discover -s tests -v
sh hypr/plugins/caelestia-minimize/build.sh
# Optional: regenerate the included Qt shader bundles
sh scripts/build-shaders.sh
```

[Testing notes](docs/TESTING.md) describe the live X11/Wayland close-isolation regression, close rejection, and verification results. Desktop tests are opt-in and use their own test windows; the ordinary unit suite does not operate the desktop.

## Credits and license

This includes a modified source snapshot of **[Caelestia Shell](https://github.com/caelestia-dots/shell)**, the basis for the shell, design system, dashboard transitions, launcher, and theme services. It is an independent customization, not an official Caelestia release. The wallpaper integration extends **[Almamu/linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine)**, with the installed baseline at `b016d7d1fdcf4e5fd2f9c9fa420a8aaa07fee02d`. **[Hyprland](https://github.com/hyprwm/Hyprland)** and **[Quickshell](https://quickshell.org/)** provide compositor and UI infrastructure. The wallpaper splash takes visual inspiration from swww's grow/outer transitions.

Distributed under [GPL-3.0](LICENSE), with upstream notices retained. See [third-party notices](THIRD_PARTY_NOTICES.md). Steam Workshop wallpapers and other personal content are not included.
