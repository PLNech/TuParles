// TuParles Focus Window — the missing piece for paste-into-focus on Wayland.
//
// On X11 the daemon runs `xdotool getactivewindow getwindowclassname` to tell
// a terminal (wants Ctrl+Shift+V) from a regular app (Ctrl+V). Wayland forbids
// a client from reading the focused window, so that query has no equivalent —
// except from inside the compositor. This extension does exactly that one
// thing: expose the focused window's class on the session bus. No UI, no
// timers, no signals; it only answers when asked.

import Gio from 'gi://Gio';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `
<node>
  <interface name="org.tuparles.FocusWindow">
    <method name="GetClass">
      <arg type="s" direction="out" name="wmclass"/>
    </method>
  </interface>
</node>`;

export default class FocusWindowExtension extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/org/tuparles/FocusWindow');
        this._nameId = Gio.bus_own_name_on_connection(
            Gio.DBus.session,
            'org.tuparles.FocusWindow',
            Gio.BusNameOwnerFlags.REPLACE,
            null,
            null);
    }

    disable() {
        if (this._nameId) {
            Gio.bus_unown_name(this._nameId);
            this._nameId = 0;
        }
        if (this._dbus) {
            this._dbus.unexport();
            this._dbus = null;
        }
    }

    // Returns "class|instance" of the focused window (either field may be
    // empty). TuParles matches a terminal against either half, because the
    // matching token lives in different fields per app: gnome-terminal carries
    // it in the instance ("gnome-terminal-server"), kitty/Alacritty in both.
    // Empty string when nothing is focused.
    GetClass() {
        const win = global.display.focus_window;
        if (!win)
            return '';
        const cls = win.get_wm_class() || '';
        const inst = win.get_wm_class_instance() || '';
        return `${cls}|${inst}`;
    }
}
