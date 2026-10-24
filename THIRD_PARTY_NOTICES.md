# Third-party notices

## Caelestia Shell

Source: https://github.com/caelestia-dots/shell

The `quickshell/caelestia/` tree is derived from the installed Caelestia Shell 2.3.0 source distribution and includes local modifications for the central, native window motion, and wallpaper transitions. Original authors retain their copyrights. Upstream GPL-3.0 license text is retained in that tree and at the repository root. This is not an official Caelestia release.

The Google Sans Flex font remains under its accompanying license in `quickshell/caelestia/assets/google-sans-flex/LICENSE`. Other included upstream assets retain their applicable upstream terms.

## linux-wallpaperengine

Source: https://github.com/Almamu/linux-wallpaperengine

Installed integration baseline: `b016d7d1fdcf4e5fd2f9c9fa420a8aaa07fee02d` (GPL-3.0).

The optional Workshop backend is an independent integration/extension of this project. Its renderer is not bundled. The scene package/texture reader follows upstream PKGV/TEX structures. Rendering capabilities belong to the upstream project; this repository contributes library/UI/controller integration and shell transitions.

## awww

Source: https://codeberg.org/LGFae/awww (GPL-3.0-only).

The local image/GIF backend invokes the separately installed awww client and its daemon in a dedicated namespace. Neither binary is bundled. Local playback does not require linux-wallpaperengine or Steam. Validated runtime: awww 0.12.1.

## Hyprland, Quickshell, and related projects

- Hyprland: https://github.com/hyprwm/Hyprland — compositor APIs and native window animation infrastructure. Native target: 0.56.2, commit `efb50993780079460b0cbed1363e2166a2de1d9f`.
- Quickshell: https://quickshell.org/ — shell runtime, Wayland integration, IPC and QML services.
- Qt: https://www.qt.io/ — Qt Quick animation, scene graph and shaders.
- swww: https://github.com/LGFae/swww — visual reference for grow/outer wallpaper transitions; no swww runtime is required by this implementation.
- hyprland-scroll-overview: https://github.com/yayuuu/hyprland-scroll-overview — the existing desktop's overview renders background wallpaper layers. That plugin is not bundled or required for the central.

The vendored fuzzy-search helpers retain their embedded MIT (`fuzzysort`, Stephen Kamenar) and BSD-3-Clause (`fzf-for-js`, Ajit) notices in `quickshell/caelestia/utils/scripts/`.

The desktop regression helper includes the wlr virtual-pointer protocol by Josef Gajdusek, under its embedded MIT license. Generated protocol code is built locally.

## Test fixtures and excluded content

The English GTK fixture in `tests/desktop/fixture.py` creates synthetic test windows. No desktop recordings, Workshop wallpaper assets, Steam account data, user documents, caches, thumbnails, tokens, or prebuilt compositor plugins are included in this distribution. Workshop artwork remains the property of its creators.
