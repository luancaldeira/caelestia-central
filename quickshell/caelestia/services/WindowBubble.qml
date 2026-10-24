pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import qs.services

Singleton {
    id: root
    readonly property alias motions: motions
    property int receivedFrames: 0
    property var anchors: ({})

    ListModel { id: motions; dynamicRoles: true }
    function indexOf(address) {
        for (let i=0;i<motions.count;i++) if (motions.get(i).address === address) return i;
        return -1;
    }
    function snapshot() {
        const result = [];
        for (let i=0;i<motions.count;i++) result.push(motions.get(i));
        return result;
    }
    function registerBar(name, port, duration=500, curve=[.38,1.21,.22,1]) {
        if (!name || ![port.x,port.y,port.width,port.height].every(Number.isFinite)) return;
        anchors = Object.assign({}, anchors, {[name]:Object.assign({},port,{duration:duration,curve:Array.from(curve)})});
        const values = [JSON.stringify(name),port.x,port.y,port.width,port.height,duration,...Array.from(curve).slice(0,4)].join(",");
        Hypr.dispatch(`function() local p=hl.plugin.caelestia_minimize; if p and p.set_bar_origin then p.set_bar_origin(${values}) end end`);
    }
    function replayAnchors() {
        for (const [name,port] of Object.entries(anchors)) registerBar(name,port,port.duration,port.curve);
    }
    function update(data) {
        try {
            const frame = JSON.parse(data);
            if (!frame.address) return;
            receivedFrames++;
            const index = indexOf(frame.address);
            if (!frame.visible || ShellState.sessionLocked || frame.done) {
                if (index >= 0) motions.remove(index);
                return;
            }
            if (![frame.x,frame.y,frame.width,frame.height,frame.portX,frame.portY,frame.portWidth,frame.portHeight,frame.openness,frame.clientAlpha,frame.rounding].every(Number.isFinite)) return;
            // A stable model updates the existing blob shapes each frame.
            const values = {address:frame.address,windowX:frame.x,windowY:frame.y,
                windowWidth:frame.width,windowHeight:frame.height,
                portX:frame.portX,portY:frame.portY,portWidth:frame.portWidth,portHeight:frame.portHeight,
                openness:frame.openness,clientAlpha:frame.clientAlpha,rounding:frame.rounding,expires:Date.now()+250};
            if (index >= 0) motions.set(index,values);
            else if (!frame.done) {
                if (motions.count >= 8) motions.remove(0);
                motions.append(values);
            }
        } catch (e) { console.warn("WindowBubble: invalid motion frame", e); }
    }
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (event.name === "caelestia_bubble") root.update(event.data);
            else if (["caelestia_bubble_ready","configreloaded"].includes(event.name)) root.replayAnchors();
        }
    }
    Connections {
        target: ShellState
        function onSessionLockedChanged() { if (ShellState.sessionLocked) motions.clear(); }
    }
    Timer {
        interval: 100
        running: motions.count > 0
        repeat: true
        onTriggered: {
            for (let i=motions.count-1;i>=0;i--)
                if (motions.get(i).expires <= Date.now()) motions.remove(i);
        }
    }
    IpcHandler {
        target: "windowbubble"
        function info(): string { return JSON.stringify({frames:root.receivedFrames,active:root.snapshot(),anchors:root.anchors}); }
    }
}
