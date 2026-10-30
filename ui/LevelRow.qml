import QtQuick
import "Theme.js" as Theme

Item {
    id: root
    property string label: ""
    property real value: 0

    implicitHeight: 43
    height: implicitHeight

    readonly property real ratio: Math.max(0, Math.min(1, value))
    readonly property real trackX: 70
    readonly property real trackWidth: Math.max(20, width - trackX - 72)

    Text {
        x: 0
        width: root.trackX - 10
        anchors.verticalCenter: parent.verticalCenter
        text: root.label
        color: "#E4E4E4"
        font.pixelSize: 14
        elide: Text.ElideRight
    }

    Rectangle {
        id: track
        x: root.trackX
        width: root.trackWidth
        height: 6
        radius: 3
        anchors.verticalCenter: parent.verticalCenter
        color: "#3B3B3B"
    }

    Rectangle {
        width: root.trackWidth * root.ratio
        height: 6
        radius: 3
        anchors.verticalCenter: parent.verticalCenter
        x: root.trackX
        color: Theme.green
        Behavior on width { NumberAnimation { duration: 80; easing.type: Easing.OutCubic } }
    }

    Rectangle {
        visible: root.ratio > 0
        x: root.trackX + root.trackWidth * root.ratio - 2.5
        width: 5
        height: 5
        radius: 2.5
        anchors.verticalCenter: parent.verticalCenter
        color: "#B6FF9E"
    }

    Row {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 1
        Text {
            text: Math.round(root.value * 100)
            color: "#EAEAEA"
            font.pixelSize: 22
            font.weight: Font.DemiBold
        }
        Text {
            text: "%"
            color: Theme.muted
            font.pixelSize: 11
            anchors.baseline: parent.children[0].baseline
        }
    }
}
