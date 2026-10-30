import QtQuick
import "Theme.js" as Theme

Item {
    id: root
    objectName: "navBar"
    property int current: 0
    property var appModel: Placeholder {}
    signal pageChanged(int index)
    height: 56

    Rectangle {
        anchors.fill: parent
        color: Theme.tabbar
        border.color: "#2A2A2A"
        border.width: 1
    }

    Rectangle {
        id: pill
        x: 18 + (tabs.children[root.current] ? tabs.children[root.current].x : 0)
        y: (root.height - 32) / 2
        width: tabs.children[root.current] ? tabs.children[root.current].width : 0
        height: 32
        radius: 4
        color: Theme.green
        Behavior on x { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    }

    Row {
        id: tabs
        x: 18
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4

        Repeater {
            model: ["状态", "系统"]
            delegate: Item {
                width: label.implicitWidth + 36
                height: 32

                Text {
                    id: label
                    anchors.centerIn: parent
                    text: modelData
                    color: root.current === index ? "#0A0A0A" : "#B0B0B0"
                    font.pixelSize: 16
                    font.weight: root.current === index ? Font.DemiBold : Font.Normal
                }

                MouseArea {
                    id: hit
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.current = index
                        root.pageChanged(index)
                    }
                }
            }
        }
    }

    Row {
        anchors.right: parent.right
        anchors.rightMargin: 18
        anchors.verticalCenter: parent.verticalCenter
        spacing: 12

        Item {
            width: 10
            height: 10
            anchors.verticalCenter: parent.verticalCenter
            Rectangle {
                anchors.centerIn: parent
                width: 6
                height: 6
                radius: 3
                color: appModel.connected ? Theme.green : "#888888"
            }
            Rectangle {
                anchors.centerIn: parent
                width: 12
                height: 12
                radius: 6
                color: "transparent"
                border.color: Theme.green
                border.width: 1
                visible: appModel.connected
                opacity: 0
                scale: 0.6
                SequentialAnimation on scale {
                    loops: Animation.Infinite
                    NumberAnimation { from: 0.6; to: 1.9; duration: 2600; easing.type: Easing.OutCubic }
                }
                SequentialAnimation on opacity {
                    loops: Animation.Infinite
                    NumberAnimation { from: 0.7; to: 0; duration: 2600; easing.type: Easing.OutCubic }
                }
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: appModel.connected
                  ? (appModel.uptime !== "" ? "已连接 · " + appModel.uptime : "已连接")
                  : "未连接"
            color: "#DEDEDE"
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }

        Rectangle {
            width: 80
            height: 26
            radius: 4
            color: "#1D1D1D"
            border.color: "#383838"
            border.width: 1
            Text {
                anchors.centerIn: parent
                text: appModel.modeLabel
                color: "#D8D8D8"
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }
        }
    }
}
