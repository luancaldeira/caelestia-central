#!/bin/sh
set -eu
cd "$(dirname "$0")"
wayland-scanner client-header protocols/virtual-pointer.xml virtual-pointer.h
wayland-scanner private-code protocols/virtual-pointer.xml virtual-pointer-protocol.c
cc -O2 virtual-pointer.c virtual-pointer-protocol.c $(pkg-config --cflags --libs wayland-client) -o virtual-pointer
