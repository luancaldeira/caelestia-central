import QtQuick
import Quickshell
import Quickshell.Widgets
import Caelestia.Config
import qs.components
import qs.services
import qs.utils
import qs.modules.launcher.services

Item {
    id: root

    required property DesktopEntry modelData
    required property ScreenState screenState
    property double launchBlockedUntil: 0
    readonly property bool centralFavorite: modelData && ApplicationLibrary.favorites.includes(String(modelData.id))

    implicitHeight: Tokens.sizes.launcher.itemHeight

    anchors.left: parent?.left
    anchors.right: parent?.right

    StateLayer {
        id: stateLayer
        property string pressedId: ""
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        radius: Tokens.rounding.large
        onPressed: mouse => {
            press(mouse.x,mouse.y);
            pressedId = String(root.modelData.id);
            if (mouse.button === Qt.RightButton) root.launchBlockedUntil = Date.now() + 500;
        }
        onCanceled: pressedId = ""
        onClicked: mouse => {
            if (pressedId !== String(root.modelData.id)) return;
            if (mouse.button === Qt.RightButton) {
                ApplicationLibrary.favorite(pressedId);
                return;
            }
            if (Date.now() < root.launchBlockedUntil) return;
            Apps.launch(root.modelData);
            root.screenState.launcher = false;
        }
    }
    StyledRect {
        anchors.fill: parent
        radius: Tokens.rounding.large
        border.width: 1
        border.color: Qt.alpha(Colours.palette.m3primary,root.centralFavorite && stateLayer.containsMouse ? 0.85 : 0)
    }

    Item {
        anchors.fill: parent
        anchors.leftMargin: Tokens.padding.medium
        anchors.rightMargin: Tokens.padding.medium
        anchors.margins: Tokens.padding.small

        IconImage {
            id: icon

            asynchronous: true
            source: root.modelData?.icon ? Quickshell.iconPath(root.modelData.icon, true) : ""
            visible: status === Image.Ready
            implicitSize: parent.height * 0.8

            anchors.verticalCenter: parent.verticalCenter
        }
        MaterialIcon {
            anchors.centerIn: icon
            visible: icon.status !== Image.Ready
            text: "apps"
            fontStyle: Tokens.font.icon.size(Math.round(icon.implicitSize)).build()
            color: Colours.palette.m3primary
        }

        Item {
            anchors.left: icon.right
            anchors.leftMargin: Tokens.spacing.medium
            anchors.verticalCenter: icon.verticalCenter

            implicitWidth: parent.width - icon.width - favouriteIcon.width
            implicitHeight: name.implicitHeight + comment.implicitHeight

            StyledText {
                id: name

                text: root.modelData?.name ?? ""
                font: Tokens.font.body.medium
            }

            StyledText {
                id: comment

                text: (root.modelData?.comment || root.modelData?.genericName || root.modelData?.name) ?? ""
                font: Tokens.font.body.small
                color: Colours.palette.m3outline

                elide: Text.ElideRight
                width: root.width - icon.width - favouriteIcon.width - Tokens.rounding.extraLargeIncreased

                anchors.top: name.bottom
            }
        }

        Loader {
            id: favouriteIcon

            asynchronous: true
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            active: root.modelData && Strings.testRegexList(GlobalConfig.launcher.favouriteApps, root.modelData.id)

            sourceComponent: MaterialIcon {
                text: "favorite"
                fill: 1
                color: Colours.palette.m3primary
            }
        }
    }
}
