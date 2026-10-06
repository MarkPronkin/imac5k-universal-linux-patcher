-- Record mpv's frame timing in the EDR test session's run directory: one JSON
-- line a second while a video plays. Playback properties are already gone at
-- shutdown, so nothing is written then.
local utils = require "mp.utils"
local run = os.getenv("IMAC_EDR_RUN")
local session = os.getenv("IMAC_EDR_SESSION")

-- Raising the backlight while the desktop is scaled down gives HDR content its
-- headroom without changing how bright the desktop looks. It costs black level,
-- so it is asked for only while a video plays.
local function headroom(what)
  if session then
    mp.command_native_async({ name = "subprocess", playback_only = false, capture_stdout = true,
                              args = { "python3", session .. "/headroom.py", what } }, function() end)
  end
end

mp.register_event("file-loaded", function() headroom("engage") end)
mp.register_event("shutdown", function()
  mp.command_native({ name = "subprocess", playback_only = false, capture_stdout = true,
                      args = { "python3", (session or ".") .. "/headroom.py", "release" } })
end)

if not run then
  return
end

local names = {
  "time-pos", "estimated-vf-fps", "display-fps", "estimated-display-fps", "vsync-jitter",
  "frame-drop-count", "decoder-frame-drop-count", "vo-delayed-frame-count", "mistimed-frame-count",
}

mp.add_periodic_timer(1, function()
  local stats = {}
  for _, name in ipairs(names) do
    stats[name] = mp.get_property_number(name)
  end
  if not stats["time-pos"] then
    return
  end
  local file = io.open(run .. "/mpv-stats.jsonl", "a")
  if file then
    file:write(utils.format_json(stats) .. "\n")
    file:close()
  end
end)
