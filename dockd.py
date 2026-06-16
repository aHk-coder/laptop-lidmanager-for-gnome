#!/usr/bin/env python3
"""dockd — remember and restore display layouts by monitor serial.

GNOME matches saved display layouts by *connector name*. DisplayLink docks
hand the same physical monitor a different connector (DVI-I-1 vs DVI-I-2) on
different plug-ins, so GNOME often fails to match and falls back to a default
arrangement at the wrong refresh rate.

This helper matches monitors by their stable EDID identity (vendor + product +
serial) instead, and re-applies your saved layout via Mutter's DisplayConfig
D-Bus API. Run it as a --watch service to restore automatically on dock.

  dockd.py --save            save the current layout as a profile
  dockd.py --apply           apply the best-matching saved profile once
  dockd.py --list            list saved profiles
  dockd.py --watch           keep restoring on every monitor change (the service)
  dockd.py --status          show current monitors and whether a profile matches
"""

import json
import os
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

BUS_NAME = "org.gnome.Mutter.DisplayConfig"
OBJ_PATH = "/org/gnome/Mutter/DisplayConfig"
IFACE = "org.gnome.Mutter.DisplayConfig"

GET_STATE_TYPE = GLib.VariantType.new(
    "(ua((ssss)a(siiddada{sv})a{sv})a(iiduba(ssss)a{sv})a{sv})"
)

CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "lidbehaviour",
)
PROFILES_PATH = os.path.join(CONFIG_DIR, "profiles.json")

DEBOUNCE_MS = 1500  # let staggered DisplayLink monitors all show up first


# --------------------------------------------------------------------------- #
# Mutter DisplayConfig access
# --------------------------------------------------------------------------- #
def _bus():
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def ident(monitor_id):
    """Stable identity key from (connector, vendor, product, serial)."""
    _conn, vendor, product, serial = monitor_id
    return f"{vendor}:{product}:{serial}"


def read_state(bus=None):
    """Return (serial, monitors, logical_monitors) from Mutter, unpacked."""
    bus = bus or _bus()
    reply = bus.call_sync(
        BUS_NAME, OBJ_PATH, IFACE, "GetCurrentState",
        None, GET_STATE_TYPE, Gio.DBusCallFlags.NONE, -1, None,
    )
    return reply.unpack()


def _active_layout(state):
    """Describe currently-active monitors: {ident: {pos/mode/...}}."""
    serial, monitors, logical, _props = state
    # map identity -> (connector, modes)
    by_ident = {}
    for mon_id, modes, _mp in monitors:
        by_ident[ident(mon_id)] = (mon_id[0], modes)

    out = {}
    for x, y, scale, transform, primary, mons, _lp in logical:
        for mon_id in mons:  # (ssss)
            key = ident(mon_id)
            conn, modes = by_ident.get(key, (mon_id[0], []))
            cur = next((m for m in modes if m[6].get("is-current")), None)
            if cur is None:
                continue
            out[key] = {
                "id": key,
                "connector": conn,
                "x": int(x), "y": int(y),
                "scale": float(scale), "transform": int(transform),
                "primary": bool(primary),
                "w": int(cur[1]), "h": int(cur[2]), "rate": float(cur[3]),
            }
    return out


# --------------------------------------------------------------------------- #
# Profiles
# --------------------------------------------------------------------------- #
def load_profiles():
    try:
        with open(PROFILES_PATH) as fh:
            return json.load(fh).get("profiles", [])
    except (OSError, ValueError):
        return []


def save_profiles(profiles):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = PROFILES_PATH + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"profiles": profiles}, fh, indent=2)
    os.replace(tmp, PROFILES_PATH)


def save_current(name=None):
    layout = _active_layout(read_state())
    if not layout:
        print("No active monitors to save.")
        return None
    key = sorted(layout)
    monitors = list(layout.values())
    profiles = [p for p in load_profiles() if sorted(p["key"]) != key]
    profile = {
        "name": name or f"{len(monitors)} monitors",
        "key": key,
        "monitors": monitors,
    }
    profiles.append(profile)
    save_profiles(profiles)
    print(f"Saved profile '{profile['name']}' for {len(monitors)} monitor(s):")
    for m in monitors:
        tag = " *primary" if m["primary"] else ""
        print(f"  {m['id']}  {m['w']}x{m['h']}@{m['rate']:.0f} "
              f"@({m['x']},{m['y']}){tag}")
    return profile


def _match_profile(layout):
    """Find a saved profile whose monitor set equals the active set."""
    active = set(layout)
    for p in load_profiles():
        if set(p["key"]) == active:
            return p
    return None


