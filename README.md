# Lid Behaviour

A tiny GUI to choose **what closing your laptop lid does** — like Windows 11's
*Power Options*, but for GNOME/Zorin. Set one action for **Plugged in** and
another for **On battery**. No config files, no terminal, no root.

![what it controls](data/no.finter.LidBehaviour.svg)

The classic use case: at a docking station with external monitors, close the
lid and keep working on the external screens instead of the laptop sleeping.
Set **Plugged in → Do nothing** and you're done.

## Install

```bash
./install.sh
```

Then search **“Lid Behaviour”** in your app menu, or run `lidbehaviour`.

Uninstall with `./uninstall.sh` (your settings are left untouched).

## Requirements

Already present on a standard Zorin/Ubuntu GNOME desktop:

- Python 3, PyGObject (`python3-gi`)
- GTK 4 and libadwaita (`gir1.2-gtk-4.0`, `gir1.2-adw-1`)

## How it works

GNOME's settings daemon (`gsd-power`) owns the lid switch while you're logged
in, so this app sets the keys it actually reads, via GSettings:

| In the app | GSettings key (`org.gnome.settings-daemon.plugins.power`) |
|---|---|
| Plugged in | `lid-close-ac-action` |
| On battery | `lid-close-battery-action` |
| Stay awake with an external monitor | `lid-close-suspend-with-external-monitor` (inverted) |

Actions map to GNOME enum values: **Do nothing** = `nothing`, **Sleep** =
`suspend`, **Hibernate** = `hibernate`, **Shut down** = `shutdown`.

Because GNOME holds an inhibitor on the lid switch, these GSettings keys take
priority over `/etc/systemd/logind.conf` for the logged-in session — which is
why this layer is the right one to touch and needs no root.

## Notes

- **Docked = Plugged in.** A powered dock charges the laptop, so "Plugged in"
  is the setting that applies when docked.
- **DisplayLink docks** (e.g. the ThinkPad *Hybrid USB-C with USB-A* dock)
  present monitors as virtual displays, which GNOME's "external monitor"
  detection doesn't always count. Setting **Plugged in → Do nothing** keeps the
  machine awake regardless of whether that detection fires.
- **Hibernate** needs enough swap space to store RAM; without it the system
  sleeps instead.
