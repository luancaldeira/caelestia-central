# Changelog

## 2026-10-23 — Wallpaper session startup and login images

- Fix wallpaper bootstrap aborting on a systemd user unit that has not been loaded, which left the desktop blank until the central opened.
- Wait for the current Hyprland instance and display, serialize duplicate startup hooks, and retain the running renderer on configuration reloads.
- Export a full-size login still independently of the small colour sample; prepare it outside the transition and upgrade late scene captures.
- Add an optional configurable Caelestia greetd export so graphical session restarts read the latest image and colours.
- Add portable regressions for unloaded services, stale sessions, duplicate hooks, image quality and greeter export.

Tracked in [issue #1](https://github.com/luancaldeira/caelestia-central/issues/1).
