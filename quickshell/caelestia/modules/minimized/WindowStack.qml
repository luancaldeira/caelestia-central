pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Widgets
import Caelestia.Config
import qs.components
import qs.components.controls
import qs.services

Item {
    id: root
    required property var items
    property string selectedUid: ""
    property var previousOrder: []
    property var retiring: ({})
    property bool complete: false
    property bool reindexing: false
    property real phase: 0
    property real reveal: 1
    property real wheelRemainder: 0
    property double lastWheel: 0
    property double lastStepAt: 0
    property int lastStepDirection: 0
    property double blockedUntil: 0
    readonly property int currentIndex: items.findIndex(e => key(e) === selectedUid)
    readonly property var currentEntry: currentIndex >= 0 ? items[currentIndex] : null
    readonly property int position: currentIndex + 1
    readonly property int animatedCount: cards.count
    readonly property real sideInset: 56
    readonly property real coverWidth: Math.max(80,width - sideInset * 2)
    readonly property real coverHeight: Math.max(48,Math.min(coverWidth * 9 / 16,height - 16))
    readonly property real cardStep: coverWidth + 14
    readonly property bool settled: currentIndex >= 0 && Math.abs(phase - currentIndex) < 0.035
    signal activated(var entry, var origin)
    signal secondaryTriggered(var entry)

    function key(entry) { return entry ? String(entry.address) + ":" + String(entry.pid) : ""; }
    function rowFor(uid) {
        for (let i = 0; i < cards.count; ++i) if (cards.get(i).uid === uid) return i;
        return -1;
    }
    function originFor(entry) {
        const row = rowFor(key(entry));
        const card = row >= 0 ? scene.itemAt(row) : null;
        if (!card || !card.visible) return null;
        const rect = card.mapToItem(null,Qt.rect(0,0,card.width,card.height));
        return {x:rect.x,y:rect.y,width:rect.width,height:rect.height};
    }
    function activate(entry) {
        if (!settled || Date.now() < blockedUntil || key(entry) !== selectedUid || !items.some(e => key(e) === key(entry))) return;
        activated(Object.assign({},entry),originFor(entry));
    }
    function requestSecondary(entry) {
        if (!entry || !items.some(e => key(e) === key(entry))) return;
        blockedUntil = Date.now() + 260;
        secondaryTriggered(Object.assign({},entry));
    }
    function sync() {
        const order = items.map(e => key(e));
        const changed = JSON.stringify(order) !== JSON.stringify(previousOrder);
        const oldIndex = previousOrder.indexOf(selectedUid);
        const selectionRemoved = selectedUid && !order.includes(selectedUid);
        // Outgoing cards retain their current presentation, independent of the
        // live list. A removal can never turn their release into a neighbor click.
        for (let i = 0; i < cards.count; ++i) {
            const item = cards.get(i);
            if (!order.includes(item.uid) && !item.leaving) {
                const delegate = scene.itemAt(i);
                if (delegate) cards.setProperty(i,"frozen",delegate.snapshot());
                cards.setProperty(i,"leaving",true);
                retiring[item.uid] = Date.now() + 270;
                retire.start();
            }
        }
        if (!order.includes(selectedUid))
            selectedUid = order[Math.max(0,Math.min(oldIndex,order.length - 1))] ?? "";
        if (changed) reindexing = true;
        for (let i = 0; i < items.length; ++i) {
            const row = rowFor(order[i]);
            if (row < 0) cards.append({uid:order[i],entry:items[i],slot:i,leaving:false,frozen:{x:0,y:0,scale:1,opacity:1,rotation:0}});
            else {
                cards.setProperty(row,"entry",items[i]);
                cards.setProperty(row,"slot",i);
            }
        }
        if (changed) {
            phase = Math.max(0,currentIndex);
            previousOrder = order;
            if (selectionRemoved && items.length) { reveal = 0; incoming.restart(); }
            Qt.callLater(() => root.reindexing = false);
        }
    }
    function resetOrder() {
        reindexing = true;
        sync();
        // Start in the middle of a bounded list, with context on both sides.
        selectedUid = key(items[Math.floor(Math.max(0,items.length - 1) / 2)]);
        phase = Math.max(0,currentIndex);
        reveal = 1;
        wheelRemainder = 0;
        lastStepAt = 0;
        lastStepDirection = 0;
        Qt.callLater(() => root.reindexing = false);
    }
    function cycle(direction) {
        const index = Math.max(0,Math.min(items.length - 1,currentIndex + direction));
        if (!items.length || index === currentIndex) return;
        incoming.stop(); reveal = 1;
        selectedUid = key(items[index]);
        phase = index;
    }
    function wheel(event) {
        const pixels = event.pixelDelta.y || event.pixelDelta.x;
        const delta = event.angleDelta.y || event.angleDelta.x || pixels * 1.5;
        const now = Date.now();
        if (now - lastWheel > 320) wheelRemainder = 0;
        lastWheel = now;
        wheelRemainder += delta;
        if (Math.abs(wheelRemainder) >= 120) {
            const direction = wheelRemainder < 0 ? 1 : -1;
            // Do not queue a burst of wheel events through a small collection.
            // Reversing remains immediate, even while a card is still moving.
            if (direction !== lastStepDirection || now - lastStepAt >= 260) {
                cycle(direction);
                lastStepAt = now;
                lastStepDirection = direction;
            }
            wheelRemainder = 0;
        }
        event.accepted = true;
    }
    function diagnostics() {
        const rendered = [];
        for (let i = 0; i < cards.count; ++i) {
            const c = scene.itemAt(i);
            if (c && c.opacity > 0.01) rendered.push({uid:c.uid,x:c.x,y:c.y,width:c.width,height:c.height,offset:c.offset,selected:c.selected,opacity:c.opacity,leaving:c.leaving});
        }
        return {phase:phase,index:currentIndex,settled:settled,rendered:rendered};
    }
    onItemsChanged: if (complete) sync()
    Component.onCompleted: { complete = true; sync(); }
    Behavior on phase {
        enabled: root.complete && root.visible && !root.reindexing
        SmoothedAnimation { duration: 400; velocity: -1; maximumEasingTime: 150; reversingMode: SmoothedAnimation.Eased }
    }
    NumberAnimation { id: incoming; target: root; property: "reveal"; to: 1; duration: 230; easing.type: Easing.OutCubic }
    ListModel { id: cards }
    Timer {
        id: retire
        interval: 16; repeat: true
        onTriggered: {
            for (const [uid,deadline] of Object.entries(root.retiring)) {
                if (Date.now() < deadline) continue;
                const row = root.rowFor(uid);
                if (row >= 0 && cards.get(row).leaving) cards.remove(row);
                delete root.retiring[uid];
            }
            if (!Object.keys(root.retiring).length) stop();
        }
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
            readonly property real offset: slot - root.phase
            readonly property real distance: Math.abs(offset)
            readonly property bool selected: uid === root.selectedUid
            property real dismissal: leaving ? 1 : 0
            width: root.coverWidth; height: root.coverHeight
            x: leaving ? frozen.x : (root.width - width) / 2 + offset * root.cardStep
            y: leaving ? frozen.y - dismissal * 6 : 8
            scale: leaving ? frozen.scale * (1 - dismissal * 0.025) : (1 - Math.min(1,distance) * 0.035) * (selected ? 0.985 + 0.015 * root.reveal : 1)
            rotation: leaving ? frozen.rotation : 0
            opacity: leaving ? frozen.opacity * (1 - dismissal) : Math.max(0,Math.min(1,2 - distance)) * (1 - Math.min(1,distance) * 0.28) * (selected ? root.reveal : 1)
            visible: opacity > 0.001
            z: leaving ? 200 : 100 - distance
            function snapshot() { return {x:x,y:y,scale:scale,opacity:opacity,rotation:rotation}; }
            Behavior on dismissal { NumberAnimation { duration: 230; easing.type: Easing.OutCubic } }
            ClippingRectangle {
                anchors.fill: parent
                radius: 8
                color: Colours.palette.m3surfaceContainerHigh
                Image {
                    anchors.fill: parent
                    source: card.entry.thumbnail ? "file://" + card.entry.thumbnail : ""
                    sourceSize: Qt.size(640,480)
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    mipmap: true
                }
                MaterialIcon {
                    anchors.centerIn: parent
                    visible: !card.entry.thumbnail
                    text: "desktop_windows"
                    fontStyle: Tokens.font.icon.size(40).build()
                    color: Colours.palette.m3primary
                }
                Rectangle {
                    anchors.fill: parent
                    radius: 8
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.alpha(Colours.palette.m3outlineVariant,0.55)
                }
            }
        }
    }
    MouseArea {
        x: (root.width - width) / 2; y: 8
        width: root.coverWidth; height: root.coverHeight
        z: 300
        enabled: !!root.currentEntry
        acceptedButtons: Qt.LeftButton
        cursorShape: Qt.PointingHandCursor
        property var pressedEntry: null
        onPressed: pressedEntry = root.currentEntry ? Object.assign({},root.currentEntry) : null
        onCanceled: pressedEntry = null
        onClicked: {
            if (pressedEntry) root.activate(pressedEntry);
            pressedEntry = null;
        }
        onWheel: event => root.wheel(event)
    }
    MouseArea {
        id: actionZone
        x: (root.width + root.coverWidth) / 2 - width - 4; y: 12
        width: 40; height: 40; z: 400
        visible: root.animatedCount > 0
        acceptedButtons: Qt.LeftButton
        preventStealing: true
        property var pressedEntry: null
        onClicked: event => event.accepted = true
        onWheel: event => root.wheel(event)
        IconButton {
            anchors.centerIn: parent
            icon: "close"
            type: IconButton.Tonal
            font: Tokens.font.icon.small
            padding: 6
            disabled: !root.currentEntry || !root.settled
            ToolTip.visible: hovered
            ToolTip.text: "Close window"
            ToolTip.delay: 450
            Accessible.name: "Close window: " + (root.currentEntry?.title ?? "")
            onPressedChanged: if (pressed) {
                actionZone.pressedEntry = root.currentEntry ? Object.assign({},root.currentEntry) : null;
                root.blockedUntil = Date.now() + 260;
            }
            onClicked: {
                root.requestSecondary(actionZone.pressedEntry);
                actionZone.pressedEntry = null;
            }
        }
    }
}
