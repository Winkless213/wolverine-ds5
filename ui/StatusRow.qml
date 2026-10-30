import QtQuick
import "Theme.js" as Theme

Item {
    id: root
    property string name: ""
    property string value: ""
    property bool divider: true
    implicitHeight: 48

    Rectangle {
        x: 2
        width: 6
        height: 6
        radius: 3
        anchors.verticalCenter: parent.verticalCenter
        color: Theme.green
    }

    Text {
        x: 18
        anchors.verticalCenter: parent.verticalCenter
        text: root.name
        color: "#E4E4E4"
        font.pixelSize: 13
    }

    Text {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: root.value
        color: "#C8C8C8"
        font.pixelSize: 12
    }

    Rectangle {
        visible: root.divider
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.line
    }
}
