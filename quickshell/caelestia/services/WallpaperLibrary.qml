pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    readonly property string controller: Quickshell.env("HOME") + "/.config/wallpaperengine/wallpaperctl"
    readonly property string stateRoot: Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state"
    property var state: ({items: []})
    property var entries: []
    property var order: []
    property var jobs: []
    property string error: ""
    readonly property bool busy: !!state.busy || command.running || jobs.length > 0
    readonly property string activeId: state.active ?? ""
    readonly property string message: error || state.error || (busy ? state.message || "Applying wallpaper…" : "")

    function key(item) { return String(item.id); }
    function update(text) {
        try {
            const data = JSON.parse(text);
            if (!Array.isArray(data.items)) return;
            state = data;
            const remaining = data.items.filter(i => !order.includes(key(i)));
            order = order.filter(id => data.items.some(i => key(i) === id)).concat(remaining.map(key));
            entries = order.map(id => data.items.find(i => key(i) === id));
        } catch (e) { console.warn("WallpaperLibrary: invalid controller status", e); }
    }
    function open() {
        // Freeze this order while browsing. Starring a card never moves it under the pointer.
        order = [...state.items].sort((a, b) => Number(!!b.favorite) - Number(!!a.favorite) ||
            a.title.localeCompare(b.title) || key(a).localeCompare(key(b))).map(key);
        entries = order.map(id => state.items.find(i => key(i) === id));
        refresh();
    }
    function refresh() {
        status.reload();
        if (!synchronize.running) synchronize.running = true;
    }
    function run(action, id) {
        const item = state.items.find(i => key(i) === String(id));
        if (!item || (action === "apply" && item.missing)) return;
        error = "";
        jobs = jobs.concat([[action, String(id)]]);
        pump();
    }
    function pump() {
        if (command.running || jobs.length === 0) return;
        const job = jobs[0];
        jobs = jobs.slice(1);
        command.command = [controller].concat(job);
        command.running = true;
    }
    function apply(id) { run("apply", id); }
    function favorite(id) { run("favorite", id); }

    FileView {
        id: status
        path: root.stateRoot + "/wallpaperengine/status.json"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: root.update(text())
    }
    Process {
        id: synchronize
        command: [root.controller, "refresh"]
        onExited: status.reload()
    }
    Process {
        id: command
        stderr: StdioCollector { id: commandError }
        onExited: (exitCode, exitStatus) => {
            if (exitCode !== 0) root.error = commandError.text.trim() || "Could not complete the action.";
            status.reload();
            Qt.callLater(root.pump);
        }
    }
    IpcHandler {
        target: "wallpapercentral"
        function list(): string { return JSON.stringify(root.entries); }
        function info(): string { return JSON.stringify({count:root.entries.length,active:root.activeId,busy:root.busy,error:root.error}); }
        function favorite(id: string): void { root.favorite(id); }
        function apply(id: string): void { root.apply(id); }
        function refresh(): void { root.refresh(); }
    }
}
