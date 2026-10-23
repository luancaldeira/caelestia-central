import QtQuick

Item {
    id: root
    required property int count
    required property int currentIndex
    property bool active: true
    property bool animate: true
    property int transitionDuration: 500
    property real radius: 200
    property real oblique: count === 2 ? 0.5 : 0
    property real spread: count > 1 ? 1 : 0
    readonly property real sideAngle: count > 10 ? Math.PI / 5 : step
    property real angularGain: count > 10 ? Math.tan(sideAngle / 2) / Math.tan(step / 2) : 1
    property real normalizer: count === 2 ? 1 : Math.max(0.45,Math.abs(Math.sin(count > 10 ? sideAngle : step)))
    property real phase: 0
    property real targetPhase: 0
    property int selectedIndex: -1
    property int selectedCount: -1
    property bool ready: false
    property bool selectionQueued: false
    readonly property real turn: 2 * Math.PI
    readonly property real step: count > 1 ? turn / count : 0

    function select(index, direction = 0) {
        if (!active || index < 0 || index >= count) return;
        if (selectedIndex === index && selectedCount === count) return;
        const canonical = index * step;
        let delta = Math.atan2(Math.sin(canonical - targetPhase), Math.cos(canonical - targetPhase));
        // Preserve the selected card's bearing when indices shift after a model edit.
        if (selectedCount > 0 && selectedCount !== count)
            delta = canonical - selectedIndex * turn / selectedCount;
        if (direction > 0 && delta < -0.000001) delta += turn;
        else if (direction < 0 && delta > 0.000001) delta -= turn;
        targetPhase += delta;
        selectedIndex = index;
        selectedCount = count;
        // Never normalize the animated phase: last -> first continues the same turn.
        phase = targetPhase;
    }
    function queueSelection() {
        if (!ready || selectionQueued) return;
        selectionQueued = true;
        // Model removals update count and index together; reconcile their final values.
        Qt.callLater(() => { selectionQueued = false; select(currentIndex); });
    }
    function project(angle) {
        const rawCosine = Math.cos(angle);
        const denominator = (1 + rawCosine) + angularGain * angularGain * (1 - rawCosine);
        const cosine = ((1 + rawCosine) - angularGain * angularGain * (1 - rawCosine)) / denominator;
        const sine = 2 * angularGain * Math.sin(angle) / denominator;
        const depth = (1 + cosine) / 2;
        // A slight oblique view keeps the rear card visible in a two-window ring.
        const side = sine + oblique * (1 - cosine);
        return {
            x: radius * side * spread,
            y: -8 * (1 - cosine) * spread,
            scale: 1 - 0.16 * (1 - depth) * spread,
            z: 100 - 99 * (1 - depth) * spread,
            opacity: 1 - 0.18 * (1 - depth) * spread,
            rotation: -62 * Math.max(-1,Math.min(1,side / normalizer)) * spread
        };
    }
    onCountChanged: queueSelection()
    onCurrentIndexChanged: queueSelection()
    Component.onCompleted: { select(currentIndex); ready = true; }
    Behavior on radius {
        enabled: root.ready && root.active && root.animate
        SmoothedAnimation { duration: root.transitionDuration; velocity: -1; maximumEasingTime: 120 }
    }
    Behavior on oblique {
        enabled: root.ready && root.active && root.animate
        SmoothedAnimation { duration: root.transitionDuration; velocity: -1; maximumEasingTime: 120 }
    }
    Behavior on spread {
        enabled: root.ready && root.active && root.animate
        SmoothedAnimation { duration: root.transitionDuration; velocity: -1; maximumEasingTime: 120 }
    }
    Behavior on angularGain {
        enabled: root.ready && root.active && root.animate
        SmoothedAnimation { duration: root.transitionDuration; velocity: -1; maximumEasingTime: 120 }
    }
    Behavior on normalizer {
        enabled: root.ready && root.active && root.animate
        SmoothedAnimation { duration: root.transitionDuration; velocity: -1; maximumEasingTime: 120 }
    }
    Behavior on phase {
        enabled: root.ready && root.active && root.animate
        SmoothedAnimation {
            duration: root.transitionDuration
            velocity: -1
            maximumEasingTime: 120
            reversingMode: SmoothedAnimation.Eased
        }
    }
}
