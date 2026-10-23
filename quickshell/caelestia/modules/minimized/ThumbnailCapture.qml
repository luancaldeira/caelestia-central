pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.services

// A single on-demand capture per monitor. Nothing is captured while idle.
Item {
    id: root
    required property ShellScreen screen
    property string address: ""
    property string destination: ""
    property bool grabbing: false
    property var queue: []

    x: -4096
    y: -4096
    width: 640
    height: 360

    function nextCapture() {
        if (address || queue.length === 0)
            return;
        const job = queue.shift();
        if (!Minimized.pending[job.address] || !job.toplevel) {
            Qt.callLater(nextCapture);
            return;
        }
        address = job.address;
        destination = job.path;
        capture.captureSource = job.toplevel.wayland;
        release.restart();
        if (capture.hasContent)
            captureReady.restart();
    }

    function finish() {
        if (!capture.hasContent || grabbing || !address)
            return;
        grabbing = true;
        const a = address;
        const path = destination;
        root.grabToImage(result => {
            const saved = result.saveToFile(path);
            Minimized.completeCapture(a, saved ? path : "");
            root.address = "";
            capture.captureSource = null;
            root.grabbing = false;
            release.stop();
            Qt.callLater(root.nextCapture);
        }, Qt.size(640, 360));
    }

    Rectangle { anchors.fill: parent; color: "#111318" }
    ScreencopyView {
        id: capture
        anchors.fill: parent
        live: true
        paintCursor: false
        constraintSize: Qt.size(640, 360)
        onHasContentChanged: if (hasContent) captureReady.restart()
    }
    Timer { id: captureReady; interval: 45; onTriggered: root.finish() }
    Timer {
        id: release
        interval: 750
        onTriggered: {
            capture.captureSource = null;
            root.address = "";
            root.grabbing = false;
            Qt.callLater(root.nextCapture);
        }
    }
    Connections {
        target: Minimized
        function onCaptureRequested(toplevel, address, path) {
            if (toplevel.monitor?.name !== root.screen.name)
                return;
            root.queue.push({toplevel: toplevel, address: address, path: path});
            root.nextCapture();
        }
    }
}
