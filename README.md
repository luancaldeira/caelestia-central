# Caelestia Central

A compact bottom-edge hub for favorite apps, minimized windows, and Steam Workshop wallpapers, built around Caelestia's native motion and translucent surfaces.

[Installation](docs/INSTALLATION.md) · [Architecture](docs/ARCHITECTURE.md)

## What it does

- Hover over the bottom center to reveal a small row of favorite application icons.
- Click the handle beneath the icons to slide into **Apps / Windows / Wallpapers**. The transition uses the same expressive `Anim` curve as Caelestia's dashboard and can reverse while moving.
- **Apps** opens Caelestia's native launcher. Clicking a favorite launches its window from the icon, or brings back an existing window without launching a duplicate.
- **Windows** keeps minimized windows in a compact, scrollable queue. The front card slides aside as you scroll; restoring a window grows it from its preview and keeps the hub open for another selection.
- Minimize buttons and **Super+M** send windows into the hub. Closing a minimized window closes only that window. Other minimized windows remain hidden, including when an X11 toolkit updates their state after a sibling closes.
- **Wallpapers** uses a rectangular Cover Flow carousel with perspective and reflections. Right-click to favorite; favorites appear first the next time the library opens.
- Wallpaper changes reveal the live wallpaper and the new shell colors through a soft circular splash originating at the pointer. Scene captures and video frames improve carousel preview quality.
- The saved wallpaper starts with the graphical session without opening the hub. Login backgrounds use a separate full-size still; compatible Caelestia greetd installations can opt into a persistent public export.
- Closing a visible application shrinks it upward, visually distinguishing closing from minimizing downward into the hub.

## Wallpaper integration and current limitation

The wallpaper subsystem is an independent **integration/extension of [Almamu/linux-wallpaperengine](https://github.com/Almamu/linux-wallpaperengine)**. That project provides rendering; this repository adds Steam library synchronization, selection, favorites, preview preparation, Caelestia colors, and transitions. The renderer is a separate dependency and is not bundled or reimplemented here.

**Local wallpapers from your computer are not supported yet.** The integration currently follows the Steam Workshop library model: it indexes downloaded Wallpaper Engine Workshop projects for Steam app `431960`. Arbitrary local images, videos, and wallpaper folders outside that library cannot be imported into the central. This describes this integration's scope, rather than a limitation claimed for every upstream rendering mode.

A legitimate Wallpaper Engine installation and its assets are required. Unsubscribed items disappear from the central even if Steam leaves their folders behind. No Workshop content is downloaded or redistributed by this repository. Scene/video compatibility depends on the installed renderer; web wallpapers are excluded from automatic next/random selection.

## Requirements

The validated combination is **Hyprland 0.56.2 with Lua configuration**, **Caelestia Shell 2.3.0**, and **Quickshell 0.3.1**, plus the installed Caelestia C++ QML modules and CLI. The native extension uses Hyprland internals and must be compiled against headers matching the running compositor. It checks the complete ABI hash before loading. Other Hyprland releases require porting and validation.

The controller also needs Python 3.11+, Pillow, materialyoucolor, the Caelestia Python package, FFmpeg/ffprobe, grim, systemd user services, and a separately installed `linux-wallpaperengine`. Build dependencies include a C++23 compiler, pkg-config, matching Hyprland headers, and ripgrep. See [installation and recovery](docs/INSTALLATION.md).

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
| Random / next Workshop wallpaper | Super+Shift+W / Super+Ctrl+W |

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
