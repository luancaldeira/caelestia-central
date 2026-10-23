-- Caelestia Central: add require("lua.caelestia-central") to hyprland.lua.
local config = os.getenv("XDG_CONFIG_HOME") or (os.getenv("HOME") .. "/.config")
local loader = config .. "/hypr/plugins/caelestia-minimize/load.sh"
local wallpaper = '"' .. config .. '/wallpaperengine/wallpaperctl"'

hl.bind("SUPER + M", hl.dsp.exec_cmd("qs -c caelestia ipc call minimized minimize"), {
    description = "Minimize window to Caelestia Central",
})
hl.bind("SUPER + SHIFT + M", hl.dsp.exec_cmd("qs -c caelestia ipc call minimized toggle"), {
    description = "Toggle Caelestia Central",
})
hl.bind("SUPER + ALT + W", hl.dsp.exec_cmd(wallpaper .. " ui"), {
    description = "Open Steam wallpaper library",
})
hl.bind("SUPER + SHIFT + W", hl.dsp.exec_cmd(wallpaper .. " random"), {
    description = "Apply a random Steam wallpaper",
})
hl.bind("SUPER + CTRL + W", hl.dsp.exec_cmd(wallpaper .. " next"), {
    description = "Apply the next Steam wallpaper",
})
hl.on("hyprland.start", function()
    hl.exec_cmd('"' .. loader .. '"')
    hl.exec_cmd(wallpaper .. " session")
end)
hl.on("config.reloaded", function() hl.exec_cmd('"' .. loader .. '"') end)
hl.workspace_rule({ workspace = "special:caelestia-minimized", gaps_in = 0, gaps_out = 0 })

-- Give apps without their own decoration a native minimize button when available.
for _, plugin in ipairs(hl.get_loaded_plugins()) do
    if plugin.name == "hyprbars" then
        hl.plugin.hyprbars.add_button({
            bg_color = "rgb(c5c7b1)", fg_color = "rgb(25271c)", size = 12, icon = "−",
            action = "qs -c caelestia ipc call minimized minimize",
        })
        break
    end
end
