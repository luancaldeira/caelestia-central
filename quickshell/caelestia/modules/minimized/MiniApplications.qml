pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Widgets
import Caelestia.Config
import qs.components
import qs.services

Item {
    id: root
    required property ShellScreen screen
    property real maximumWidth: 600
    readonly property var entries: ApplicationLibrary.favoriteEntries
    readonly property int columns: Math.max(1,Math.min(12,Math.floor((maximumWidth - 14) / 46)))
    readonly property int occupiedColumns: Math.min(columns,Math.max(1,entries.length))
    readonly property int rows: Math.ceil(entries.length / columns)
    property double launchBlockedUntil: 0
    signal launched()

    implicitWidth: entries.length ? occupiedColumns * 36 + (occupiedColumns - 1) * 10 + 24 : 136
    implicitHeight: rows ? rows * 36 + (rows - 1) * 10 + 20 : 0

    Flow {
        anchors.top: parent.top
        anchors.topMargin: 10
        anchors.horizontalCenter: parent.horizontalCenter
        width: root.implicitWidth - 24
        spacing: 10
        Repeater {
            model: root.entries
            delegate: Item {
                id: appIcon
                required property var modelData
                width: 36
                height: 36
                Accessible.role: Accessible.Button
                Accessible.name: modelData.title
                IconImage {
                    id: image
                    anchors.centerIn: parent
                    implicitSize: 32
                    source: Quickshell.iconPath(appIcon.modelData.icon, true)
                    visible: status === Image.Ready
                    asynchronous: true
                    mipmap: true
                }
                MaterialIcon {
                    anchors.centerIn: parent
                    visible: image.status !== Image.Ready
                    text: "apps"
                    fontStyle: Tokens.font.icon.size(30).build()
                    color: Colours.palette.m3primary
                }
                MouseArea {
                    anchors.fill: parent
                    property string pressedId: ""
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    cursorShape: Qt.PointingHandCursor
                    onPressed: mouse => {
                        pressedId = String(appIcon.modelData.id);
                        if (mouse.button === Qt.RightButton) root.launchBlockedUntil = Date.now() + 500;
                    }
                    onCanceled: pressedId = ""
                    onClicked: mouse => {
                        if (!pressedId || pressedId !== String(appIcon.modelData.id)) return;
                        if (mouse.button === Qt.RightButton) ApplicationLibrary.favorite(pressedId);
                        else if (Date.now() >= root.launchBlockedUntil) {
                            const rect = appIcon.mapToItem(null,Qt.rect(2,2,32,32));
                            const panel = ShellState.componentsFor(root.screen)?.panels?.minimized;
                            const origin = panel?.bubbleOrigin(rect.x + root.screen.x + rect.width / 2) ||
                                {x:rect.x + root.screen.x,y:rect.y + root.screen.y,width:rect.width,height:rect.height};
                            if (ApplicationLibrary.launch(pressedId,origin)) root.launched();
                        }
                    }
                    onWheel: event => event.accepted = true
                }
            }
        }
    }
}
