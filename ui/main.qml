import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "Theme.js" as Theme

ApplicationWindow {
    id: window
    width: 1180
    height: 780
    minimumWidth: 980
    minimumHeight: 760
    visible: false
    color: Theme.bg
    title: "Wolverine to DS5"
    flags: Qt.Window | Qt.FramelessWindowHint

    property bool quitting: false
    property var appModel: Placeholder {}
    signal hideRequested()
    signal quitRequested()

    FontLoader { source: "assets/fonts/RazerF5-Regular.ttf" }
    FontLoader { source: "assets/fonts/RazerF5-SemiBold.ttf" }
    FontLoader { source: "assets/fonts/Roboto-Regular.ttf" }
    FontLoader { source: "assets/fonts/Roboto-Medium.ttf" }
    FontLoader { source: "assets/fonts/Roboto-Bold.ttf" }

    onClosing: function(close) {
        if (quitting) {
            close.accepted = true
            return
        }
        close.accepted = false
        if (appModel.trayAvailable) {
            window.visible = false
            hideRequested()
        } else {
            quitRequested()
        }
    }

    TitleBar {
        id: titleBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 42
    }

    NavBar {
        id: tabBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: titleBar.bottom
        height: 56
    }

    Item {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: tabBar.bottom
        anchors.bottom: parent.bottom

        DotGrid { anchors.fill: parent }

        Item {
            id: pageHost
            property bool animate: !appModel.reduceMotion
            anchors.fill: parent
            anchors.topMargin: 20
            anchors.leftMargin: 26
            anchors.rightMargin: 26
            anchors.bottomMargin: 12

            StatusPage {
                anchors.fill: parent
                opacity: tabBar.current === 0 ? 1 : 0
                visible: opacity > 0.01
                enabled: tabBar.current === 0
                z: tabBar.current === 0 ? 1 : 0
                Behavior on opacity {
                    enabled: pageHost.animate
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
            }

            SystemPage {
                anchors.fill: parent
                opacity: tabBar.current === 1 ? 1 : 0
                visible: opacity > 0.01
                enabled: tabBar.current === 1
                z: tabBar.current === 1 ? 1 : 0
                Behavior on opacity {
                    enabled: pageHost.animate
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
            }
        }

        Toast {
            id: toast
            x: content.width - width - 2
            y: 10
        }
    }

    Connections {
        target: appModel
        ignoreUnknownSignals: true
        function onToastRequested(kind, title, content) {
            toast.show(kind, title, content)
        }
    }

    MouseArea {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 4
        cursorShape: Qt.SizeHorCursor
        onPressed: window.startSystemResize(Qt.LeftEdge)
    }

    MouseArea {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 4
        cursorShape: Qt.SizeHorCursor
        onPressed: window.startSystemResize(Qt.RightEdge)
    }

    MouseArea {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 4
        cursorShape: Qt.SizeVerCursor
        onPressed: window.startSystemResize(Qt.BottomEdge)
    }

    MouseArea {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: 12
        height: 12
        cursorShape: Qt.SizeFDiagCursor
        onPressed: window.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
    }
}
