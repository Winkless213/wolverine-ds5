import QtQuick
import "Theme.js" as Theme

Item {
    id: root
    property bool value: false
    signal toggled(bool checked)

    implicitWidth: 40
    implicitHeight: 22

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: root.value ? Theme.green : "#3F3F3F"
        Behavior on color { ColorAnimation { duration: 160 } }
    }

    Rectangle {
        width: 16
        height: 16
        radius: 8
        y: 3
        x: root.value ? 21 : 3
        color: root.value ? "#FFFFFF" : "#CCCCCC"
        Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: 160 } }
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.enabled
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.toggled(!root.value)
    }
}
