#!/usr/bin/env python3
"""Lid Behaviour — choose what closing the laptop lid does.

A small GTK4/libadwaita app that gives you Windows-11-style control over
GNOME's lid-close actions, separately for "Plugged in" and "On battery".

It writes the standard GNOME settings-daemon keys via GSettings, so changes
take effect immediately — no config files, no terminal, no root.

Keys used (schema: org.gnome.settings-daemon.plugins.power):
  * lid-close-ac-action                     -> "Plugged in"
  * lid-close-battery-action                -> "On battery"
  * lid-close-suspend-with-external-monitor -> "Stay awake with a monitor"
"""

import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

APP_ID = "no.finter.LidBehaviour"
SERVICE = "lidbehaviour-dock.service"
DOCKD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dockd.py")
SCHEMA = "org.gnome.settings-daemon.plugins.power"
KEY_AC = "lid-close-ac-action"
KEY_BAT = "lid-close-battery-action"
KEY_EXT = "lid-close-suspend-with-external-monitor"

# Windows-like labels mapped to GNOME enum values, in display order.
ACTIONS = [
    ("nothing", "Do nothing"),
    ("suspend", "Sleep"),
    ("hibernate", "Hibernate"),
    ("shutdown", "Shut down"),
]

AC_ONLINE_PATHS = (
    "/sys/class/power_supply/AC/online",
    "/sys/class/power_supply/AC0/online",
    "/sys/class/power_supply/ACAD/online",
)


def power_is_ac():
    """True if the laptop is currently on AC power (best effort)."""
    for path in AC_ONLINE_PATHS:
        try:
            with open(path) as fh:
                return fh.read().strip() == "1"
        except OSError:
            continue
    return True  # assume plugged in if we cannot tell


def schema_is_installed(schema_id):
    src = Gio.SettingsSchemaSource.get_default()
    return src is not None and src.lookup(schema_id, True) is not None


class ActionComboRow:
    """An Adw.ComboRow bound two-way to a string-enum GSettings key."""

    def __init__(self, settings, key, title, subtitle=""):
        self.settings = settings
        self.key = key
        self._syncing = False

        self.values = [value for value, _ in ACTIONS]
        labels = [label for _, label in ACTIONS]

        # Don't clobber a value set elsewhere that we don't have a label for.
        current = settings.get_string(key)
        if current not in self.values:
            self.values.append(current)
            labels.append(current.replace("-", " ").capitalize())

        self.row = Adw.ComboRow(title=title, subtitle=subtitle)
        self.row.set_model(Gtk.StringList.new(labels))
        self._select(current)

        self.row.connect("notify::selected", self._on_selected)
        settings.connect(f"changed::{key}", self._on_external_change)

    def _select(self, value):
        self._syncing = True
        self.row.set_selected(self.values.index(value))
        self._syncing = False

    def _on_selected(self, row, _pspec):
        if self._syncing:
            return
        index = row.get_selected()
        if 0 <= index < len(self.values):
            self.settings.set_string(self.key, self.values[index])

    def _on_external_change(self, settings, key):
        value = settings.get_string(key)
        if value in self.values and not self._syncing:
            self._select(value)


