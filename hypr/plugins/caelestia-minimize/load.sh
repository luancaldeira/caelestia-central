#!/bin/sh
set -eu
cd "$(dirname "$0")"
if hyprctl plugin list | rg -q '^Plugin caelestia-minimize by '; then
    exit 0
fi
# The plugin itself checks Hyprland's complete ABI hash before adding listeners.
if [ -f caelestia-minimize-flight.so ] && hyprctl plugin load "$PWD/caelestia-minimize-flight.so"; then
    exit 0
fi
if sh ./build.sh > build.log 2>&1 && hyprctl plugin load "$PWD/caelestia-minimize-flight.so"; then
    exit 0
fi
notify-send -a Caelestia 'Minimize extension needs rebuilding' \
    'Update Hyprland headers (hyprpm update) and run ~/.config/hypr/plugins/caelestia-minimize/load.sh. Super+M still works.'
exit 1
