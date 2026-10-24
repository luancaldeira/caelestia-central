pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.services

// A single deferred thumbnail job per monitor, after window motion has ended.
Item {
    id: root
    required property ShellScreen screen
    property string address: ""
    property string destination: ""
    property bool grabbing: false
    property var queue: []
    property int capturedPid: 0
    property int serial: 0
    property var pendingImage: null

    x: -4096
    y: -4096
    width: 640
    height: 360

    function nextCapture() {
        if (address || queue.length === 0 || WindowDrawer.motions.count || ShellState.sessionLocked)
            return;
        const job = queue.shift();
        const entry = Minimized.entries.find(e => e.address === job.address && e.pid === job.pid);
        if (!entry || entry.thumbnail || !job.toplevel || job.path !== Minimized.thumbnailDir + "/" + job.address + "-" + entry.time + ".png") {
            Qt.callLater(nextCapture);
            return;
        }
        serial++;
        address = job.address;
        destination = job.path;
        capturedPid = job.pid;
        capture.captureSource = job.toplevel.wayland;
        release.restart();
        if (capture.hasContent)
            Qt.callLater(finish);
    }

    function finish() {
        if (!capture.hasContent || grabbing || !address)
            return;
        grabbing = true;
        const jobSerial = serial;
        root.grabToImage(result => {
            if (jobSerial !== root.serial) return;
            release.stop();
            root.pendingImage = result;
            root.savePending();
        }, Qt.size(640, 360));
    }
    function savePending() {
        if (!pendingImage || WindowDrawer.motions.count || ShellState.sessionLocked) return;
        const saved = pendingImage.saveToFile(destination);
        Minimized.completeThumbnail(address, saved ? destination : "", capturedPid);
        clear();
    }
    function clear() {
        serial++;
        pendingImage = null;
        capture.captureSource = null;
        address = "";
        grabbing = false;
        release.stop();
        Qt.callLater(nextCapture);
    }

    Rectangle { anchors.fill: parent; color: "#111318" }
    ScreencopyView {
        id: capture
        anchors.fill: parent
        live: false
        paintCursor: false
        constraintSize: Qt.size(640, 360)
        onHasContentChanged: if (hasContent) Qt.callLater(root.finish)
    }
    Timer { id: idleSave; interval: 80; onTriggered: { root.savePending(); root.nextCapture(); } }
    Timer {
        id: release
        interval: 750
        onTriggered: root.clear()
    }
    Connections {
        target: Minimized
        function onCaptureRequested(toplevel, address, path) {
            if (toplevel.monitor?.name !== root.screen.name)
                return;
            root.queue.push({toplevel: toplevel, address: address, path: path, pid: toplevel.lastIpcObject.pid});
            root.nextCapture();
        }
    }
    Connections {
        target: WindowDrawer.motions
        function onCountChanged() { if (!WindowDrawer.motions.count) idleSave.restart(); }
    }
    Connections {
        target: ShellState
        function onSessionLockedChanged() { if (!ShellState.sessionLocked) idleSave.restart(); }
    }
}
