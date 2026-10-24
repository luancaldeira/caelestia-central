# Testing

## Unit checks

```sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s wallpaperengine/tests -v
```

The wallpaper suite covers local-folder selection and removal, Unicode paths, recursive scanning and symlink boundaries, duplicate roots, stable IDs after replacement, unavailable drives, local-only startup, renderer ownership/cancellation, Steam library discovery, subscription removal and empty lists, malformed/atomic metadata writes, safe paths, video/scene poster preparation, palette hue and contrast, isolation from global application theme writers, renderer recovery, startup retries, and transition cleanup. Palette tests require the installed Caelestia Python package and materialyoucolor. Portable CI runs installation, library and transition checks without assuming a graphical session or a Caelestia installation.

Startup regressions also cover an unloaded systemd user unit, late compositor/monitor readiness, stale Wayland environment, concurrent duplicate hooks and failure logging. Login-image checks use generated video fixtures and scene captures to verify native resolution, cache reuse, retry after decoder failure, late capture upgrades, and rejection of obsolete asynchronous results. Optional greeter export tests preserve unrelated settings and profile fields, check atomic public image writes, and ensure the root profile updater never reads user image bytes. These checks are included in portable CI.

The stopped-service/config-reload sequence was reproduced in the supported desktop: the old `reset-failed` prerequisite aborted before starting an unloaded service; direct startup restored the saved wallpaper without opening the central. Repeated reloads kept the same controller PID. A complete logout/login cycle after this update has not been repeated automatically.

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

- Favorite launch projects the current bottom drawer; unarmed launches retain the compositor's normal animation. Existing apps are reused.
- Favorite launch, minimization and hub restoration use the hover drawer's actual motion tokens and BlobRect material. The panel slides out before detaching and morphing into the window; client pixels appear only after release. Absorption reverses that path. Close retains its upward departure.
- Restore releases the window from the bottom bar and leaves the hub and pointer available for another restore.
- Closing a visible app shrinks upward; application close confirmation remains functional.
- The finite window list opens at its middle entry, exposes adjacent previews at the edges, stops at both ends, and reverses smoothly while keeping stable window identities.
- The bottom handle moves between icons and options with native dashboard easing, a small overshoot, and interruption from the current position.
- Wallpaper favorites retain browsing order, subscriptions synchronize, and posters use the best available cached source.
- The splash reveals the new live wallpaper and shell palette, cancels on workspace/lock changes, cleans up captures, and still runs after unlock.

The lock/unlock cycle was previously confirmed by the desktop owner. An automated test does not attempt to enter a user's password. The latest close regression was run in the real session on both X11 and Wayland; machine-specific results are summarized in `docs/verification.json`.

## Bubble geometry

```sh
c++ -std=c++23 -O2 -Wall -Wextra tests/test_bubble_motion.cpp -o /tmp/bubble-motion-test
/tmp/bubble-motion-test
```

Portable checks cover exact endpoints, translated monitors, positive bounds, rounding limits, a fixed-size vertical reveal behind the bar, clearance before client pixels appear, alpha bounds, and continuity across material handoffs. Live native checks also cover preserved goals, reduced motion, reversal during minimization, close and plugin reload.

The end-to-end surface regression temporarily adds one favorite desktop entry, operates its actual icon and restored-window preview, and removes its fixtures afterward:

```sh
sh tests/desktop/build-pointer.sh
python3 tests/desktop/verify_surface_motion.py --live
```

It checks all three paths on Wayland and X11, delayed client visibility, surface delivery and cleanup, final geometry, an open hub and unchanged pointer after restoration, and ordinary launches remaining outside the custom path. It briefly uses workspace 918 and requires that workspace to be empty, an unlocked supported desktop and the pointer fixture's 1920×1080 single-monitor coordinates. Avoid desktop interaction while it runs. Sanitized results go to ignored `test-results/surface-motion.json`. It takes no screenshots or recordings.

## Visual demonstrations

Recordings and visual demonstrations are deferred. The current release contains no captured desktop media. Verification is documented through automated tests, the native regression, and the sanitized results in `docs/verification.json`.
