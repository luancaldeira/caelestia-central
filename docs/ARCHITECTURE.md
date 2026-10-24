# Architecture

## Shell and compact navigation

`quickshell/caelestia` is a modified Caelestia Shell 2.3.0 source snapshot. The central is integrated into the existing drawer surface, input region, screen state, and palette services. It does not add a separate polling daemon for mouse hover.

`modules/minimized/Wrapper.qml` keeps favorites and the options row on a shared horizontal track. A clipped viewport and the native `Anim` behavior reproduce the dashboard's expressive transition. Both pages remain mounted; hit testing follows the selected page. Width and height are shared between those two compact views, while the window and wallpaper views have their own dimensions.

The wallpaper carousel keeps its final screen-bounded dimensions inside a clipped viewport while the panel opens. Cover dimensions, image crops and orbit spacing remain stable throughout the expansion.

`MiniApplications.qml` displays raw favorite icons. `ApplicationLibrary.qml` reads desktop entries and preserves native DesktopEntry launch semantics, including D-Bus activation, working directories, and arguments. An optional icon origin arms a short-lived native launch intent. Matching existing windows are reused; minimized matches go through the regular restore service.

## Minimized-window lifecycle

`Minimized.qml` records address, PID, workspace, geometry and thumbnail before minimizing. The address/PID pair guards against stale entries and reused window addresses. Hidden windows live on `special:caelestia-minimized`. Normal close requests are sent directly to the application; entries disappear only when the compositor reports that the window actually closed. An application can still reject closing to protect unsaved work.

The native plugin listens for client minimize requests in XDG-shell and XWayland. Each optional request is **consumed once**. In Hyprland 0.56.2, XWayland retains `requestsMinimize` while its shared `stateChanged` signal also reports unrelated fullscreen/maximize updates. Re-emitting that retained value could replay an old restore request for minimized siblings. Version 1.5 clears the request after reading it. Explicit subsequent restore requests still work.

`WindowStack.qml` holds stable address/PID identities, freezes outgoing cards during removal, and captures the pressed entry before a close/restore gesture. The horizontal list opens at its middle entry and has bounded, rate-limited wheel movement suitable for a small number of windows. Adjacent previews remain partially visible at the left and right edges; cards translate along a straight track without rotation or wraparound. Restoring from the hub targets the current workspace and retains the layer surface and pointer, allowing successive restores.

## Native motion

The extension animates presented window geometry while keeping the compositor's layout goals and the client surface resolution intact. Minimize and close share a single departure-geometry helper: the same proportional shrink, size cap and horizontal center, with opposite screen edges. Both use `windowsOut` for geometry and `fadeOut` for opacity, including the configured curves and independent durations. At the end of minimizing, it masks the move to the hidden workspace to avoid a second fade or a full-size flash. Restoration starts at the actual preview or clicked app icon. Interrupted minimize flights retain their current presented geometry.

Closing hooks the compositor's native `CWindowAnimationController::animateOut` context, after the client really closes. The snapshot shrinks upward; the close request itself is not delayed. There is no per-frame renderer hook. The complete ABI hash and the target symbol are checked before hooks are installed, and hooks/listeners are removed on unload.

## Wallpaper integration

`wallpaperengine/` manages two independent sources. `catalog.py` combines explicitly selected image folders from `localfiles.py` with downloaded Workshop projects; `subscriptions.py` synchronizes Steam metadata; `previews.py` prepares cached posters from video frames, rendered captures, or recoverable scene artwork. Scene package/texture parsing follows the installed upstream format. It does not start an additional live renderer to make each preview.

`controller.py` serializes renderer changes, preserves the latest requested selection, and handles recovery. `palette.py` generates Material color roles through the Caelestia Python utilities and writes only the shell's scheme state. Legacy serialized intensity identifiers are retained for preference compatibility; all displayed labels are English.

The CLI bootstrap serializes compositor startup hooks, waits for that instance's actual display and monitors, and compares its identity with the running controller. Starting an unloaded unit works without resetting a nonexistent failure state. A new graphical session restarts the previous controller; reloading configuration in the same session preserves it.

Display stills are independent of palette samples. A background task prepares the selected wallpaper's native frame and upgrades a delayed scene capture. It checks the selection generation before publishing, so older work cannot overwrite a newer wallpaper. `greeter.py` optionally publishes the image and scheme into a stable shared directory as the desktop user. The optional system installer changes only a compatible greetd greeter's root-owned profile URLs; it does not give a root process arbitrary user-supplied image paths to read on change notifications.

`transition.py` prepares a private runtime capture of the previous desktop while the new wallpaper and colors become ready. `WallpaperTransition.qml` and `modules/wallpaper/splash.frag` reveal the new live scene through a soft circular mask. The overlay receives no pointer/keyboard input and has a timeout, lock/workspace cancellation, and capture cleanup. Captures are temporary runtime data, not library items.

Local image/GIF IDs are namespaced hashes of canonical paths; modification signatures include size and nanosecond timestamps. Overlapping folder roots deduplicate files. Scans never change originals and skip hidden entries, symlink directories and escaping file links. Inotify watches scanned directories, missing-root parents and the settings file's parent to handle atomic saves; periodic refresh covers missed events. Settings updates retain unrelated keys.

Local playback uses a child `awww-daemon --namespace caelestia-central --no-cache`, and the client addresses only that namespace. Image-to-image changes reuse that process. It applies the final image without its own transition so the shell splash controls the reveal and colors. Shutdown terminates only the owned child; it does not kill unrelated awww instances. Workshop playback uses the separately installed Almamu/linux-wallpaperengine and Wallpaper Engine assets. Neither Steam nor that engine is required for local images. Local video files are not indexed.

A fresh empty library exposes IPC immediately once the compositor is ready. Existing saved selections still receive a boot grace period for temporarily unavailable drives or Steam libraries. Available local images participate in next/random and removal fallback; unavailable optional renderers are excluded.
