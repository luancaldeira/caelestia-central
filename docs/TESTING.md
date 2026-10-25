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

- Favorite icon and native launcher activation reveal the client through the actual bottom hover drawer; existing apps are reused.
- Minimize reverses the same drawer offset, merges into the bottom border, and finishes on the hidden workspace without a full-size flash.
- Restore reveals the client through the bottom border, detaches the shared surface and hands off to the native window, leaving the hub and pointer available.
- Closing a visible app shrinks upward; application close confirmation remains functional.
- The finite window list opens at its middle entry, exposes adjacent previews at the edges, stops at both ends, and reverses smoothly while keeping stable window identities.
- The bottom handle moves between icons and options with native dashboard easing, a small overshoot, and interruption from the current position.
- Wallpaper favorites retain browsing order, subscriptions synchronize, and posters use the best available cached source.
- The splash reveals the new live wallpaper and shell palette, cancels on workspace/lock changes, cleans up captures, and still runs after unlock.

The lock/unlock cycle was previously confirmed by the desktop owner. An automated test does not attempt to enter a user's password. The latest close regression was run in the real session on both X11 and Wayland; machine-specific results are summarized in `docs/verification.json`.

## Shared drawer verification

`qs -c caelestia ipc call windowdrawer info` reports active image readiness, source resolution, drawer offset, deformed border clearance and detachment. Its last eight completed panels also include image readiness, primed frame swaps, animation frame intervals, refresh request count and native-frame acknowledgment timestamps. Verify these alongside the actual displayed animation; native alpha alone cannot establish that a window image is visible. Opening and restoring must show client pixels inside the moving surface, and minimization must follow the same surface back into the border. At rest there must be no active panel or outstanding hidden native client.

Use real applications in addition to GTK fixtures, and test both Wayland and X11. Check the ordinary native launcher as well as favorite icons. A fixture that changes its content after the first captured frame must visibly update inside the moving surface before the native handoff. Content refresh is capped at 30 Hz; this must not lower the geometry animation's frame rate. Minimize must begin before thumbnail readback/encoding, and the thumbnail must still arrive after the window is hidden. Restore or close an entry while its thumbnail is pending to check that a late callback cannot recreate it. No screen recording is required.

For continuity, keep the original default spatial easing and duration. The image must be presented in its initial pose before the native client is suppressed and the offset begins. At the other end, a constant-color fixture must retain its color across the native handoff, away from the still-open hub. The final image transform must reach identity (`edgeErrorPx: 0`) across two final frame swaps before releasing the native client. A decorated export already includes the compositor's corner mask and uses no additional clip (`clipRadius: 0`). `nativeFrameAt` must precede completion and `handoffFallback` must remain false. A minimized surface must clear the smoothing region and reach deformation rest before removal; it must not disappear merely because its content has crossed the clip. Also test a restore while the first image is still being prepared.

The title bar must travel with the client, including its native buttons. A content-only fixture cannot catch a title appearing at handoff. With hyprbars and a light title enabled, the opt-in regression below opens a unique Kitty window, minimizes it and restores it from the hub. It checks title glyphs before and after handoff using temporary 320×13-pixel crops. The exported final pose is held through the opt-in `windowdrawer hold` diagnostic so both captures use identical geometry; a timed sample during bounce would also measure text resampling. The diagnostic defaults to disabled, is cleared during test cleanup, and remains bounded by the native lease timeout. The test retains only numeric results, closes only its own window, and restores the workspace, hub and pointer. It requires Pillow and grim.

```sh
python tests/desktop/verify_drawer_titlebar.py --live --backend wayland
python tests/desktop/verify_drawer_titlebar.py --live --backend x11
```

Title glyphs and center colors alone do not detect clipped edges. The perimeter regression below creates a temporary Kitty desktop entry, adds it to favorites, and clicks that actual icon in the app hub. It compares the final exported frame with the native client at the same position, then minimizes the fixture and clicks it in the window hub to repeat the comparison. It checks both side edges, the exposed bottom edges, title background/text, and both top corners. The middle of the bottom edge is excluded because the still-open hub animates above it independently. Temporary launchers, favorites, windows and full captures are removed; the original client set, minimized entries, favorites, focus, workspace and cursor are checked or restored.

```sh
python3 tests/desktop/verify_drawer_edges.py --live --backend wayland
python3 tests/desktop/verify_drawer_edges.py --live --backend x11
```

This test requires the pointer helper above, Kitty, Pillow, grim, and one unrotated 1920×1080 monitor at scale 1. Optional `--artifacts /private/path` retains only side-by-side corner crops. Results go to ignored `test-results/edges-wayland.json` and `test-results/edges-x11.json`. Passing this fixed-pose comparison verifies the exported/native handoff in those cases; it does not replace visual evaluation of every app, layout or monitor configuration.

## Visual demonstrations

Recordings and visual demonstrations are deferred. The current release contains no captured desktop media. Verification is documented through automated tests, the native regression, and the sanitized results in `docs/verification.json`.
