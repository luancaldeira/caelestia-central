#!/bin/sh
set -eu
cd "$(dirname "$0")"
target=$(mktemp "$PWD/caelestia-minimize.XXXXXX.so")
trap 'rm -f "$target"' EXIT
c++ -std=c++23 -O2 -fPIC -fno-gnu-unique -shared -Wall -Wextra -Wno-unused-parameter \
    $(pkg-config --cflags hyprland) main.cpp -o "$target"
# Never truncate a shared library currently mapped by the compositor.
chmod 755 "$target"
mv "$target" caelestia-minimize-flight.so
