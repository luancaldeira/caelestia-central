pragma Singleton
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.services

Singleton {
    id: root

    property string token: ""
    property var frames: ({})
    property var readyOutputs: ({})
    property point origin: Qt.point(0, 0)
    property bool active: false
    property bool revealing: false
    property bool reduced: false
    property real progress: 0
    property int duration: 680
    property double started: 0
    property double finished: 0
    signal requestFrame()
    readonly property bool ready: active && Object.keys(frames).length > 0 &&
        Object.keys(frames).every(name => readyOutputs[name] === token)

    function prepare(text: string): bool {
        try {
            if (ShellState.sessionLocked) return false;
            const data = JSON.parse(text);
            if (!data.token || !data.frames || Object.keys(data.frames).length === 0) return false;
            wave.stop();
            token = data.token;
            readyOutputs = ({});
            origin = Qt.point(data.origin.x, data.origin.y);
            duration = data.duration;
            reduced = data.reduced;
            progress = 0;
            revealing = false;
            Colours.spatialTransition = true;
            frames = data.frames;
            active = true;
            watchdog.restart();
            // A retarget may reuse the same pixels and source. Explicitly ask
            // Qt to present it so readiness cannot wait on an unchanged image.
            Qt.callLater(() => root.requestFrame());
            return true;
        } catch (e) {
            console.warn("Wallpaper transition prepare:", e);
            return false;
        }
    }
    function markReady(name: string): void {
        if (!active || revealing || readyOutputs[name] === token) return;
        readyOutputs = Object.assign({}, readyOutputs, {[name]: token});
    }
    function reveal(id: string, scheme: string): bool {
        if (!active || token !== id || !ready) return false;
        // All new colours are committed behind the old snapshot. The moving
        // hole exposes each part of the shell only when the splash reaches it.
        Colours.load(scheme, false);
        revealing = true;
        started = Date.now();
        Qt.callLater(() => { if (root.active && root.token === id) wave.start(); });
        return true;
    }
    function cancel(id: string): void {
        if (id && token !== id) return;
        wave.stop();
        active = false;
        revealing = false;
        Colours.spatialTransition = false;
        frames = ({});
        readyOutputs = ({});
        watchdog.stop();
        finished = Date.now();
    }

    NumberAnimation {
        id: wave
        target: root
        property: "progress"
        from: 0; to: 1
        duration: root.reduced ? 160 : root.duration
        easing.type: Easing.InOutCubic
        onFinished: root.cancel(root.token)
    }
    Timer {
        id: watchdog
        interval: 5000
        onTriggered: root.cancel(root.token)
    }
    Connections {
        target: ShellState
        function onSessionLockedChanged(): void {
            if (ShellState.sessionLocked) root.cancel(root.token);
        }
    }
    Connections {
        target: Hypr
        function onActiveWsIdChanged(): void {
            if (root.active) root.cancel(root.token);
        }
    }

    Variants {
        model: Quickshell.screens
        PanelWindow {
            id: overlay
            required property ShellScreen modelData
            readonly property var frame: root.frames[modelData.name]
            screen: modelData
            visible: root.active && !!frame
            color: "transparent"
            surfaceFormat.opaque: false
            exclusionMode: ExclusionMode.Ignore
            anchors { top: true; bottom: true; left: true; right: true }
            WlrLayershell.namespace: "caelestia-wallpaper-splash"
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            mask: Region {}

            Image {
                id: previous
                anchors.fill: parent
                visible: false
                source: overlay.frame ? "file://" + overlay.frame.path : ""
                cache: false
                asynchronous: false
                fillMode: Image.Stretch
            }
            ShaderEffect {
                id: splash
                anchors.fill: parent
                readonly property var source: previous
                readonly property vector2d dimensions: Qt.vector2d(width, height)
                readonly property vector2d center: Qt.vector2d(root.origin.x - (overlay.frame?.x ?? 0), root.origin.y - (overlay.frame?.y ?? 0))
                readonly property real progress: root.progress
                readonly property real reduced: root.reduced ? 1 : 0
                readonly property color accent: Colours.palette.m3primary
                fragmentShader: "../modules/wallpaper/splash.frag.qsb"
            }
            Connections {
                target: root
                function onRequestFrame(): void { previous.Window.window?.update(); }
            }
            Connections {
                target: previous.Window.window
                function onFrameSwapped(): void {
                    // The prebuilt shader can draw correctly while Qt leaves
                    // ShaderEffect.status at Uncompiled. A swapped frame plus
                    // the loaded snapshot is the reliable readiness barrier.
                    if (overlay.visible && previous.status === Image.Ready)
                        root.markReady(overlay.modelData.name);
                }
            }
        }
    }
    IpcHandler {
        target: "wallpapertransition"
        function prepare(data: string): bool { return root.prepare(data); }
        function reveal(token: string, scheme: string): bool { return root.reveal(token, scheme); }
        function cancel(token: string): void { root.cancel(token); }
        function info(): string {
            return JSON.stringify({token:root.token,active:root.active,ready:root.ready,revealing:root.revealing,
                progress:root.progress,started:root.started,finished:root.finished,duration:root.duration,
                sessionLocked:ShellState.sessionLocked});
        }
    }
}
