# Testing

## Unit checks

```sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s wallpaperengine/tests -v
```

The wallpaper suite covers Steam library discovery, subscription removal and empty lists, malformed/atomic metadata writes, safe paths, video/scene poster preparation, palette hue and contrast, isolation from global application theme writers, renderer recovery, startup retries, and transition cleanup. Palette tests require the installed Caelestia Python package and materialyoucolor. Portable CI runs installation, library and transition checks without assuming a graphical session or a Caelestia installation.

## Live close-isolation regression

Run only in the supported Hyprland/Caelestia desktop. This opt-in test creates three related GTK windows on a temporary workspace and briefly operates the central. Requirements include Python GObject/GTK4, a C compiler, wayland-scanner and Wayland client headers.

```sh
sh tests/desktop/build-pointer.sh
python3 tests/desktop/verify_close_isolation.py --live
```

The test uses its own windows, remembers the initial panel/pointer/focus state, and removes its fixtures afterward. Avoid interacting with the desktop while it runs. Results go to ignored `test-results/close-isolation.json`.

For each of X11 and Wayland it minimizes three windows through their native toolkit requests, clicks the actual close button, verifies that a rejected close keeps the original window, closes individual accepted targets, and verifies that every remaining window stays on the hidden workspace. The hub must remain open. On X11, unrelated fullscreen-state updates are also sent to survivors to ensure that a previous NormalState request is not replayed as a restore.

The original regression was reproduced before the fix: after all three windows were hidden, an unrelated X11 state update restored one. The same sequence passes after consuming `requestsMinimize` once. No timeout or blanket suppression of legitimate restore requests is used.

## Motion verification

Check these behaviors visually when changing native motion or the central:

- Favorite icon launch starts at the clicked 32 px icon; existing apps are reused.
- Minimize shrinks downward into the preview without a lingering frame or flash at full size.
- Restore grows from the preview and leaves the hub and pointer available for another restore.
- Closing a visible app shrinks upward; application close confirmation remains functional.
- The queue works with one, two and three windows, stable identities, and direction reversal.
- The bottom handle moves between icons and options with native dashboard easing, a small overshoot, and interruption from the current position.
- Wallpaper favorites retain browsing order, subscriptions synchronize, and posters use the best available cached source.
- The splash reveals the new live wallpaper and shell palette, cancels on workspace/lock changes, cleans up captures, and still runs after unlock.

The lock/unlock cycle was previously confirmed by the desktop owner. An automated test does not attempt to enter a user's password. The latest close regression was run in the real session on both X11 and Wayland; machine-specific results are summarized in `docs/verification.json`.

## Visual demonstrations

Recordings and visual demonstrations are deferred. The current release contains no captured desktop media. Verification is documented through automated tests, the native regression, and the sanitized results in `docs/verification.json`.
