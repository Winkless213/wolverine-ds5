import QtQuick
import "Theme.js" as Theme

Item {
    id: root
    property int value: 0
    property int maximum: 150
    signal moved(int value)

    implicitWidth: 250
    implicitHeight: 24

    readonly property real ratio: Math.max(0, Math.min(1, value / Math.max(1, maximum)))
    readonly property real usable: width - 14

    Rectangle {
        id: track
        x: 7
        width: root.usable
        height: 4
        radius: 2
        anchors.verticalCenter: parent.verticalCenter
        color: "#3F3F3F"
    }

    Rectangle {
        x: 7
        width: root.usable * root.ratio
        height: 4
        radius: 2
        anchors.verticalCenter: parent.verticalCenter
        color: root.enabled ? Theme.green : "#4A4A4A"
    }

    Rectangle {
        id: thumb
        x: 7 + root.usable * root.ratio - width / 2
        width: 14
        height: 14
        radius: 7
        anchors.verticalCenter: parent.verticalCenter
        color: root.enabled ? Theme.green : "#5A5A5A"
    }

    Rectangle {
        anchors.centerIn: thumb
        width: 22
        height: 22
        radius: 11
        color: "transparent"
        border.color: "#66D62C"
        border.width: 1
        visible: root.enabled
        opacity: 0
        scale: 0.7
        SequentialAnimation on scale {
            loops: Animation.Infinite
            NumberAnimation { from: 0.65; to: 1.55; duration: 2800; easing.type: Easing.OutCubic }
        }
        SequentialAnimation on opacity {
            loops: Animation.Infinite
            NumberAnimation { from: 0.75; to: 0; duration: 2800; easing.type: Easing.OutCubic }
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.enabled
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        function apply(x) {
            var next = Math.round(Math.max(0, Math.min(1, (x - 7) / root.usable)) * root.maximum)
            root.moved(next)
        }
        onPressed: apply(mouse.x)
        onPositionChanged: if (pressed) apply(mouse.x)
    }
}
