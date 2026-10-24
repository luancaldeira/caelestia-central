pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io
import Caelestia.Config
import qs.utils
import qs.services
import qs.modules.launcher.services as Launcher

Singleton {
    id: root

    readonly property var applications: DesktopEntries.applications.values.filter(app =>
        !app.noDisplay && app.name && !Strings.testRegexList(GlobalConfig.launcher.hiddenApps, app.id))
    property var entries: []
    readonly property var favoriteEntries: entries.filter(entry => entry.favorite)
    property var order: []
    property var favorites: []
    property bool loaded: false
    property bool pendingOpen: false
    property string error: ""
    property var launchQueue: []
    property var armedLaunch: null

    function rebuild() {
        if (!loaded) return;
        const available = new Map(applications.map(app => [String(app.id), app]));
        const remaining = applications.filter(app => !order.includes(String(app.id)))
            .sort((a,b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
        order = order.filter(id => available.has(id)).concat(remaining.map(app => String(app.id)));
        entries = order.map(id => {
            const app = available.get(id);
            return {id:id,title:app.name,icon:app.icon,genericName:app.genericName,
                description:app.comment,favorite:favorites.includes(id)};
        });
    }
    function open() {
        if (!loaded) { pendingOpen = true; return; }
        // Keep identities and order stable while browsing or clicking the star.
        order = [...applications].sort((a,b) =>
            Number(favorites.includes(String(b.id))) - Number(favorites.includes(String(a.id))) ||
            a.name.localeCompare(b.name) || a.id.localeCompare(b.id)).map(app => String(app.id));
        error = "";
        rebuild();
    }
    function finishLoad() {
        loaded = true;
        if (pendingOpen) { pendingOpen = false; open(); }
        else rebuild();
    }
    function favorite(id) {
        id = String(id);
        if (!loaded || !applications.some(app => String(app.id) === id)) return;
        favorites = favorites.includes(id) ? favorites.filter(value => value !== id) : favorites.concat([id]);
        rebuild();
        saved.setText(JSON.stringify({version:1,favorites:favorites}));
    }
    function luaQuote(value) {
        return '"' + String(value).replace(/\\/g,"\\\\").replace(/"/g,'\\"').replace(/\n/g,"\\n").replace(/\r/g,"\\r") + '"';
    }
    function launchNext() {
        if (armedLaunch || !launchQueue.length) return;
        armedLaunch = launchQueue.shift();
        const app = applications.find(a => String(a.id) === armedLaunch.id);
        if (!app) { armedLaunch = null; Qt.callLater(launchNext); return; }
        const executable = String(app.command[0] ?? "").split("/").pop();
        const commandClass = ["env","sh","bash","flatpak","steam"].includes(executable) ? "" : executable;
        const classes = [app.id,app.startupClass,commandClass].filter(value => value);
        // The short preparation IPC completes before the original DesktopEntry
        // launch, keeping D-Bus activation, working directories and arguments intact.
        const o = armedLaunch.origin;
        const args = [luaQuote(classes.join("\n")),o.x,o.y,o.width,o.height,luaQuote(armedLaunch.focused)].join(",");
        launchPreparation.command = ["hyprctl","dispatch",`function() local p=hl.plugin.caelestia_minimize; if p and p.prepare_launch then p.prepare_launch(${args}) end end`];
        launchPreparation.running = true;
    }
    function finishPreparedLaunch() {
        const job = armedLaunch;
        armedLaunch = null;
        if (job) {
            const app = applications.find(a => String(a.id) === job.id);
            if (app && !activateExisting(app,job.origin)) execute(app);
        }
        Qt.callLater(launchNext);
    }
    function activateExisting(app, origin) {
        const names = [String(app.id).replace(/\.desktop$/,""),String(app.startupClass || "")].filter(Boolean).map(name => name.toLowerCase());
        const candidates = Hypr.toplevels.values.filter(t => names.includes(String(t.lastIpcObject.class || "").toLowerCase()) ||
            names.includes(String(t.lastIpcObject.initialClass || "").toLowerCase()));
        candidates.sort((a,b) => (a.lastIpcObject.focusHistoryID ?? 999) - (b.lastIpcObject.focusHistoryID ?? 999));
        const window = candidates[0];
        if (!window) return false;
        const address = Minimized.address(window.address);
        const pid = Number(window.lastIpcObject.pid);
        if (Minimized.entries.some(e => e.address === address && e.pid === pid)) {
            Minimized.restore(address,pid,origin);
        } else {
            const args = [luaQuote(address),pid,origin.x,origin.y,origin.width,origin.height].join(",");
            const guard = `${luaQuote(address)},${pid}`;
            Hypr.dispatch(`function() local p=hl.plugin.caelestia_minimize; if not p or not p.animation_state or p.animation_state(${guard}) then hl.dispatch(hl.dsp.focus({window=${luaQuote("address:0x" + address)}})); if p and p.restore_from then p.restore_from(${args}) end end end`);
        }
        error = "";
        return true;
    }
    function execute(app) {
        try {
            Launcher.Apps.launch(app,true);
            error = "";
            return true;
        } catch (e) {
            error = "Could not open " + app.name + ".";
            console.warn("ApplicationLibrary:", e);
            return false;
        }
    }
    function launch(id, origin) {
        const app = applications.find(app => String(app.id) === String(id));
        if (!app) { error = "This application is no longer installed."; return false; }
        if (origin && Hypr.usingLua && !ShellState.sessionLocked &&
            [origin.x,origin.y,origin.width,origin.height].every(Number.isFinite)) {
            launchQueue.push({id:String(id),origin:origin,focused:Hypr.activeToplevel?.address ?? ""});
            launchNext();
            return true;
        }
        return execute(app);
    }
    Process {
        id: launchPreparation
        onExited: root.finishPreparedLaunch()
    }
    onApplicationsChanged: rebuild()

    FileView {
        id: saved
        path: Paths.state + "/central-apps.json"
        printErrors: false
        watchChanges: true
        atomicWrites: true
        onFileChanged: reload()
        onLoaded: {
            try {
                const data = JSON.parse(text());
                if (!Array.isArray(data.favorites)) throw new Error("Invalid favorites");
                root.favorites = [...new Set(data.favorites.filter(id => typeof id === "string"))];
            } catch (e) { console.warn("ApplicationLibrary: invalid saved favorites", e); }
            root.finishLoad();
        }
        onLoadFailed: {
            if (!root.loaded)
                root.favorites = root.applications.filter(app => Strings.testRegexList(GlobalConfig.launcher.favouriteApps, app.id)).map(app => String(app.id));
            root.finishLoad();
        }
    }
    IpcHandler {
        target: "appcentral"
        function list(): string { return JSON.stringify(root.entries); }
        function info(): string { return JSON.stringify({count:root.entries.length,favorites:root.favorites,error:root.error,loaded:root.loaded}); }
        function favorite(id: string): void { root.favorite(id); }
        function launch(id: string): bool { return root.launch(id); }
        function refresh(): void { root.open(); }
    }
}
