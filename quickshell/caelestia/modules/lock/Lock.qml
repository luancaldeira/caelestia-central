pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.components.misc
import qs.services

Scope {
    id: root

    property alias lock: sessionLock

    function syncLockState(): void {
        ShellState.syncSessionLock(sessionLock);
    }

    WlSessionLock {
        id: sessionLock

        signal unlock

        onLockStateChanged: root.syncLockState()
        onSecureStateChanged: root.syncLockState()
        Component.onCompleted: root.syncLockState()

        LockSurface {
            lock: sessionLock
            pam: pam
        }
    }

    Pam {
        id: pam

        lock: sessionLock
    }

    Loader {
        asynchronous: true
        active: true
        onLoaded: active = false

        // Force a load of a screencopy so the one in the lock works
        // My guess is the ICC backend loads async on first request, which if the lock is
        // the first request it fails to capture (because it's async and the compositor
        // refuses capture when locked)
        sourceComponent: ScreencopyView {
            captureSource: Quickshell.screens[0]
        }
    }

    // qmllint disable unresolved-type
    CustomShortcut {
        // qmllint enable unresolved-type
        name: "lock"
        description: "Lock the current session"
        onPressed: sessionLock.locked = true
    }

    // qmllint disable unresolved-type
    CustomShortcut {
        // qmllint enable unresolved-type
        name: "unlock"
        description: "Unlock the current session"
        onPressed: sessionLock.unlock()
    }

    IpcHandler {
        function lock(): void {
            sessionLock.locked = true;
        }

        function unlock(): void {
            sessionLock.unlock();
        }

        function isLocked(): bool {
            // A direct getter stays correct even if the native unlock path
            // omits its final property notification. Refresh the shared guard
            // before the wallpaper controller prepares its snapshot.
            root.syncLockState();
            return sessionLock.locked || sessionLock.secure;
        }

        function state(): string {
            return JSON.stringify({locked:sessionLock.locked,secure:sessionLock.secure,
                tracked:ShellState.sessionLocked});
        }

        target: "lock"
    }
}
