#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
qsb=${QSB:-/usr/lib/qt6/bin/qsb}
for shader in quickshell/caelestia/modules/minimized/reflection.frag quickshell/caelestia/modules/wallpaper/splash.frag; do
    "$qsb" --glsl '100 es,120,150' -o "$shader.qsb" "$shader"
done
