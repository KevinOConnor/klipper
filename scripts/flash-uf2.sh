#!/bin/bash
# This script installs a uf2 imag to a given rp2040 BOOTSEL disk

DISK=$1
BIN_FILE=$2

if [[ "$DISK" = "" || "$BIN_FILE" = "" ]]; then
    echo "Usage: $0 <disk> <uf2 file>" >&2
    exit -1
fi

MOUNT_POINT="$(mktemp -d)"
function cleanup {
    umount "$MOUNT_POINT" &>/dev/null
    rm -rf "$MOUNT_POINT"
}
trap cleanup EXIT

mount "/dev/${DISK}1" "$MOUNT_POINT"
cp "$BIN_FILE" "$MOUNT_POINT/"
