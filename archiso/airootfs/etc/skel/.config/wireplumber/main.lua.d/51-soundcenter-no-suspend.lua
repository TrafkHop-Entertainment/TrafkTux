-- 51-soundcenter-no-suspend.lua — für WirePlumber < 0.5 (Lua-Config).
-- Prüfen mit: wireplumber --version
--
-- Installieren nach:  ~/.config/wireplumber/main.lua.d/
--
-- Gleicher Fix wie 51-soundcenter-no-suspend.conf, nur in der alten
-- Lua-Syntax - nur EINE der beiden Dateien installieren, passend zur
-- tatsächlich laufenden WirePlumber-Version.
--
-- Nach dem Anlegen: systemctl --user restart wireplumber (oder ab-/anmelden).

alsa_monitor.rules = alsa_monitor.rules or {}

table.insert(alsa_monitor.rules, {
  matches = {
    {
      { "node.name", "matches", "alsa_output.*" },
    },
    {
      { "node.name", "matches", "alsa_input.*" },
    },
  },
  apply_properties = {
    ["session.suspend-timeout-seconds"] = 0,
  },
})