def _layout_matches(profile, layout):
    """True if the live layout already equals the profile (no apply needed)."""
    for m in profile["monitors"]:
        cur = layout.get(m["id"])
        if cur is None:
            return False
        if (cur["x"], cur["y"], cur["primary"], cur["w"], cur["h"]) != (
                m["x"], m["y"], m["primary"], m["w"], m["h"]):
            return False
        if abs(cur["rate"] - m["rate"]) > 0.5:
            return False
    return True


def _find_mode_id(modes, w, h, rate):
    best = None
    for mid, mw, mh, mrate, *_rest in modes:
        if mw == w and mh == h:
            if abs(mrate - rate) <= 0.5:
                return mid
            if best is None:
                best = mid  # same resolution, nearest refresh as fallback
    return best


def apply_best(verify=False):
    """Apply the best-matching saved profile. Returns a status string."""
    bus = _bus()
    state = read_state(bus)
    serial, monitors, _logical, _props = state
    layout = _active_layout(state)
    profile = _match_profile(layout)
    if profile is None:
        return "no-match"
    if not verify and _layout_matches(profile, layout):
        return "already-correct"

    by_ident = {ident(m[0]): (m[0][0], m[1]) for m in monitors}

    logical_monitors = []
    for m in profile["monitors"]:
        entry = by_ident.get(m["id"])
        if entry is None:
            return "incomplete"
        connector, modes = entry
        mode_id = _find_mode_id(modes, m["w"], m["h"], m["rate"])
        if mode_id is None:
            return "no-mode"
        logical_monitors.append((
            m["x"], m["y"], m["scale"], m["transform"], m["primary"],
            [(connector, mode_id, {})],
        ))

    method = 0 if verify else 1  # 0=verify only, 1=apply (temporary)
    params = GLib.Variant(
        "(uua(iiduba(ssa{sv}))a{sv})",
        (serial, method, logical_monitors, {}),
    )
    bus.call_sync(
        BUS_NAME, OBJ_PATH, IFACE, "ApplyMonitorsConfig",
        params, None, Gio.DBusCallFlags.NONE, -1, None,
    )
    return "verified" if verify else "applied"


# --------------------------------------------------------------------------- #
# Watch service
# --------------------------------------------------------------------------- #
def watch():
    loop = GLib.MainLoop()
    bus = _bus()
    pending = {"id": 0}

    def do_apply():
        pending["id"] = 0
        try:
            result = apply_best()
        except GLib.Error as exc:
            result = f"error: {exc.message}"
        if result not in ("already-correct", "no-match"):
            print(f"[dockd] {result}", flush=True)
        return False  # one-shot

    def on_changed(*_args):
        if pending["id"]:
            GLib.source_remove(pending["id"])
        pending["id"] = GLib.timeout_add(DEBOUNCE_MS, do_apply)

    bus.signal_subscribe(
        BUS_NAME, IFACE, "MonitorsChanged", OBJ_PATH, None,
        Gio.DBusSignalFlags.NONE, on_changed,
    )
    print("[dockd] watching for monitor changes…", flush=True)
    GLib.timeout_add(DEBOUNCE_MS, do_apply)  # apply once at startup
    loop.run()


def status():
    layout = _active_layout(read_state())
    print(f"Active monitors ({len(layout)}):")
    for m in layout.values():
        tag = " *primary" if m["primary"] else ""
        print(f"  {m['id']:34} {m['w']}x{m['h']}@{m['rate']:.0f} "
              f"@({m['x']},{m['y']}){tag} [{m['connector']}]")
    profile = _match_profile(layout)
    if profile is None:
        print("No saved profile matches this monitor set.")
    elif _layout_matches(profile, layout):
        print(f"Matches saved profile '{profile['name']}' — already applied.")
    else:
        print(f"Saved profile '{profile['name']}' matches but is NOT applied "
              "(run --apply).")


def list_profiles():
    profiles = load_profiles()
    if not profiles:
        print("No saved profiles.")
        return
    for p in profiles:
        print(f"• {p['name']}  ({len(p['monitors'])} monitors)")
        for m in p["monitors"]:
            tag = " *primary" if m["primary"] else ""
            print(f"    {m['id']:34} {m['w']}x{m['h']}@{m['rate']:.0f} "
                  f"@({m['x']},{m['y']}){tag}")


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "--status"
    try:
        if cmd == "--save":
            save_current(argv[2] if len(argv) > 2 else None)
        elif cmd == "--apply":
            print(apply_best())
        elif cmd == "--verify":
            print(apply_best(verify=True))
        elif cmd == "--list":
            list_profiles()
        elif cmd == "--watch":
            watch()
        elif cmd in ("--status", "-s"):
            status()
        else:
            print(__doc__)
            return 2
    except GLib.Error as exc:
        print(f"D-Bus error: {exc.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
