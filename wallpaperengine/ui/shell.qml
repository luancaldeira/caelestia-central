import QtQuick
import QtQuick.Window
import QtQuick.Controls.Basic
import QtQuick.Dialogs as Dialogs
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root
    property bool opened: false
    property var state: ({ items: [], preferences: {} })
    property var catalogItems: []
    property string catalogText: ""
    property var palette: ({})
    property string selectedId: ""
    property string category: "All"
    property string query: ""
    property string actionError: ""
    property string lastStateText: ""
    property var jobs: []
    readonly property string dataRoot: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state")
    readonly property string controller: Quickshell.shellPath("../wallpaperctl")
    readonly property var selected: catalogItems.find(i => i.id === selectedId) || ({})
    readonly property var preferences: (state.preferences || {})[selectedId] || ({})
    readonly property var preview: state.preview?.id === selectedId ? state.preview : (state.active === selectedId ? state.theme || {} : {})
    readonly property var filtered: catalogItems.filter(i => {
        const matches = (i.title + " " + i.id).toLocaleLowerCase().includes(query.toLocaleLowerCase());
        return matches && (category === "All" || category === "Favorites" && i.favorite ||
            category === "Recent" && i.recent < 999 || category === "Videos" && i.type === "video" ||
            category === "Scenes" && i.type === "scene");
    }).sort((a, b) => category === "Recent" ? a.recent - b.recent : a.title.localeCompare(b.title));
    onFilteredChanged: Qt.callLater(() => {
        if (root.filtered.length && !root.filtered.some(i => i.id === root.selectedId)) root.choose(root.filtered[0]);
    })

    function col(name, fallback): color { return palette[name] ? "#" + palette[name] : fallback; }
    readonly property color surface: col("surfaceContainer", "#171a23")
    readonly property color raised: col("surfaceContainerHigh", "#222633")
    readonly property color base: col("surface", "#10131c")
    readonly property color ink: col("onSurface", "#e5e7ef")
    readonly property color muted: col("onSurfaceVariant", "#b0b6c8")
    readonly property color accent: col("primary", "#b6c8f4")
    readonly property color onAccent: col("onPrimary", "#18304e")
    readonly property color outline: col("outlineVariant", "#434958")

    function run(args): void { jobs.push(args); pump(); }
    function pump(): void {
        if (command.running || jobs.length === 0) return;
        command.command = [controller].concat(jobs.shift());
        command.running = true;
    }
    function choose(item): void {
        selectedId = item.id;
        previewTimer.restart();
    }
    function option(key, value): void {
        if (!selectedId) return;
        const opts = {}; opts[key] = value;
        run(["theme-options", selectedId, JSON.stringify(opts)]);
    }
    function showPicker(): void {
        stateFile.reload();
        opened = true;
        actionError = "";
        search.text = "";
        category = "All";
        selectedId = state.active || state.items?.[0]?.id || "";
        previewTimer.restart();
        Qt.callLater(() => { search.forceActiveFocus(); grid.positionViewAtIndex(root.filtered.findIndex(i => i.id === root.selectedId), GridView.Contain); });
    }
    function hidePicker(): void { opened = false; }
    function applySelected(): void {
        if (selectedId && !selected.missing) {
            actionError = "";
            run(["apply", selectedId]);
        }
    }
    function loadState(text): void {
        if (text === lastStateText) return;
        try {
            const data = JSON.parse(text);
            const itemsText = JSON.stringify(data.items || []);
            if (itemsText !== catalogText) { catalogText = itemsText; catalogItems = data.items || []; }
            state = data;
            lastStateText = text;
            if (!selectedId) selectedId = state.active || state.items?.[0]?.id || "";
        } catch (e) { actionError = "Waiting for library data…"; }
    }
    function typeLabel(item): string {
        return item.type === "scene" ? "Animated scene" : item.type === "video" ? "Video" : item.type === "web" ? "Web · check compatibility" : item.type === "image" ? "Local image" : "Unknown type";
    }
    function navigate(delta): void {
        if (!filtered.length) return;
        const index = Math.max(0, Math.min(filtered.length - 1, filtered.findIndex(i => i.id === selectedId) + delta));
        grid.currentIndex = index;
        choose(filtered[index]);
        grid.positionViewAtIndex(index, GridView.Contain);
    }

    FileView {
        id: stateFile
        path: root.dataRoot + "/wallpaperengine/status.json"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: root.loadState(text())
    }
    FileView {
        path: root.dataRoot + "/caelestia/scheme.json"
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: { try { root.palette = JSON.parse(text()).colours; } catch (e) {} }
    }
    Process {
        id: command
        stderr: StdioCollector { id: commandError }
        onExited: (exitCode, exitStatus) => {
            if (exitCode !== 0) root.actionError = commandError.text.trim();
            Qt.callLater(() => root.pump());
        }
    }
    Timer {
        interval: 1500
        running: root.opened
        repeat: true
        onTriggered: stateFile.reload()
    }
    Timer {
        id: previewTimer
        interval: 250
        onTriggered: { if (root.opened && root.selectedId) root.run(["preview", root.selectedId]); }
    }
    IpcHandler {
        target: "picker"
        function open(): void { root.showPicker(); }
        function close(): void { root.hidePicker(); }
        function toggle(): void { root.opened ? root.hidePicker() : root.showPicker(); }
        function selectItem(id: string): void { root.selectedId = id; previewTimer.restart(); }
        function setSearch(query: string): void { search.text = query; }
        function applySelection(): void { root.applySelected(); }
        function folders(): void { folderManager.open(); }
        function closeFolders(): void { folderManager.close(); }
        function chooseFolder(): void { localFolder.open(); }
        function cancelFolder(): void { localFolder.close(); }
        function info(): string { return JSON.stringify({open: root.opened, selected: root.selectedId, items: root.filtered.length, foldersOpen:folderManager.opened,choosingFolder:localFolder.visible}); }
    }

    component ActionButton: Button {
        id: button
        property bool filled: false
        property bool active: false
        implicitHeight: 38
        implicitWidth: Math.max(38, label.implicitWidth + 24)
        font.pixelSize: 13
        contentItem: Text {
            id: label
            text: button.text
            color: !button.enabled ? root.muted : button.filled ? root.onAccent : button.active ? root.accent : root.ink
            font: button.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        background: Rectangle {
            radius: 12
            opacity: button.enabled ? 1 : .45
            color: button.filled ? root.accent : button.active || button.hovered ? root.raised : "transparent"
            border.width: button.filled ? 0 : 1
            border.color: button.active || button.activeFocus ? root.accent : root.outline
            Behavior on color { ColorAnimation { duration: 120 } }
        }
    }

    // A single static handoff image covers the gap while the old engine exits.
    Dialogs.FolderDialog {
        id: localFolder
        parentWindow: panel.Window.window
        title: "Choose a wallpaper folder"
        currentFolder: "file://" + Quickshell.env("HOME")
        onAccepted: root.run(["folder-add", decodeURIComponent(selectedFolder.toString().replace(/^file:\/\//, ""))])
    }

    // It is never a second engine and is removed once the new background maps.
    PanelWindow {
        visible: !!root.state.switching && !!root.state.theme?.poster
        anchors { top: true; bottom: true; left: true; right: true }
        WlrLayershell.namespace: "wallpaperengine-transition"
        WlrLayershell.layer: WlrLayer.Background
        exclusionMode: ExclusionMode.Ignore
        color: "black"
        Image { anchors.fill: parent; source: root.state.theme?.poster ? "file://" + root.state.theme.poster : ""; fillMode: Image.PreserveAspectCrop }
    }

    PanelWindow {
        id: window
        visible: root.opened
        color: "transparent"
        anchors { top: true; bottom: true; left: true; right: true }
        WlrLayershell.namespace: "wallpaperengine-picker"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
        exclusionMode: ExclusionMode.Ignore

        Rectangle {
            anchors.fill: parent
            color: "#99070a10"
            MouseArea { anchors.fill: parent; onClicked: root.hidePicker() }
        }
        Rectangle {
            id: panel
            width: Math.min(1350, window.width - 90)
            height: Math.min(885, window.height - 96)
            anchors.centerIn: parent
            color: root.surface
            radius: 26
            border.color: root.outline
            border.width: 1
            MouseArea { anchors.fill: parent }
            Keys.onEscapePressed: root.hidePicker()
            Keys.onPressed: event => {
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { root.applySelected(); event.accepted = true; }
            }

            Popup {
                id: folderManager
                anchors.centerIn: parent
                width: Math.min(640, panel.width - 48)
                height: Math.min(380, panel.height - 48)
                modal: true
                padding: 20
                background: Rectangle { color: root.surface; radius: 20; border.color: root.outline }
                contentItem: ColumnLayout {
                    spacing: 12
                    Text { text: "Wallpaper folders"; font.pixelSize: 22; color: root.ink }
                    ListView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: root.state.folders || []
                        delegate: RowLayout {
                            required property var modelData
                            width: ListView.view.width
                            Text { Layout.fillWidth: true; text: parent.modelData.path; color: parent.modelData.available ? root.ink : root.col("error", "#ffb4ab"); elide: Text.ElideMiddle }
                            ActionButton { text: "Remove"; onClicked: root.run(["folder-remove", parent.modelData.path]) }
                        }
                        Text { anchors.centerIn: parent; visible: (root.state.folders || []).length === 0; text: "No local folders added"; color: root.muted }
                    }
                    RowLayout {
                        ActionButton { text: "Add folder"; onClicked: localFolder.open() }
                        Item { Layout.fillWidth: true }
                        ActionButton { text: "Done"; onClicked: folderManager.close() }
                    }
                }
            }
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 16
                RowLayout {
                    spacing: 12
                    ColumnLayout {
                        spacing: 2
                        Text { text: "Your wallpapers"; font.pixelSize: 27; font.weight: Font.DemiBold; color: root.ink }
                        Text { text: "Local & Workshop · " + (root.state.items?.length || 0) + " in your library"; font.pixelSize: 13; color: root.muted }
                    }
                    Item { Layout.fillWidth: true }
                    ActionButton { text: "Folders"; onClicked: folderManager.open() }
                    ActionButton { text: "Random"; onClicked: root.run(["random"]) }
                    ActionButton { text: "Next →"; onClicked: root.run(["next"]) }
                    ActionButton { text: "↻"; Accessible.name: "Refresh library"; onClicked: root.run(["refresh"]) }
                    ActionButton { text: "✕"; Accessible.name: "Close"; onClicked: root.hidePicker() }
                }
                TextField {
                    id: search
                    Layout.fillWidth: true
                    implicitHeight: 44
                    placeholderText: "Search your library…"
                    placeholderTextColor: root.muted
                    color: root.ink
                    selectionColor: root.accent
                    selectedTextColor: root.onAccent
                    font.pixelSize: 15
                    leftPadding: 16
                    onTextChanged: root.query = text
                    onAccepted: root.applySelected()
                    Keys.onEscapePressed: root.hidePicker()
                    Keys.onDownPressed: { grid.currentIndex = Math.max(0, root.filtered.findIndex(i => i.id === root.selectedId)); grid.forceActiveFocus(); }
                    background: Rectangle { radius: 13; color: root.base; border.width: 1; border.color: search.activeFocus ? root.accent : root.outline }
                }
                RowLayout {
                    spacing: 8
                    Repeater {
                        model: ["All", "Favorites", "Recent", "Videos", "Scenes"]
                        ActionButton { required property string modelData; text: modelData; active: root.category === modelData; onClicked: root.category = modelData }
                    }
                    Item { Layout.fillWidth: true }
                    Text { text: root.filtered.length + " results"; font.pixelSize: 12; color: root.muted }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 20
                    GridView {
                        id: grid
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        model: root.opened ? root.filtered : []
                        cellWidth: width / Math.max(1, Math.floor(width / 225))
                        cellHeight: cellWidth * .5625 + 79
                        boundsBehavior: Flickable.StopAtBounds
                        keyNavigationEnabled: false
                        Keys.onLeftPressed: root.navigate(-1)
                        Keys.onRightPressed: root.navigate(1)
                        Keys.onUpPressed: root.navigate(-Math.max(1, Math.floor(width / 225)))
                        Keys.onDownPressed: root.navigate(Math.max(1, Math.floor(width / 225)))
                        Keys.onReturnPressed: root.applySelected()
                        Keys.onEnterPressed: root.applySelected()
                        Keys.onEscapePressed: root.hidePicker()
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Item {
                            id: tile
                            required property var modelData
                            required property int index
                            width: grid.cellWidth
                            height: grid.cellHeight
                            Rectangle {
                                anchors.fill: parent
                                anchors.rightMargin: 12
                                anchors.bottomMargin: 12
                                radius: 17
                                color: root.selectedId === tile.modelData.id || hover.containsMouse ? root.raised : root.base
                                border.width: root.selectedId === tile.modelData.id ? 2 : 1
                                border.color: root.selectedId === tile.modelData.id ? root.accent : root.outline
                                Behavior on color { ColorAnimation { duration: 120 } }
                                Image {
                                    id: thumbnail
                                    anchors.top: parent.top
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.margins: 8
                                    height: width * .5625
                                    source: tile.modelData.preview ? "file://" + tile.modelData.preview : ""
                                    sourceSize.width: 480
                                    asynchronous: true
                                    fillMode: Image.PreserveAspectCrop
                                    clip: true
                                    Text { visible: thumbnail.status !== Image.Ready; anchors.centerIn: parent; text: "◇"; font.pixelSize: 36; color: root.muted }
                                }
                                Column {
                                    anchors.top: thumbnail.bottom
                                    anchors.topMargin: 10
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.margins: 12
                                    spacing: 5
                                    Text { width: parent.width; text: tile.modelData.title; color: root.ink; font.pixelSize: 13; font.weight: Font.Medium; elide: Text.ElideRight }
                                    Text { width: parent.width; text: tile.modelData.id === root.state.active ? "●  In use" : tile.modelData.missing ? "Incomplete download" : tile.modelData.compatibility?.state === "error" ? "Previous failure · see details" : root.typeLabel(tile.modelData); color: tile.modelData.id === root.state.active ? root.accent : root.muted; font.pixelSize: 11; elide: Text.ElideRight }
                                }
                                MouseArea {
                                    id: hover
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    onClicked: { grid.currentIndex = tile.index; root.choose(tile.modelData); }
                                    onDoubleClicked: { root.choose(tile.modelData); root.applySelected(); }
                                }
                                ActionButton {
                                    anchors.top: parent.top
                                    anchors.right: parent.right
                                    anchors.margins: 12
                                    implicitHeight: 30
                                    implicitWidth: 32
                                    text: tile.modelData.favorite ? "★" : "☆"
                                    active: tile.modelData.favorite
                                    Accessible.name: "Favorite " + tile.modelData.title
                                    onClicked: root.run(["favorite", tile.modelData.id])
                                }
                            }
                        }
                        Text { visible: root.filtered.length === 0; anchors.centerIn: parent; text: "No wallpapers match this selection"; color: root.muted; font.pixelSize: 15 }
                    }
                    Rectangle {
                        Layout.preferredWidth: 310
                        Layout.fillHeight: true
                        color: root.base
                        radius: 18
                        ScrollView {
                            anchors.fill: parent
                            anchors.margins: 16
                            clip: true
                            contentWidth: availableWidth
                            ColumnLayout {
                                width: 278
                                spacing: 14
                                Image {
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 156
                                    source: root.selected.preview ? "file://" + root.selected.preview : ""
                                    asynchronous: true
                                    fillMode: Image.PreserveAspectCrop
                                    sourceSize.width: 640
                                    clip: true
                                }
                                Text { Layout.fillWidth: true; text: root.selected.title || "Choose a wallpaper"; color: root.ink; font.pixelSize: 19; font.weight: Font.DemiBold; wrapMode: Text.Wrap }
                                Text { Layout.fillWidth: true; text: root.typeLabel(root.selected); color: root.muted; font.pixelSize: 12 }
                                ActionButton { Layout.fillWidth: true; text: root.state.active === root.selectedId ? "Reapply wallpaper" : "Apply wallpaper"; filled: true; enabled: !!root.selectedId && !root.selected.missing; onClicked: root.applySelected() }
                                Text { text: "Shell color preview"; font.pixelSize: 13; font.weight: Font.DemiBold; color: root.ink }
                                Row {
                                    spacing: 5
                                    Repeater {
                                        model: root.preview.scheme ? ["primary", "secondary", "tertiary", "surfaceContainerHigh"] : []
                                        Rectangle { required property string modelData; width: 64; height: 26; radius: 8; color: "#" + root.preview.scheme.colours[modelData] }
                                    }
                                }
                                Text { text: "Image colors · choose an accent"; font.pixelSize: 11; color: root.muted }
                                Row {
                                    spacing: 9
                                    Repeater {
                                        model: root.preview.swatches || []
                                        Rectangle {
                                            required property string modelData
                                            width: 38; height: 38; radius: 19
                                            color: "#" + modelData
                                            border.width: root.preferences.seed === modelData ? 3 : 1
                                            border.color: root.preferences.seed === modelData ? root.ink : root.outline
                                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.option("seed", parent.modelData) }
                                        }
                                    }
                                }
                                Text { Layout.fillWidth: true; text: root.preview.source ? "Source: " + root.preview.source : "Preparing color preview…"; font.pixelSize: 11; color: root.muted; wrapMode: Text.Wrap }
                                RowLayout {
                                    ActionButton { text: "Balanced"; active: (root.preferences.intensity || "equilibrada") === "equilibrada"; onClicked: root.option("intensity", "equilibrada") }
                                    ActionButton { text: "Vivid"; active: root.preferences.intensity === "viva"; onClicked: root.option("intensity", "viva") }
                                }
                                RowLayout {
                                    Repeater {
                                        model: [{label:"Dark", value:"dark"}, {label:"Light", value:"light"}, {label:"Auto", value:"auto"}]
                                        ActionButton { required property var modelData; text: modelData.label; active: (root.preferences.mode || "dark") === modelData.value; onClicked: root.option("mode", modelData.value) }
                                    }
                                }
                                ActionButton { Layout.fillWidth: true; text: root.preferences.frozen ? "●  Palette pinned to this wallpaper" : "Pin this palette"; active: !!root.preferences.frozen; onClicked: root.option("frozen", !root.preferences.frozen) }
                                RowLayout {
                                    ActionButton { text: "Automatic accent"; onClicked: root.option("seed", null) }
                                    ActionButton { text: "Recalculate"; enabled: !root.state.busy; onClicked: root.run(["recolor", root.selectedId]) }
                                }
                                ActionButton { Layout.fillWidth: true; text: "Restore previous colors"; onClicked: root.run(["undo-theme"]) }
                                Text { Layout.fillWidth: true; visible: !!root.selected.compatibility?.message; text: root.selected.compatibility?.message || ""; font.pixelSize: 11; wrapMode: Text.Wrap; color: root.muted }
                            }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    BusyIndicator { running: !!root.state.busy; visible: running; Layout.preferredWidth: 24; Layout.preferredHeight: 24 }
                    Text { Layout.fillWidth: true; text: root.actionError || root.state.error || root.state.message || "Choose a wallpaper to get started"; color: root.actionError || root.state.error ? root.col("error", "#ffb4ab") : root.muted; font.pixelSize: 12; elide: Text.ElideRight; maximumLineCount: 1 }
                    Text { text: "Enter aplica · Esc fecha"; color: root.muted; font.pixelSize: 11 }
                }
            }
        }
    }
}
