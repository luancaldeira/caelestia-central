pragma Singleton

import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Dialogs as Dialogs
import qs.components
import qs.components.controls
import Caelestia.Config
import Quickshell
import Quickshell.Io

Singleton {
    id: root

    readonly property string controller: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/wallpaperengine/wallpaperctl"
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
    function folder(action, path) {
        error = "";
        jobs = jobs.concat([[action, String(path)]]);
        pump();
    }
    function manageFolders() { foldersWindow.activeAsync = true; }
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
        function info(): string { return JSON.stringify({count:root.entries.length,active:root.activeId,busy:root.busy,error:root.error,foldersOpen:foldersWindow.active}); }
        function favorite(id: string): void { root.favorite(id); }
        function apply(id: string): void { root.apply(id); }
        function refresh(): void { root.refresh(); }
        function folders(): void { root.manageFolders(); }
        function closeFolders(): void { foldersWindow.active = false; }
    }
    LazyLoader {
        id: foldersWindow
        FloatingWindow {
            id: manager
            title: "Wallpaper folders"
            implicitWidth: 640
            implicitHeight: 360
            minimumSize.width: implicitWidth
            minimumSize.height: implicitHeight
            maximumSize.width: implicitWidth
            maximumSize.height: implicitHeight
            color: Colours.tPalette.m3surface
            surfaceFormat.opaque: false
            onVisibleChanged: if (!visible) foldersWindow.active = false
            ColumnLayout {
                id: foldersLayout
                anchors.fill: parent
                anchors.margins: 24
                spacing: 16
                RowLayout {
                    Layout.fillWidth: true
                    StyledText { text: "Wallpaper folders"; font: Tokens.font.title.large }
                    Item { Layout.fillWidth: true }
                    IconTextButton {
                        icon: "create_new_folder"
                        text: "Add folder"
                        onClicked: folderDialog.open()
                    }
                }
                StyledText {
                    Layout.fillWidth: true
                    text: "Local images and GIFs · Steam Workshop is optional"
                    color: Colours.palette.m3onSurfaceVariant
                    wrapMode: Text.WordWrap
                }
                ListView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 8
                    model: root.state.folders || []
                    delegate: RowLayout {
                        id: folderRow
                        required property var modelData
                        width: ListView.view.width
                        spacing: 12
                        MaterialIcon { text: folderRow.modelData.available ? "folder" : "folder_off" }
                        StyledText {
                            Layout.fillWidth: true
                            text: folderRow.modelData.path
                            elide: Text.ElideMiddle
                            color: folderRow.modelData.available ? Colours.palette.m3onSurface : Colours.palette.m3error
                        }
                        IconButton {
                            icon: "remove_circle_outline"
                            Accessible.name: "Remove folder from library"
                            onClicked: root.folder("folder-remove", folderRow.modelData.path)
                        }
                    }
                    StyledText {
                        anchors.centerIn: parent
                        visible: (root.state.folders || []).length === 0
                        text: "No local folders added"
                        color: Colours.palette.m3onSurfaceVariant
                    }
                }
                StyledText {
                    Layout.fillWidth: true
                    visible: root.message.length > 0
                    text: root.message
                    color: root.error || root.state.error ? Colours.palette.m3error : Colours.palette.m3onSurfaceVariant
                    wrapMode: Text.WordWrap
                }
                IconTextButton {
                    Layout.alignment: Qt.AlignRight
                    icon: "check"
                    text: "Done"
                    onClicked: foldersWindow.active = false
                }
            }
            Dialogs.FolderDialog {
                id: folderDialog
                parentWindow: foldersLayout.Window.window
                title: "Choose a wallpaper folder"
                currentFolder: "file://" + Quickshell.env("HOME")
                onAccepted: root.folder("folder-add", decodeURIComponent(selectedFolder.toString().replace(/^file:\/\//, "")))
            }
        }
    }

}
