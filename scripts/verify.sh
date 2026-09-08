#!/usr/bin/env bash

set -u

echo "Kernel command line"
cat /proc/cmdline

echo
echo "AMD graphics"
lspci -nnk | grep -A4 -i 'vga\|display'

echo
if [[ ${XDG_CURRENT_DESKTOP:-} == *KDE* ]] && command -v kscreen-doctor >/dev/null; then
    echo "KDE display configuration (check current mode is 5120x2880)"
    kscreen-doctor --outputs
elif command -v hyprctl >/dev/null; then
    echo "Hyprland monitor"
    hyprctl monitors all
    hyprctl configerrors
fi

echo
echo "Installed AMD module"
modinfo -n amdgpu
modinfo -F vermagic amdgpu

echo
echo "Loaded AMD module"
if [[ -d /sys/module/amdgpu ]]; then
    echo "amdgpu: loaded"
    echo "tiled_stitch: $(cat /sys/module/amdgpu/parameters/tiled_stitch 2>/dev/null || echo 'parameter missing')"
else
    echo "amdgpu: NOT LOADED - the desktop is running on software rendering (llvmpipe)."
    echo "Kernel messages:"
    (dmesg 2>/dev/null || journalctl -k -b 2>/dev/null) | grep -i amdgpu | tail -10 ||
        echo "  (none; re-run this section as root to read the kernel log)"
fi

echo
echo "DRM driver bound to the GPU"
lspci -k -s 01:00.0 | sed -n '/Kernel driver in use/p' || true
grep -H . /sys/class/drm/card*/device/uevent 2>/dev/null | grep -i driver || true

echo
echo "OpenGL renderer (llvmpipe means no GPU acceleration)"
command -v glxinfo >/dev/null && glxinfo -B 2>/dev/null | grep -i 'OpenGL renderer' ||
    echo "  glxinfo not installed (dnf install glx-utils)"

echo
echo "Audio"
command -v wpctl >/dev/null && wpctl status
command -v dkms >/dev/null && dkms status
command -v pactl >/dev/null && pactl list cards | grep -E 'Name: alsa_card|Active Profile'

echo
echo "Thunderbolt devices"
command -v boltctl >/dev/null && boltctl list

echo
echo "Network devices"
nmcli device status

echo
echo "IPv4 routes"
ip -4 route

echo
echo "Aquantia/OWC Ethernet"
lspci -nnk | grep -A4 -i 'ethernet\|aquantia'

