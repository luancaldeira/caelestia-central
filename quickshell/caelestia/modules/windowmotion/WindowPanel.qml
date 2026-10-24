pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window
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
    property bool priming: false
    property int primedSwaps: 0
    property double imageReadyAt: 0
    property bool detached: model?.minimizing ?? false
    property bool finishing: false
    property real offsetScale: 0
    readonly property double createdAt: Date.now()
    property double startedAt: 0
    property double settledAt: 0
    property int frameCount: 0
    property real maxFrameMs: 0
    property real totalFrameMs: 0
    property int contentRefreshes: 0
    property double releaseRequestedAt: 0
    property double nativeFrameAt: 0
    property bool handoffFallback: false
    property bool retired: false
    property real elasticity: 1
    property bool landingStarted: false
    property double landingStartedAt: 0
    property bool awaitingPose: false
    property int finalPoseSwaps: 0
    readonly property real nativeRadius: model?.goalRounding >= 0 ? model.goalRounding : Tokens.rounding.extraLarge
    // Decorated exports already carry the compositor's exact corner mask.
    readonly property real clipRadius: model?.decorated ? Tokens.rounding.extraLarge*elasticity : nativeRadius+(Tokens.rounding.extraLarge-nativeRadius)*elasticity
    readonly property real backingOpacity: elasticity
    readonly property matrix4x4 imageTransform: Qt.matrix4x4(
        1+(deformation.m11-1)*elasticity,deformation.m12*elasticity,0,deformation.m14*elasticity,
        deformation.m21*elasticity,1+(deformation.m22-1)*elasticity,0,deformation.m24*elasticity,
        0,0,1,0, 0,0,0,1)
    readonly property real destination: model?.minimizing ? 1 : 0
    // Clear the entire SDF join before removing a departing surface. Five
    // pixels outside the content clip still contribute to the border's blob.
    readonly property real distance: screen.height-borderThickness+2*smoothing+5-((model?.goalY ?? screen.y)-(model?.captureTop ?? 0)-screen.y)
    readonly property real gap: screen.height-2*borderThickness-panel.y-panel.height/2-
        (Math.abs(deformation.m21)*panel.width+Math.abs(deformation.m22)*panel.height)/2

    function prime() {
        if(!model || started || priming || finishing || !capture.hasContent || !client) return;
        priming=true;
        imageReadyAt=Date.now();
        primedSwaps=0;
        root.Window.window?.update();
    }
    function start() {
        if(!model || started || finishing || primedSwaps<2 || !capture.hasContent || !client) return;
        started=true;
        priming=false;
        startedAt=Date.now();
        captureDeadline.stop();
        WindowDrawer.claim(model);
        updateJoin();
        offsetScale=Qt.binding(()=>root.destination);
        frames.restart();
    }
    function updateJoin() {
        if(!started) return;
        if(model?.minimizing && gap<Math.max(2,smoothing*.6)) detached=false;
        else if(!model?.minimizing && gap>Math.max(2,smoothing*.6)) detached=true;
    }
    function complete() {
        if(finishing || retired || !model) return;
        frames.stop();
        finishing=true;
        settledAt=Date.now();
        if(model?.minimizing) retire();
        else {
            releaseRequestedAt=Date.now();
            WindowDrawer.release(model,releaseRequestedAt);
            handoffDeadline.start();
        }
    }
    function retire() {
        if(retired || !model) return;
        retired=true;
        handoffDeadline.stop();
        WindowDrawer.complete(model);
    }
    function beginLanding(elapsedMs) {
        if(landingStarted) return;
        landingStarted=true;
        landingStartedAt=Date.now();
        detached=true;
        landing.to=0;
        landing.duration=Math.max(Math.min(100,slide.duration*.2),slide.duration-elapsedMs);
        landing.restart();
    }
    function edgeError() {
        const m=imageTransform;
        let error=0;
        for(const x of [0,panel.width]) for(const y of [0,panel.height]) {
            error=Math.max(error,Math.abs((m.m11-1)*x+m.m12*y+m.m14),
                Math.abs(m.m21*x+(m.m22-1)*y+m.m24+distance*offsetScale));
        }
        return error;
    }
    function info() {
        if(!model) return null;
        return {address:model.address,pid:model.pid,token:model.token,minimizing:model.minimizing,
            decorated:model.decorated,captureTop:model.captureTop,hasContent:capture.hasContent,sourceWidth:capture.sourceSize.width,sourceHeight:capture.sourceSize.height,
            offset:offsetScale,detached:detached,started:started,animating:slide.running,
            x:panel.x+leftInset,y:panel.y+borderThickness,width:panel.width,height:panel.height,gap:gap,
            deform:[deformation.m11,deformation.m12,deformation.m21,deformation.m22],
            receivedAt:model.receivedAt,createdAt:createdAt,startedAt:startedAt,settledAt:settledAt,
            frameCount:frameCount,maxFrameMs:maxFrameMs,meanFrameMs:frameCount ? totalFrameMs/frameCount : 0,
            contentRefreshes:contentRefreshes,imageReadyAt:imageReadyAt,primedSwaps:primedSwaps,
            releaseRequestedAt:releaseRequestedAt,nativeFrameAt:nativeFrameAt,
            handoffFallback:handoffFallback,finishing:finishing,retired:retired,
            elasticity:elasticity,landingStartedAt:landingStartedAt,landingDuration:landing.duration,
            imageTransform:[imageTransform.m11,imageTransform.m12,imageTransform.m21,imageTransform.m22,imageTransform.m14,imageTransform.m24],
            edgeErrorPx:edgeError(),clipRadius:clipRadius,nativeRadius:nativeRadius,finalPoseSwaps:finalPoseSwaps};
    }
    onGapChanged: updateJoin()
    onDestinationChanged: {
        if(started && model) {
            handoffDeadline.stop();
            finishing=false;
            retired=false;
            releaseRequestedAt=0;
            nativeFrameAt=0;
            handoffFallback=false;
            awaitingPose=false;
            finalPoseSwaps=0;
            landingStarted=false;
            landingStartedAt=0;
            landing.stop();
            if(root.model.minimizing && elasticity<1) {
                landing.to=1;
                landing.duration=Math.min(100,slide.duration*.2);
                landing.restart();
            }
            frames.restart();
        }
    }
    Behavior on offsetScale { enabled: root.started; Anim { id: slide } }
    Connections {
        target: root.Window.window
        function onFrameSwapped() {
            if(!root.model) return;
            if(root.awaitingPose && !root.finishing) {
                root.finalPoseSwaps++;
                if(root.finalPoseSwaps>=2) Qt.callLater(root.complete);
                else root.Window.window?.update();
                return;
            }
            if(!root.priming || root.started || root.finishing) return;
            // One swap may already have been in flight when capture became
            // ready. The next one contains our texture and shared background.
            root.primedSwaps++;
            if(root.primedSwaps>=2) Qt.callLater(root.start);
            else root.Window.window?.update();
        }
    }
    FrameAnimation {
        id: frames
        property real nextCaptureAt: 1/30
        onTriggered: {
            if(!root.model) { stop(); return; }
            if(currentFrame>1) {
                root.frameCount++;
                root.maxFrameMs=Math.max(root.maxFrameMs,frameTime*1000);
                root.totalFrameMs+=frameTime*1000;
            }
            // Refresh client content without coupling capture throughput to a
            // high-refresh monitor. Geometry still animates at display rate.
            if((!root.model.minimizing || slide.running) && elapsedTime>=nextCaptureAt) {
                capture.captureFrame();
                root.contentRefreshes++;
                nextCaptureAt=elapsedTime+1/30;
            }
            const m=root.deformation;
            const atRest=Math.abs(m.m11-1)+Math.abs(m.m12)+Math.abs(m.m21)+Math.abs(m.m22-1)<.006;
            if(root.model.minimizing) {
                if(!slide.running && Math.abs(root.offsetScale-root.destination)<.0001 && atRest) {
                    root.detached=false;
                    root.complete();
                }
            } else {
                if(!root.landingStarted && (root.detached || !slide.running) && elapsedTime*1000>=slide.duration*.65)
                    root.beginLanding(elapsedTime*1000);
                if(!slide.running && root.elasticity===0 && !landing.running && !root.awaitingPose) {
                    root.awaitingPose=true;
                    root.finalPoseSwaps=0;
                    root.Window.window?.update();
                }
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
            x: (root.model?.goalX ?? 0)-(root.model?.captureLeft ?? 0)-root.screen.x-root.leftInset
            y: (root.model?.goalY ?? 0)-(root.model?.captureTop ?? 0)-root.screen.y-root.borderThickness+root.distance*root.offsetScale
            width: (root.model?.goalWidth ?? 0)+(root.model?.captureLeft ?? 0)+(root.model?.captureRight ?? 0)
            height: (root.model?.goalHeight ?? 0)+(root.model?.captureTop ?? 0)+(root.model?.captureBottom ?? 0)
            opacity: (root.priming || root.started) ? 1 : 0
            transform: Matrix4x4 { matrix: root.imageTransform }
            StyledClippingRect {
                anchors.fill: parent
                radius: root.clipRadius
                ScreencopyView {
                    id: capture
                    anchors.fill: parent
                    captureSource: root.client?.wayland ?? null
                    live: false
                    paintCursor: false
                    onHasContentChanged: if(hasContent) Qt.callLater(root.prime)
                }
            }
        }
    }

    NumberAnimation {
        id: landing
        target: root
        property: "elasticity"
        easing.type: Easing.InOutCubic
    }

    Connections {
        target: WindowDrawer
        function onPresented(frame) {
            if(!root.finishing || root.model?.minimizing || frame.address!==root.model?.address ||
               frame.pid!==root.model.pid || frame.token!==root.model.token || frame.releaseId!==root.releaseRequestedAt) return;
            root.nativeFrameAt=Date.now();
            root.retire();
        }
    }
    Timer {
        id: handoffDeadline
        interval: 160
        onTriggered: {
            root.handoffFallback=true;
            console.warn("WindowDrawer: compositor handoff acknowledgment unavailable");
            root.retire();
        }
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
    Component.onCompleted: {
        offsetScale=model.minimizing ? 0 : 1;
        identity=String(model.address);
        WindowDrawer.attach(identity,root);
        Qt.callLater(prime);
    }
    Component.onDestruction: WindowDrawer.detach(identity,root)
}
