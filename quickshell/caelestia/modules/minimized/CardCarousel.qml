pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import Quickshell
import Quickshell.Widgets
import Caelestia.Config
import qs.components
import qs.components.controls
import qs.services

Item {
    id: root
    required property var items
    property bool wallpapers: false
    property bool applications: false
    readonly property bool favoritesEnabled: wallpapers || applications
    property string selectedUid: ""
    property double blockedUntil: 0
    property real wheelRemainder: 0
    property double lastWheel: 0
    property var retiring: ({})
    property bool complete: false
    property bool resetting: false
    readonly property real baseCoverWidth: applications ? Math.min(148,width * 0.27) : Math.min(264,width * 0.32)
    readonly property real coverWidth: applications ? baseCoverWidth : Math.min(420,width * 0.50)
    readonly property real coverHeight: applications ? Math.min(112,height - 30) : Math.min(244,height - 58)
    readonly property real firstSideOffset: baseCoverWidth * 0.66
    readonly property real wallpaperRadius: Math.min(width * 0.43,firstSideOffset / Math.sin(Math.PI / 5))
    readonly property real windowSideFactor: items.length % 4 === 0 ? 1 : Math.cos(Math.PI / (items.length % 2 === 0 ? Math.max(1,items.length) : Math.max(1,items.length) * 2))
    readonly property int animatedCount: cards.count
    readonly property int currentIndex: items.findIndex(e => key(e) === selectedUid)
    readonly property var currentEntry: currentIndex >= 0 ? items[currentIndex] : null
    readonly property int position: currentIndex + 1
    signal activated(var entry, var origin)
    signal secondaryTriggered(var entry)

    function key(entry) {
        if (!entry) return "";
        return favoritesEnabled ? String(entry.id) : String(entry.address) + ":" + String(entry.pid);
    }
    function rowFor(uid) {
        for (let i = 0; i < cards.count; ++i) if (cards.get(i).uid === uid) return i;
        return -1;
    }
    function blockActivation() { blockedUntil = Date.now() + 500; }
    function originFor(entry) {
        if (!entry) return null;
        const row = rowFor(key(entry));
        const card = row >= 0 ? scene.itemAt(row) : null;
        if (!card || !card.visible) return null;
        const rect = card.mapToItem(null,Qt.rect(0,0,card.width,card.height));
        return {x:rect.x,y:rect.y,width:rect.width,height:rect.height};
    }
    function activate(entry) {
        if (Date.now() < blockedUntil || reflow.running || retire.running || !items.some(e => key(e) === key(entry))) return;
        activated(entry,originFor(entry));
    }
    function requestSecondary(entry) {
        if (!entry || !items.some(e => key(e) === key(entry))) return;
        blockActivation();
        secondaryTriggered(entry);
    }
    function sync() {
        const oldOrder = [];
        for (let i = 0; i < cards.count; ++i) {
            const item = cards.get(i);
            if (!item.leaving) oldOrder.push({uid:item.uid,slot:item.slot});
        }
        oldOrder.sort((a,b) => a.slot - b.slot);
        if (!items.some(e => key(e) === selectedUid)) {
            const oldIndex = oldOrder.findIndex(item => item.uid === selectedUid);
            let next = "";
            for (let n = 1; n <= oldOrder.length; ++n) {
                const candidate = oldOrder[(oldIndex + n) % oldOrder.length];
                if (items.some(e => key(e) === candidate.uid)) { next = candidate.uid; break; }
            }
            selectedUid = next || key(items[0]);
        }
        let removed = false;
        for (let i = 0; i < cards.count; ++i) {
            const item = cards.get(i);
            if (!items.some(e => key(e) === item.uid) && !item.leaving) {
                // Freeze the outgoing card at its actual displayed transform.
                const delegate = scene.itemAt(i);
                if (delegate) cards.setProperty(i,"frozen",Object.assign({},delegate.presentationPoint));
                cards.setProperty(i,"leaving",true);
                retiring[item.uid] = Date.now() + Tokens.anim.durations.expressiveFastSpatial + 32;
                removed = true;
            }
        }
        if (removed) { blockActivation(); reflow.restart(); retire.start(); }
        for (let i = 0; i < items.length; ++i) {
            const entry = items[i];
            const row = rowFor(key(entry));
            if (row < 0) cards.append({uid:key(entry),entry:entry,slot:i,leaving:false,frozen:{x:0,y:0,scale:1,z:100,opacity:1,rotation:0}});
            else {
                if (JSON.stringify(cards.get(row).entry) !== JSON.stringify(entry)) cards.setProperty(row,"entry",entry);
                cards.setProperty(row,"slot",i);
                cards.setProperty(row,"leaving",false);
                delete retiring[key(entry)];
            }
        }
    }
    function resetOrder() {
        resetting = true;
        sync();
        selectedUid = key(items[0]);
        orbit.select(currentIndex);
        Qt.callLater(() => resetting = false);
    }
    function selectIndex(index, direction = 0) {
        if (index < 0 || index >= items.length) return;
        orbit.select(index,direction);
        selectedUid = key(items[index]);
    }
    function cycle(direction) {
        if (items.length < 2) return;
        selectIndex((Math.max(0,currentIndex) + direction + items.length) % items.length,direction);
    }
    function wheel(event) {
        const delta = event.angleDelta.y || event.angleDelta.x || event.pixelDelta.y * 3;
        const now = Date.now();
        if (now - lastWheel > 250) wheelRemainder = 0;
        lastWheel = now;
        wheelRemainder += delta;
        if (Math.abs(wheelRemainder) >= 90) { cycle(wheelRemainder < 0 ? 1 : -1); wheelRemainder = 0; }
        event.accepted = true;
    }
    onItemsChanged: if (complete) sync()
    Component.onCompleted: { complete = true; sync(); }
    ListModel { id: cards }
    Timer { id: reflow; interval: Tokens.anim.durations.expressiveFastSpatial + 50 }
    Timer {
        id: retire
        interval: 16
        repeat: true
        onTriggered: {
            for (const [uid,deadline] of Object.entries(root.retiring)) {
                if (Date.now() < deadline) continue;
                const row = root.rowFor(uid);
                // Layout uses live membership and stable slots, never this visual row index.
                if (row >= 0 && cards.get(row).leaving) cards.remove(row);
                delete root.retiring[uid];
            }
            if (!Object.keys(root.retiring).length) stop();
        }
    }
    WindowFlowMotion {
        id: orbit
        count: root.items.length
        currentIndex: root.currentIndex
        animate: root.visible && !root.resetting
        transitionDuration: reflow.running ? Tokens.anim.durations.expressiveFastSpatial : Tokens.anim.durations.expressiveDefaultSpatial
        // Small window collections fill the same horizontal span as the wallpaper ring.
        radius: count <= 2 ? root.firstSideOffset : root.favoritesEnabled || count > 10 ?
            Math.min(root.width * 0.43,root.firstSideOffset / Math.max(0.45,Math.abs(Math.sin(sideAngle)))) :
            Math.min(root.width * 0.43,root.wallpaperRadius / Math.max(0.45,root.windowSideFactor))
    }
    Repeater {
        id: scene
        model: cards
        delegate: Item {
            id: card
            required property var entry
            required property string uid
            required property int slot
            required property bool leaving
            required property var frozen
            readonly property bool selected: uid === root.selectedUid
            property real favoriteHighlight: root.favoritesEnabled && selected && !leaving && entry.favorite ? 1 : 0
            property bool ready: false
            property real bearing: slot * orbit.step
            property real dismissal: leaving ? 1 : 0
            readonly property real angle: bearing - orbit.phase
            readonly property real ringDistance: orbit.step ? Math.abs(Math.atan2(Math.sin(angle),Math.cos(angle))) / orbit.step : 0
            readonly property bool rendered: leaving || root.items.length <= 10 || ringDistance < 5.1
            readonly property var presentationPoint: leaving ? frozen : orbit.project(angle)
            readonly property real edgeOpacity: root.items.length <= 10 || leaving ? 1 : Math.max(0,Math.min(1,5 - ringDistance))
            width: root.coverWidth
            height: root.coverHeight
            x: root.width / 2 - width / 2 + presentationPoint.x
            y: 10 + presentationPoint.y - 16 * dismissal
            scale: presentationPoint.scale * (1 - dismissal * 0.08)
            z: presentationPoint.z + (leaving ? 1 : 0)
            opacity: presentationPoint.opacity * edgeOpacity * Math.max(0,1 - dismissal)
            visible: rendered
            Component.onCompleted: ready = true
            Behavior on favoriteHighlight { Anim { type: Anim.DefaultEffects } }
            Behavior on bearing {
                enabled: card.ready && root.visible && !root.resetting
                SmoothedAnimation { duration: orbit.transitionDuration; velocity: -1; maximumEasingTime: 120; reversingMode: SmoothedAnimation.Eased }
            }
            Behavior on dismissal {
                NumberAnimation { duration: Tokens.anim.durations.expressiveFastSpatial; easing.type: Easing.OutCubic }
            }
            transform: Rotation {
                origin.x: card.width / 2; origin.y: card.height / 2
                axis { x:0; y:1; z:0 }
                angle: card.presentationPoint.rotation
            }
            Loader {
                anchors.fill: parent
                active: card.rendered && (!root.applications || root.visible)
                sourceComponent: Item {
                    RectangularShadow {
                        anchors.fill: coverFace
                        radius: coverFace.radius
                        blur: 12
                        spread: 1
                        color: Qt.alpha(Colours.palette.m3primary,0.28)
                        opacity: card.selected ? card.favoriteHighlight : 0
                        visible: opacity > 0
                    }
                    ClippingRectangle {
                        id: coverFace
                        anchors.fill: parent
                        radius: Math.min(8,Tokens.rounding.small)
                        color: root.applications ? Qt.alpha(Colours.palette.m3surfaceContainerHigh,card.selected ? 0.30 : 0.16) : Colours.palette.m3surfaceContainerHigh
                        Image {
                            id: poster
                            anchors.fill: parent
                            visible: !root.applications
                            readonly property string path: (root.wallpapers ? card.entry.displayPreview || card.entry.preview : card.entry.thumbnail) ?? ""
                            source: !root.applications && card.rendered && path ? "file://" + path : ""
                            sourceSize: root.wallpapers ? Qt.size(1280,1280) : Qt.size(640,480)
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            mipmap: true
                        }
                        IconImage {
                            id: applicationIcon
                            anchors.centerIn: parent
                            visible: root.applications && status === Image.Ready
                            implicitSize: Math.min(88,card.height - 32)
                            source: root.applications && card.entry.icon ? Quickshell.iconPath(card.entry.icon, true) : ""
                            asynchronous: true
                            mipmap: true
                        }
                        MaterialIcon {
                            anchors.centerIn: parent
                            visible: root.applications ? applicationIcon.status !== Image.Ready : !(root.wallpapers ? card.entry.preview : card.entry.thumbnail)
                            text: root.applications ? "apps" : root.wallpapers ? "wallpaper" : "desktop_windows"
                            fontStyle: Tokens.font.icon.size(48).build()
                            color: Colours.palette.m3primary
                        }
                        StyledRect {
                            anchors.fill: parent
                            radius: Math.min(8,Tokens.rounding.small)
                            border.width: card.selected && card.favoriteHighlight > 0 ? 2 : 1
                            border.color: card.selected && card.favoriteHighlight > 0 ? Qt.alpha(Colours.palette.m3primary,0.55 + 0.45 * card.favoriteHighlight) : Qt.alpha(Colours.palette.m3outlineVariant,card.selected ? 0.55 : 0.30)
                        }
                    }
                    ShaderEffectSource {
                        id: coverTexture
                        sourceItem: coverFace
                        hideSource: false
                        live: root.visible && card.rendered
                        visible: false
                        textureSize: Qt.size(Math.ceil(card.width),Math.ceil(card.height))
                    }
                    Item {
                        anchors.top: coverFace.bottom
                        anchors.topMargin: 3
                        width: parent.width
                        height: 54
                        clip: true
                        enabled: false
                        ShaderEffect {
                            width: card.width
                            height: card.height
                            property variant source: coverTexture
                            fragmentShader: Qt.resolvedUrl("reflection.frag.qsb")
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        property var pressedEntry: null
                        acceptedButtons: root.favoritesEnabled ? Qt.LeftButton | Qt.RightButton : Qt.LeftButton
                        hoverEnabled: true
                        enabled: !card.leaving
                        cursorShape: Qt.PointingHandCursor
                        onPressed: mouse => {
                            pressedEntry = Object.assign({},card.entry);
                            if (mouse.button === Qt.RightButton) root.blockActivation();
                        }
                        onCanceled: pressedEntry = null
                        onClicked: mouse => {
                            if (!pressedEntry || root.key(pressedEntry) !== card.uid) return;
                            if (mouse.button === Qt.RightButton && root.favoritesEnabled) {
                                root.requestSecondary(pressedEntry);
                                pressedEntry = null;
                                return;
                            }
                            if (Date.now() < root.blockedUntil || reflow.running || retire.running) return;
                            if (card.selected) root.activate(pressedEntry);
                            else root.selectIndex(root.items.findIndex(e => root.key(e) === card.uid));
                            pressedEntry = null;
                        }
                        onWheel: event => root.wheel(event)
                    }
                }
            }
        }
    }
    // The action stays still while previews rotate underneath it. Its entire hit area
    // consumes input even while the button is disabled or its original card disappears.
    MouseArea {
        id: actionZone
        property var pressedEntry: null
        width: actionButton.implicitWidth + 16
        height: actionButton.implicitHeight + 16
        x: root.width / 2 + root.coverWidth / 2 - 8 - actionButton.implicitWidth - 8
        y: 10
        z: 500
        visible: !root.favoritesEnabled && root.animatedCount > 0
        acceptedButtons: Qt.LeftButton
        preventStealing: true
        onClicked: mouse => mouse.accepted = true
        onWheel: event => root.wheel(event)
        IconButton {
            id: actionButton
            anchors.centerIn: parent
            disabled: !root.currentEntry
            icon: "close"
            label.fill: 1
            type: IconButton.Tonal
            font: Tokens.font.icon.small
            padding: 6
            ToolTip.visible: hovered
            ToolTip.text: "Close window"
            ToolTip.delay: 450
            Accessible.name: "Close window: " + (root.currentEntry?.title ?? "")
            onPressedChanged: if (pressed) {
                actionZone.pressedEntry = root.currentEntry ? Object.assign({},root.currentEntry) : null;
                root.blockActivation();
            }
            onClicked: {
                root.requestSecondary(actionZone.pressedEntry);
                actionZone.pressedEntry = null;
            }
        }
    }
    IconButton {
        anchors.left: parent.left; anchors.leftMargin: 20; anchors.verticalCenter: parent.verticalCenter
        z: 300; icon: "chevron_left"; type: IconButton.Text; disabled: root.items.length < 2
        onClicked: root.cycle(-1)
    }
    IconButton {
        anchors.right: parent.right; anchors.rightMargin: 20; anchors.verticalCenter: parent.verticalCenter
        z: 300; icon: "chevron_right"; type: IconButton.Text; disabled: root.items.length < 2
        onClicked: root.cycle(1)
    }
}
