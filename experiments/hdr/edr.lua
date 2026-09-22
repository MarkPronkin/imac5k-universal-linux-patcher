-- For the patched Hyprland 0.56.2 only. Load after the ordinary monitor rules.
-- Prototype for iMac18,3: assumes a working backlight at its maximum setting.
-- 500 and 200 are estimated nits, not colorimeter measurements.
-- This file does not change backlight settings.
hl.monitor({
    output = "eDP-1",
    mode = "preferred",
    position = "auto",
    scale = 2,
    bitdepth = 10,
    cm = "edr",
    max_luminance = 500,
    sdr_max_luminance = 200,
    supports_hdr = -1,
})