class LidBehaviourWindow(Adw.ApplicationWindow):
    def __init__(self, app, settings):
        super().__init__(application=app, title="Lid Behaviour")
        self.settings = settings
        self.set_default_size(480, 540)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        page = Adw.PreferencesPage()

        # --- When I close the lid ------------------------------------------
        lid_group = Adw.PreferencesGroup(
            title="When I close the lid",
            description="Pick what happens — just like Windows Power Options.",
        )
        on_ac = power_is_ac()
        self.ac_row = ActionComboRow(
            settings, KEY_AC, "Plugged in",
            "Currently active" if on_ac else "",
        )
        self.bat_row = ActionComboRow(
            settings, KEY_BAT, "On battery",
            "" if on_ac else "Currently active",
        )
        lid_group.add(self.ac_row.row)
        lid_group.add(self.bat_row.row)
        page.add(lid_group)

        # --- External monitors ---------------------------------------------
        ext_group = Adw.PreferencesGroup(title="External monitors")
        ext_row = Adw.ActionRow(
            title="Stay awake with an external monitor",
            subtitle="When a monitor is connected, ignore the lid action above",
        )
        self.ext_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        # The GSettings key means "suspend EVEN with a monitor", so invert it.
        self.ext_switch.set_active(not settings.get_boolean(KEY_EXT))
        self.ext_switch.connect("state-set", self._on_ext_toggle)
        ext_row.add_suffix(self.ext_switch)
        ext_row.set_activatable_widget(self.ext_switch)
        ext_group.add(ext_row)
        page.add(ext_group)

        # --- Note ----------------------------------------------------------
        note_group = Adw.PreferencesGroup()
        note = Adw.ActionRow(
            title="Good to know",
            subtitle=(
                "Docked usually means “Plugged in”. Set it to "
                "“Do nothing” to keep working on your external "
                "screens with the lid shut. Hibernate needs enough swap "
                "space, otherwise the system sleeps instead."
            ),
        )
        note.set_subtitle_lines(0)  # wrap freely
        note_group.add(note)
        page.add(note_group)

        self._build_dock_group(page)

        self.toasts = Adw.ToastOverlay()
        self.toasts.set_child(page)
        toolbar.set_content(self.toasts)
        self.set_content(toolbar)

    # --- Dock display layout ----------------------------------------------
    def _build_dock_group(self, page):
        group = Adw.PreferencesGroup(
            title="Dock display layout",
            description=(
                "Remember your external-monitor arrangement and refresh rates "
                "by monitor serial, so they survive docking — even when the "
                "dock renames the ports."
            ),
        )

        save_row = Adw.ActionRow(
            title="Save current arrangement",
            subtitle="Capture how the screens are laid out right now",
        )
        save_btn = Gtk.Button(label="Save", valign=Gtk.Align.CENTER)
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save_layout)
        save_row.add_suffix(save_btn)
        save_row.set_activatable_widget(save_btn)
        group.add(save_row)

        auto_row = Adw.ActionRow(
            title="Automatically restore on dock",
            subtitle="Runs a small background service for this session",
        )
        self.auto_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.auto_switch.set_active(self._service_enabled())
        self.auto_switch.connect("state-set", self._on_auto_toggle)
        auto_row.add_suffix(self.auto_switch)
        auto_row.set_activatable_widget(self.auto_switch)
        group.add(auto_row)

        page.add(group)

    def _toast(self, text):
        self.toasts.add_toast(Adw.Toast.new(text))

    def _dockd(self, *args):
        return subprocess.run(
            [sys.executable, DOCKD, *args],
            capture_output=True, text=True, timeout=20,
        )

    def _on_save_layout(self, _btn):
        try:
            res = self._dockd("--save")
            ok = res.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        self._toast("Arrangement saved" if ok else "Couldn't save arrangement")

    def _service_enabled(self):
        try:
            res = subprocess.run(
                ["systemctl", "--user", "is-enabled", SERVICE],
                capture_output=True, text=True, timeout=10,
            )
            return res.stdout.strip() == "enabled"
        except (OSError, subprocess.SubprocessError):
            return False

    def _on_auto_toggle(self, switch, state):
        verb = ["enable", "--now"] if state else ["disable", "--now"]
        try:
            res = subprocess.run(
                ["systemctl", "--user", *verb, SERVICE],
                capture_output=True, text=True, timeout=15,
            )
            ok = res.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        if ok:
            self._toast("Auto-restore on" if state else "Auto-restore off")
            switch.set_state(state)
        else:
            self._toast("Service not installed yet — run install.sh")
            switch.set_active(False)
            switch.set_state(False)
        return True  # we set the state explicitly above

    def _on_ext_toggle(self, _switch, state):
        self.settings.set_boolean(KEY_EXT, not state)
        return False  # let the switch update its visual state


class LidBehaviourApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.settings = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        if schema_is_installed(SCHEMA):
            self.settings = Gio.Settings.new(SCHEMA)

    def do_activate(self):
        win = self.props.active_window
        if win is None:
            if self.settings is None:
                self._show_missing_schema()
                return
            win = LidBehaviourWindow(self, self.settings)
        win.present()

    def _show_missing_schema(self):
        dialog = Adw.MessageDialog(
            heading="Unsupported desktop",
            body=(
                "The GNOME power settings schema was not found, so this tool "
                "cannot control the lid behaviour on this system."
            ),
        )
        dialog.add_response("ok", "Close")
        dialog.connect("response", lambda *_: self.quit())
        dialog.present()


def main():
    return LidBehaviourApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
