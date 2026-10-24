pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland
import Caelestia.Config
import qs.components
import qs.services

Item {
    id: root
    required property var model
    required property ShellScreen screen
    required property real leftInset
    required property real borderThickness
    required property real smoothing
    property matrix4x4 deformation: Qt.matrix4x4()
    width: screen.width
    height: screen.height
    readonly property alias panel: panel
    readonly property var client: Hypr.toplevels.values.find(t=>Minimized.address(t.address)===model?.address && t.lastIpcObject.pid===model?.pid) ?? null
    property string identity: ""
    property bool started: false
    property bool detached: model?.minimizing ?? false
    property bool finishing: false
    property real offsetScale: model?.minimizing ? 0 : 1
    property real dissolve: 1
    readonly property double createdAt: Date.now()
    property double startedAt: 0
    property double settledAt: 0
    property int frameCount: 0
    property real maxFrameMs: 0
    property real totalFrameMs: 0
    property int contentRefreshes: 0
    readonly property real destination: model?.minimizing ? 1 : 0
    readonly property real distance: screen.height-borderThickness+5-((model?.goalY ?? screen.y)-screen.y)
    readonly property real gap: screen.height-2*borderThickness-panel.y-panel.height/2-
        (Math.abs(deformation.m21)*panel.width+Math.abs(deformation.m22)*panel.height)/2

    function start() {
        if(started || !capture.hasContent || !client) return;
        started=true;
        startedAt=Date.now();
        captureDeadline.stop();
        WindowDrawer.claim(model);
        offsetScale=Qt.binding(()=>root.destination);
        frames.restart();
    }
    function updateJoin() {
        if(!started) return;
        if(model?.minimizing && gap<Math.max(2,smoothing*.6)) detached=false;
        else if(!model?.minimizing && gap>Math.max(2,smoothing*.6)) detached=true;
    }
    function complete() {
        if(finishing) return;
        finishing=true;
        settledAt=Date.now();
        if(model?.minimizing) WindowDrawer.complete(model);
        else {
            WindowDrawer.release(model);
            handoff.start();
        }
    }
    function info() {
        if(!model) return null;
        return {address:model.address,pid:model.pid,token:model.token,minimizing:model.minimizing,
            hasContent:capture.hasContent,sourceWidth:capture.sourceSize.width,sourceHeight:capture.sourceSize.height,
            offset:offsetScale,detached:detached,started:started,animating:slide.running,
            x:panel.x+leftInset,y:panel.y+borderThickness,width:panel.width,height:panel.height,gap:gap,
            deform:[deformation.m11,deformation.m12,deformation.m21,deformation.m22],
            receivedAt:model.receivedAt,createdAt:createdAt,startedAt:startedAt,settledAt:settledAt,
            frameCount:frameCount,maxFrameMs:maxFrameMs,meanFrameMs:frameCount ? totalFrameMs/frameCount : 0,
            contentRefreshes:contentRefreshes};
    }
    onGapChanged: updateJoin()
    onDestinationChanged: {
        if(started) {
            handoff.stop();
            finishing=false;
            dissolve=1;
            frames.restart();
        }
    }
    Behavior on offsetScale { Anim { id: slide } }
    FrameAnimation {
        id: frames
        property real nextCaptureAt: 1/30
        onTriggered: {
            if(currentFrame>1) {
                root.frameCount++;
                root.maxFrameMs=Math.max(root.maxFrameMs,frameTime*1000);
                root.totalFrameMs+=frameTime*1000;
            }
            // Refresh client content without coupling capture throughput to a
            // high-refresh monitor. Geometry still animates at display rate.
            if(elapsedTime>=nextCaptureAt) {
                capture.captureFrame();
                root.contentRefreshes++;
                nextCaptureAt=elapsedTime+1/30;
            }
            const m=root.deformation;
            const atRest=Math.abs(m.m11-1)+Math.abs(m.m12)+Math.abs(m.m21)+Math.abs(m.m22-1)<.006;
            if(!slide.running && Math.abs(root.offsetScale-root.destination)<.0001 && (root.model.minimizing || atRest)) {
                stop();
                root.detached=!root.model.minimizing;
                root.complete();
            }
        }
        onRunningChanged: if(running) nextCaptureAt=1/30
    }

    // The same reserved frame and clipping as the existing drawer content.
    // Client pixels stay inside the border while its shared surface deforms.
    Item {
        x: root.leftInset
        y: root.borderThickness
        width: root.width-root.leftInset-root.borderThickness
        height: root.height-2*root.borderThickness
        clip: true
        Item {
            id: panel
            x: (root.model?.goalX ?? 0)-root.screen.x-root.leftInset
            y: (root.model?.goalY ?? 0)-root.screen.y-root.borderThickness+root.distance*root.offsetScale
            width: root.model?.goalWidth ?? 0
            height: root.model?.goalHeight ?? 0
            opacity: root.started ? root.dissolve : 0
            transform: Matrix4x4 { matrix: root.deformation }
            StyledClippingRect {
                anchors.fill: parent
                radius: Tokens.rounding.extraLarge
                ScreencopyView {
                    id: capture
                    anchors.fill: parent
                    captureSource: root.client?.wayland ?? null
                    live: false
                    paintCursor: false
                    onHasContentChanged: if(hasContent) Qt.callLater(root.start)
                }
            }
        }
    }

    NumberAnimation {
        id: handoff
        target: root
        property: "dissolve"
        to: 0
        duration: 80
        onFinished: WindowDrawer.complete(root.model)
    }
    Timer {
        id: captureDeadline
        interval: 500
        running: !root.started
        onTriggered: {
            console.warn("WindowDrawer: first client frame unavailable",root.model.address);
            root.complete();
        }
    }
    Component.onCompleted: { identity=String(model.address); WindowDrawer.attach(identity,root); Qt.callLater(start); }
    Component.onDestruction: WindowDrawer.detach(identity)
}
