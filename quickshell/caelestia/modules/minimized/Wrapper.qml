pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import Quickshell
import Caelestia.Config
import qs.components
import qs.components.controls
import qs.services

Item {
    id: root
    required property ScreenState screenState
    required property ShellScreen screen
    readonly property bool shouldBeActive: screenState.minimized
    readonly property int activeTab: screenState.minimizedTab
    readonly property var activeCarousel: activeTab === 1 ? windows : wallpapers
    readonly property var currentEntry: activeTab === 0 ? null : activeCarousel.currentEntry
    readonly property int count: activeTab === 0 ? ApplicationLibrary.favoriteEntries.length : activeTab === 1 ? Minimized.count : WallpaperLibrary.entries.length
    property bool menuOpen: false
    property real offsetScale: shouldBeActive ? 0 : 1

    readonly property real compactWidth: Math.max(miniHub.implicitWidth,options.implicitWidth + 24)
    readonly property real compactHeight: Math.max(36,miniHub.implicitHeight) + 32
    readonly property real contentCenterFromBottom: 32 + Math.max(36,miniHub.implicitHeight) / 2

    readonly property real windowPanelWidth: Math.max(384,Math.min(440,compactWidth))
    readonly property real windowPanelHeight: 340
    readonly property real emptyWindowPanelHeight: 244
    readonly property real wallpaperPanelWidth: Math.min(854,screen.width - 100)
    readonly property real wallpaperPanelHeight: Math.min(440,screen.height - 160)
    implicitWidth: Math.min(activeTab === 0 ? compactWidth : activeTab === 1 ? windowPanelWidth : wallpaperPanelWidth,screen.width - 100)
    implicitHeight: Math.min(activeTab === 0 ? compactHeight + (statusNotice.visible ? 24 : 0) : activeTab === 1 ? (windows.animatedCount > 0 ? windowPanelHeight : emptyWindowPanelHeight) : wallpaperPanelHeight,screen.height - 160)
    anchors.bottomMargin: (-implicitHeight - 5) * offsetScale
    visible: offsetScale < 1
    opacity: 1 - offsetScale
    focus: shouldBeActive
    Behavior on offsetScale { Anim {} }
    Behavior on implicitWidth { Anim {} }
    Behavior on implicitHeight {
        onTargetValueChanged: panelHeightMotion.type = root.activeTab === 1 && windows.animatedCount === 0 ? Anim.Emphasized : Anim.DefaultSpatial
        Anim { id: panelHeightMotion }
    }

    function setTab(index) {
        screenState.minimizedTab = Math.max(0,Math.min(2,index));
        menuOpen = activeTab !== 0;
        if (activeTab === 2) WallpaperLibrary.open();
        else if (activeTab === 0) ApplicationLibrary.open();
        Qt.callLater(() => {
            if (root.activeTab !== 0) root.activeCarousel.resetOrder();
            root.forceActiveFocus();
        });
    }
    function toggleMenu() {
        if (activeTab !== 0) setTab(0);
        else menuOpen = !menuOpen;
    }
    function openNativeLauncher() {
        screenState.launcher = true;
        screenState.minimized = false;
    }
    function cycle(direction) { if (activeTab !== 0) activeCarousel.cycle(direction); }
    function wheel(event) {
        if (activeTab !== 0) activeCarousel.wheel(event);
        else event.accepted = true;
    }
    function activate(entry, origin) {
        if (!entry) return;
        if (activeTab === 1) {
            const source = origin ? {x:origin.x + screen.x,y:origin.y + screen.y,width:origin.width,height:origin.height} : null;
            Minimized.restore(entry.address,entry.pid,source,true);
        } else if (activeTab === 2) WallpaperLibrary.apply(entry.id);
    }
    function restoreCurrent() { if (currentEntry) activeCarousel.activate(currentEntry); }
    function closeCurrent() {
        if (activeTab === 1 && currentEntry) windows.requestSecondary(currentEntry);
    }
    function bubbleOrigin(centerX) {
        const bottom = mapToItem(null,width / 2,height);
        const base = screen.y + bottom.y - (implicitHeight + 5) * offsetScale;
        const center = Number.isFinite(centerX) ? centerX : screen.x + bottom.x;
        return {x:Math.max(screen.x,Math.min(screen.x+screen.width-48,center-24)),y:base+4,width:48,height:48};
    }
    function minimizeTarget() { return bubbleOrigin(); }
    function info() {
        return JSON.stringify({open:shouldBeActive,tab:activeTab,width:width,height:height,count:count,
            selected:activeTab === 1 ? currentEntry?.address : currentEntry?.id,
            rendered:activeTab === 0 ? count : activeCarousel.animatedCount,menuOpen:menuOpen,
            emptyMotion:{opacity:emptyState.opacity,reveal:emptyState.reveal,type:panelHeightMotion.type,duration:panelHeightMotion.duration},
            wallpaperLayout:{width:wallpapers.width,height:wallpapers.height,coverWidth:wallpapers.coverWidth,coverHeight:wallpapers.coverHeight},
            appsView:"mini",launcher:screenState.launcher,icons:miniHub.entries.map(entry => entry.id),
            handle:handle.mapToItem(null,handle.width/2,handle.height/2),
            mini:miniHub.mapToItem(null,0,0),compactWidth:compactWidth,compactHeight:compactHeight,
            contentCenter:mapToItem(null,width/2,height-contentCenterFromBottom),
            menuCenter:options.mapToItem(null,options.width/2,options.height/2),landing:minimizeTarget(),stack:windows.diagnostics(),origin:activeTab === 1 ? windows.originFor(currentEntry) : null});
    }
    Keys.onDeletePressed: closeCurrent()
    Keys.onEscapePressed: {
        if (activeTab !== 0) setTab(0);
        else if (menuOpen) menuOpen = false;
        else screenState.minimized = false;
    }
    Keys.onLeftPressed: cycle(-1)
    Keys.onRightPressed: cycle(1)
    Keys.onReturnPressed: restoreCurrent()
    Keys.onEnterPressed: restoreCurrent()
    Keys.onTabPressed: {
        if (activeTab === 0) toggleMenu();
        else setTab(activeTab === 1 ? 2 : 1);
    }
    Keys.onPressed: event => {
        if (activeTab === 2 && event.key === Qt.Key_F && currentEntry) {
            wallpapers.requestSecondary(currentEntry);
            event.accepted = true;
        }
    }
    onShouldBeActiveChanged: if (shouldBeActive) setTab(0)

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        onWheel: event => root.wheel(event)
    }
    // Keep both pages on one track, like the dashboard's animated contentX.
    // Clipping hides the outgoing page while Anim supplies the native bounce.
    Item {
        id: compactViewport
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 32
        height: Math.max(36,miniHub.implicitHeight)
        clip: true
        z: 300
        readonly property real pageWidth: width + Tokens.padding.large
        property real page: root.menuOpen ? 1 : 0
        Behavior on page {
            enabled: root.shouldBeActive && root.offsetScale === 0
            Anim {}
        }

        MiniApplications {
            id: miniHub
            screen: root.screen
            maximumWidth: Math.min(600,root.screen.width - 100)
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            transform: Translate { x: -compactViewport.page * compactViewport.pageWidth }
            enabled: root.activeTab === 0 && !root.menuOpen && root.shouldBeActive
            onLaunched: root.screenState.minimized = false
        }

        Row {
            id: options
            anchors.centerIn: parent
            spacing: 10
            transform: Translate { x: (1 - compactViewport.page) * compactViewport.pageWidth }
            enabled: root.menuOpen && root.shouldBeActive
            IconTextButton {
                implicitHeight: 36
                icon: "apps"
                text: "Apps"
                type: IconTextButton.Text
                inactiveColour: "transparent"
                onClicked: root.openNativeLauncher()
            }
            IconTextButton {
                implicitHeight: 36
                icon: "desktop_windows"
                text: "Windows"
                type: IconTextButton.Text
                isToggle: true
                checked: root.activeTab === 1
                inactiveColour: "transparent"
                activeColour: Qt.alpha(Colours.palette.m3primary,0.14)
                onClicked: { internalChecked = true; root.setTab(1); }
            }
            IconTextButton {
                implicitHeight: 36
                icon: "wallpaper"
                text: "Wallpapers"
                type: IconTextButton.Text
                isToggle: true
                checked: root.activeTab === 2
                inactiveColour: "transparent"
                activeColour: Qt.alpha(Colours.palette.m3primary,0.14)
                onClicked: { internalChecked = true; root.setTab(2); }
            }
        }
    }
    MouseArea {
        id: handle
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 6
        anchors.horizontalCenter: parent.horizontalCenter
        width: 96
        height: 20
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        z: 400
        Accessible.role: Accessible.Button
        Accessible.name: root.menuOpen ? "Back to favorites" : "Open central options"
        onClicked: root.toggleMenu()
        Rectangle {
            anchors.centerIn: parent
            width: 48
            height: 4
            radius: 2
            color: Qt.alpha(Colours.palette.m3onSurface,handle.pressed ? 0.95 : handle.containsMouse ? 0.80 : 0.42)
            Behavior on color { CAnim {} }
        }
    }

    WindowStack {
        id: windows
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.topMargin: statusNotice.visible ? 36 : 12
        height: root.height - 132
        clip: true
        items: Minimized.entries
        enabled: root.activeTab === 1
        opacity: enabled ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { Anim { type: Anim.DefaultEffects } }
        onActivated: (entry, origin) => root.activate(entry,origin)
        onSecondaryTriggered: entry => Minimized.close(entry.address,entry.pid)
    }
    Item {
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.topMargin: statusNotice.visible ? 36 : 12
        height: Math.max(0,root.height - 140)
        clip: true

        // Reveal a final-size carousel through the growing panel, without
        // resizing its covers or orbit during the hub's opening animation.
        CardCarousel {
            id: wallpapers
            anchors.horizontalCenter: parent.horizontalCenter
            width: root.wallpaperPanelWidth
            height: Math.max(0,root.wallpaperPanelHeight - 140)
            clip: true
            wallpapers: true
            items: WallpaperLibrary.entries
            enabled: root.activeTab === 2
            opacity: enabled ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { Anim { type: Anim.DefaultEffects } }
            onActivated: entry => root.activate(entry)
            onSecondaryTriggered: entry => WallpaperLibrary.favorite(entry.id)
        }
    }
    Column {
        id: emptyState
        readonly property bool shown: root.activeTab === 1 && windows.animatedCount === 0 && compactViewport.y + options.y >= height + 8
        property real reveal: shown ? 1 : 0
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.activeTab === 1 ? (compactViewport.y + options.y - height) / 2 : (parent.height - height) / 2
        width: parent.width - 48
        spacing: 12
        // Let the panel make room before revealing the empty state above its menu.
        opacity: root.activeTab === 1 ? reveal : 1
        visible: root.activeTab === 1 ? opacity > 0 : root.activeTab === 2 && wallpapers.animatedCount === 0
        scale: root.activeTab === 1 ? 0.985 + 0.015 * reveal : 1
        transform: Translate { y: root.activeTab === 1 ? 6 * (1 - emptyState.reveal) : 0 }
        Behavior on reveal {
            Anim { type: Anim.SlowEffects }
        }
        MaterialIcon {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.activeTab === 1 ? "desktop_windows" : "wallpaper"
            fontStyle: Tokens.font.icon.size(44).build()
            color: Colours.palette.m3primary
        }
        StyledText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.activeTab === 1 ? "All in view" : "Library is empty"
            font: Tokens.font.title.large
        }
        IconTextButton {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.activeTab === 2
            icon: "create_new_folder"
            text: "Add a wallpaper folder"
            onClicked: WallpaperLibrary.manageFolders()
        }
    }
    Column {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 76
        anchors.horizontalCenter: parent.horizontalCenter
        width: parent.width - 80
        spacing: 7
        visible: root.activeTab !== 0 && root.count > 0
        StyledText {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: root.currentEntry?.title ?? ""
            font: Tokens.font.title.medium
        }
        StyledText {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.activeTab === 1 ? `${Math.max(1,windows.position)} / ${root.count}  ·  Workspace ${root.currentEntry?.workspace?.replace("special:","") ?? ""}` :
                `${Math.max(1,wallpapers.position)} / ${root.count}  ·  ${root.currentEntry?.missing ? "Incomplete download" : root.currentEntry?.id === WallpaperLibrary.activeId ? "In use" : root.currentEntry?.type === "video" ? "Video" : root.currentEntry?.type === "scene" ? "Animated scene" : "Wallpaper"}`
            color: Colours.palette.m3primary
        }
    }
    IconButton {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 8
        z: 310
        visible: root.activeTab === 2
        icon: "folder_open"
        type: IconButton.Text
        Accessible.name: "Wallpaper folders"
        onClicked: WallpaperLibrary.manageFolders()
    }
    StyledText {
        id: statusNotice
        anchors.top: parent.top
        anchors.topMargin: 8
        anchors.horizontalCenter: parent.horizontalCenter
        width: parent.width - 112
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        visible: text.length > 0
        z: 300
        text: root.activeTab === 0 ? ApplicationLibrary.error : root.activeTab === 2 ?
            WallpaperLibrary.error || WallpaperLibrary.state.error ||
                (WallpaperLibrary.state.busy ? WallpaperLibrary.state.message || "Applying wallpaper…" : "") : ""
        color: (root.activeTab === 2 && (WallpaperLibrary.error || WallpaperLibrary.state.error)) || (root.activeTab === 0 && ApplicationLibrary.error) ? Colours.palette.m3error : Colours.palette.m3onSurfaceVariant
    }
}
