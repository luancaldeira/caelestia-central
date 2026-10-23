# Contributing

Use English for UI strings, code comments, documentation, issues, and pull requests. Preserve upstream license notices and keep personal configuration/state outside the repository.

Run both unit suites documented in the README. Native changes must be built against the exact running Hyprland version and tested in a recoverable desktop session. Keep X11 and Wayland regressions separate; validate close rejection, hidden siblings, repeated state changes, and explicit restoration.

For motion changes, use Caelestia's existing animation tokens where appropriate. Preserve immediate response, stable window identities and pointer position, reversible transitions, and application-owned close confirmation. Attach a short actual desktop recording when behavior changes visually.

Report the Hyprland, Caelestia, Quickshell and Qt versions with bugs. Do not attach raw private runtime captures or personal minimized-window state. Wallpaper compatibility reports should identify the Workshop item and renderer version.
