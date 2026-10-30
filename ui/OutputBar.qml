import QtQuick
import "Theme.js" as Theme

Item {
    id: root
    property string label: ""
    property real value: 0

    implicitWidth: 56
    implicitHeight: 360

    readonly property real ratio: Math.max(0, Math.min(1, value))
    readonly property real barHeight: Math.max(40, height - 78)

    Rectangle {
        id: track
        width: root.width
        height: root.barHeight
        radius: 3
        color: "#3B3B3B"
    }

    Rectangle {
        width: root.width
        height: track.height * root.ratio
        radius: 3
        anchors.bottom: track.bottom
        color: Theme.greenLevel
        Behavior on height { NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }
    }

    Text {
        y: track.height + 8
        width: root.width
        text: Math.round(root.value * 100)
        color: "#E4E4E4"
        font.pixelSize: 30
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
    }

    Text {
        y: track.height + 46
        width: root.width
        text: root.label
        color: "#D0D0D0"
        font.pixelSize: 14
        horizontalAlignment: Text.AlignHCenter
    }
}
