import QtQuick
import QtQuick.Window
import "Theme.js" as Theme

Item {
    id: root
    height: 42

    Rectangle {
        anchors.fill: parent
        color: Theme.bar
        border.color: "#2A2A2A"
        border.width: 1
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onPressed: Window.window.startSystemMove()
        onDoubleClicked: {
            if (Window.window.visibility === Window.Maximized)
                Window.window.showNormal()
            else
                Window.window.showMaximized()
        }
    }

    Image {
        x: 10
        anchors.verticalCenter: parent.verticalCenter
        width: 26
        height: 20
        source: "assets/brand-gamepad.png"
        fillMode: Image.PreserveAspectFit
        smooth: true
    }

    Text {
        x: 44
        anchors.verticalCenter: parent.verticalCenter
        text: "Wolverine <font color='#A0A0A0'>to</font> DS5"
        textFormat: Text.RichText
        color: "#DEDEDE"
        font.pixelSize: 15
        font.weight: Font.DemiBold
        font.letterSpacing: 0.4
    }

    Item { anchors.fill: parent }

    Row {
        anchors.right: parent.right
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 18

        Item {
            width: 18
            height: 42
            Rectangle {
                anchors.centerIn: parent
                width: 10
                height: 1
                color: "#8A8A8A"
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: Window.window.showMinimized()
            }
        }

        Item {
            width: 18
            height: 42
            Rectangle {
                anchors.centerIn: parent
                width: 9
                height: 9
                color: "transparent"
                border.color: "#8A8A8A"
                border.width: 1
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (Window.window.visibility === Window.Maximized)
                        Window.window.showNormal()
                    else
                        Window.window.showMaximized()
                }
            }
        }

        Item {
            width: 18
            height: 42
            Rectangle {
                anchors.centerIn: parent
                width: 10
                height: 1
                color: "#8A8A8A"
                rotation: 45
            }
            Rectangle {
                anchors.centerIn: parent
                width: 10
                height: 1
                color: "#8A8A8A"
                rotation: -45
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: Window.window.close()
            }
        }
    }
}
