pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import qs.services
import qs.utils

Singleton {
    id: root

    readonly property string workspace: "special:caelestia-minimized"
    readonly property string session: Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE")
    readonly property string thumbnailDir: Paths.cache + "/minimized"
    property var entries: []
    property var moving: ({})
    property var thumbnailRequests: ({})
    property bool loaded: false
    property bool ready: false
    readonly property int count: entries.length

    signal captureRequested(var toplevel, string address, string path)

    function address(value) { return String(value).replace(/^0x/, ""); }
    function find(value) {
        const a = address(value);
        return Hypr.toplevels.values.find(t => address(t.address) === a) ?? null;
    }
    function quote(value) {
        // Workspace selectors are data, never executable Lua.
        return '"' + String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n").replace(/\r/g, "\\r") + '"';
    }
    function selector(value) { return quote("address:0x" + address(value)); }
    function save() {
        if (loaded)
            state.setText(JSON.stringify({session: session, entries: entries}));
    }
    function minimize(value) {
        const t = value ? find(value) : Hypr.activeToplevel;
        if (!t)
            return;
        const a = address(t.address);
        if (entries.some(e => e.address === a))
            return;
        const ipc = t.lastIpcObject;
        if (ipc.workspace?.name === workspace)
            return;
        const record = {
            address: a, pid: ipc.pid, title: t.title, appId: ipc.class,
            workspace: ipc.workspace?.name ?? String(Hypr.activeWsId),
            pinned: ipc.pinned ?? false, floating: ipc.floating ?? false, monitor: t.monitor?.name ?? "",
            at: Array.from(ipc.at ?? []), size: Array.from(ipc.size ?? []),
            thumbnail: "", time: Date.now()
        };
        Hyprland.refreshToplevels();
        // Motion must not wait for GPU readback or PNG encoding. The thumbnail
        // is captured only after the native client reaches the hidden workspace.
        beginMinimize(record);
    }
    function beginMinimize(record) {
        const a = record.address;
        const t = find(a);
        if (!t || t.lastIpcObject.pid !== record.pid)
            return;
        const ipc = t.lastIpcObject;
        record.workspace = ipc.workspace?.name ?? record.workspace;
        record.floating = ipc.floating ?? record.floating;
        record.pinned = ipc.pinned ?? record.pinned;
        record.at = Array.from(ipc.at ?? record.at);
        record.size = Array.from(ipc.size ?? record.size);
        record.monitor = t.monitor?.name ?? record.monitor;
        entries = [record, ...entries];
        moving[a] = Date.now();
        save();
        const commands = [];
        if (record.pinned)
            commands.push(`hl.dsp.window.pin({window=${selector(a)},action="off"})`);
        commands.push(`hl.dsp.window.move({window=${selector(a)},workspace=${quote(workspace)},follow=false})`);
        const screen = Screens.screens.find(s => s.name === record.monitor);
        const destination = screen ? ShellState.componentsFor(screen)?.panels?.minimized?.minimizeTarget() : null;
        if (destination && !ShellState.sessionLocked && Hypr.usingLua) {
            const args = [quote(a),Number(record.pid),destination.x,destination.y,destination.width,destination.height].join(",");
            const fallback = commands.map(command => `hl.dispatch(${command})`).join("; ");
            Hypr.dispatch(`function() local p=hl.plugin.caelestia_minimize; if not (p and p.minimize_to and p.minimize_to(${args})) then ${fallback} end end`);
        } else {
            commands.forEach(command => Hypr.dispatch(command));
        }
        settle.restart();
    }
    function completeThumbnail(value, imagePath, capturedPid) {
        const a = address(value);
        const entry = entries.find(e => e.address === a && e.pid === capturedPid);
        if (entry && imagePath === thumbnailDir + "/" + a + "-" + entry.time + ".png") {
            entries = entries.map(e => e === entry ? Object.assign({},e,{thumbnail:imagePath}) : e);
            save();
        } else if (imagePath.startsWith(thumbnailDir + "/")) {
            Quickshell.execDetached(["rm", "-f", imagePath]);
        }
    }
    function requestThumbnails() {
        if (WindowDrawer.motions.count > 0 || ShellState.sessionLocked) return;
        for (const entry of entries) {
            if (entry.thumbnail || thumbnailRequests[entry.address] === entry.time) continue;
            const t = find(entry.address);
            if (!t || t.lastIpcObject.pid !== entry.pid || t.workspace?.name !== workspace) continue;
            thumbnailRequests[entry.address] = entry.time;
            captureRequested(t, entry.address, thumbnailDir + "/" + entry.address + "-" + entry.time + ".png");
        }
    }
    function updateMotionGeometry(frame) {
        if (!frame.minimizing || frame.done) return;
        const record = entries.find(e => e.address === frame.address && e.pid === frame.pid);
        if (!record) return;
        // The native layout goal is authoritative, including a floating move
        // that occurred before the asynchronous toplevel refresh completed.
        record.at = [frame.x,frame.y];
        record.size = [frame.width,frame.height];
        save();
    }
    function restore(value, expectedPid, origin, keepHub = false) {
        const a = address(value);
        const record = entries.find(e => e.address === a);
        const t = find(a);
        if (!record || !t || t.lastIpcObject.pid !== record.pid ||
            (expectedPid !== undefined && Number(expectedPid) !== record.pid))
            return;
        moving[a] = Date.now();
        // Batch restores from the hub stay on this workspace and retain layer focus.
        // External restores still return to the saved workspace, recreating it if needed.
        const destinationWorkspace = keepHub ? String(Hypr.activeWsId) : record.workspace;
        const commands = [`hl.dsp.window.move({window=${selector(a)},workspace=${quote(destinationWorkspace)},follow=false})`];
        if (record.floating && record.at?.length === 2 && record.size?.length === 2 &&
            Hypr.monitors.values.some(m => m.name === record.monitor)) {
            commands.push(`hl.dsp.window.resize({window=${selector(a)},x=${Number(record.size[0])},y=${Number(record.size[1])},relative=false})`);
            commands.push(`hl.dsp.window.move({window=${selector(a)},x=${Number(record.at[0])},y=${Number(record.at[1])},relative=false})`);
        }
        if (record.pinned)
            commands.push(`hl.dsp.window.pin({window=${selector(a)},action="on"})`);
        // Keep the layer surface focused for successive restores. Focusing a
        // client here also warps the pointer and clears the shell focus grab.
        if (!keepHub) commands.push(`hl.dsp.focus({window=${selector(a)}})`);
        const animate = origin && !ShellState.sessionLocked && Hypr.usingLua &&
            [origin.x,origin.y,origin.width,origin.height].every(Number.isFinite) && origin.width >= 8 && origin.height >= 8;
        if (Hypr.usingLua) {
            // The move, layout, focus and animation begin in one compositor turn.
            // Older/unavailable plugins simply leave the normal restore intact.
            const args = animate ? [quote(a),Number(record.pid),origin.x,origin.y,origin.width,origin.height].join(",") : [quote(a),Number(record.pid)].join(",");
            const action = animate ? "restore_from" : "cancel_minimize";
            Hypr.dispatch(`function() ${commands.map(command => `hl.dispatch(${command})`).join("; ")}; local p=hl.plugin.caelestia_minimize; if p and p.${action} then p.${action}(${args}) end end`);
        } else {
            commands.forEach(command => Hypr.dispatch(command));
        }
        entries = entries.filter(e => e.address !== a);
        delete thumbnailRequests[a];
        removeThumbnail(record);
        save();
        settle.restart();
    }
    function close(value, expectedPid) {
        const a = address(value);
        const record = entries.find(e => e.address === a);
        const t = find(a);
        if (!record || !t || t.lastIpcObject.pid !== record.pid ||
            (expectedPid !== undefined && Number(expectedPid) !== record.pid))
            return;
        // Ask the application to close normally; unsaved documents can still veto it.
        Hypr.dispatch(`hl.dsp.window.close({window=${selector(a)}})`);
    }
    function forget(value) {
        const a = address(value);
        const record = entries.find(e => e.address === a);
        if (record) {
            entries = entries.filter(e => e.address !== a);
            removeThumbnail(record);
            save();
        }
        delete moving[a];
        delete thumbnailRequests[a];
    }
    function restoreAll() {
        for (const e of [...entries].reverse())
            restore(e.address);
    }
    function removeThumbnail(record) {
        if (record.thumbnail.startsWith(thumbnailDir + "/"))
            Quickshell.execDetached(["rm", "-f", record.thumbnail]);
    }
    function reconcile() {
        if (!loaded || !ready)
            return;
        const kept = [];
        for (const record of entries) {
            const t = find(record.address);
            if (t && t.lastIpcObject.pid === record.pid &&
                (t.workspace?.name === workspace || Date.now() - (moving[record.address] ?? 0) < 3000)) {
                kept.push(Object.assign({}, record, {title: t.title}));
            } else {
                removeThumbnail(record);
            }
        }
        // Recover hidden windows even if the shell was restarted before its state was saved.
        for (const t of Hypr.toplevels.values) {
            const a = address(t.address);
            if (t.workspace?.name === workspace && !kept.some(e => e.address === a) &&
                Date.now() - (moving[a] ?? 0) >= 1200) {
                kept.push({address:a, pid:t.lastIpcObject.pid, title:t.title,
                    appId:t.lastIpcObject.class, workspace:String(Hypr.activeWsId),
                    pinned:false, thumbnail:"", time:Date.now()});
            }
        }
        if (JSON.stringify(kept) !== JSON.stringify(entries)) {
            entries = kept;
            save();
        }
        thumbnailIdle.restart();
    }
    function toggle() {
        const s = ShellState.forActive();
        if (s) {
            s.launcher = false;
            s.minimized = !s.minimized;
        }
    }

    Component.onCompleted: {
        Quickshell.execDetached(["mkdir", "-p", thumbnailDir]);
        Hyprland.refreshToplevels();
        startup.start();
    }

    FileView {
        id: state
        path: Paths.state + "/minimized.json"
        printErrors: false
        atomicWrites: true
        onLoaded: {
            try {
                const data = JSON.parse(text());
                if (data.session === root.session && Array.isArray(data.entries))
                    root.entries = data.entries;
            } catch (e) { console.warn("Minimized: invalid saved state", e); }
            root.loaded = true;
        }
        onLoadFailed: root.loaded = true
    }

    Timer {
        id: startup
        interval: 1200
        onTriggered: { root.ready = true; root.reconcile(); }
    }
    Timer {
        id: settle
        interval: 1400
        onTriggered: { Hyprland.refreshToplevels(); root.reconcile(); }
    }
    Timer {
        id: thumbnailIdle
        interval: 120
        onTriggered: root.requestThumbnails()
    }
    onEntriesChanged: thumbnailIdle.restart()
    Connections {
        target: WindowDrawer.motions
        function onCountChanged() { if (!WindowDrawer.motions.count) thumbnailIdle.restart(); }
    }
    Connections {
        target: ShellState
        function onSessionLockedChanged() { if (!ShellState.sessionLocked) thumbnailIdle.restart(); }
    }
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (event.name === "caelestia_minimize" || event.name === "minimized") {
                const parts = event.data.split(",");
                if (parts[1] === "1") root.minimize(parts[0]);
                else if (parts[1] === "0") root.restore(parts[0]);
            } else if (event.name === "caelestia_minimize_done") {
                const [a, pid, hidden] = event.data.split(",");
                const record = root.entries.find(e => e.address === a && e.pid === Number(pid));
                if (record) {
                    if (hidden === "0") root.forget(a);
                    else root.moving[a] = Date.now();
                }
                Hyprland.refreshToplevels();
                settle.restart();
                thumbnailIdle.restart();
            } else if (event.name === "caelestia_drawer") {
                try { root.updateMotionGeometry(JSON.parse(event.data)); }
                catch (e) { console.warn("Minimized: invalid motion geometry",e); }
            } else if (event.name === "closewindow") {
                root.forget(event.data);
                settle.restart();
            } else if (["closewindow", "movewindow", "windowtitle", "openwindow"].includes(event.name)) {
                settle.restart();
            }
        }
    }
    IpcHandler {
        target: "minimized"
        function toggle(): void { root.toggle(); }
        function minimize(): void { root.minimize(""); }
        function minimizeWindow(address: string): void { root.minimize(address); }
        function restore(address: string): void { root.restore(address); }
        function close(address: string): void { root.close(address); }
        function restoreAll(): void { root.restoreAll(); }
        function list(): string { return JSON.stringify(root.entries); }
        function next(): void { ShellState.componentsForActive()?.panels?.minimized?.cycle(1); }
        function previous(): void { ShellState.componentsForActive()?.panels?.minimized?.cycle(-1); }
        function tab(index: int): void { ShellState.componentsForActive()?.panels?.minimized?.setTab(index); }
        function info(): string { return ShellState.componentsForActive()?.panels?.minimized?.info() ?? "{}"; }
        function selected(): string { return ShellState.componentsForActive()?.panels?.minimized?.currentEntry?.address ?? ""; }
    }
}
