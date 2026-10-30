import QtQuick
import "Theme.js" as Theme

Item {
    id: root
    width: 340
    height: 84
    visible: opacity > 0.01
    opacity: 0

    property string kind: "success"
    property string titleText: ""
    property string bodyText: ""

    function colorFor(kind) {
        if (kind === "error") return Theme.error
        if (kind === "warning") return Theme.warn
        return Theme.green
    }

    function show(kind, title, body) {
        root.kind = kind
        root.titleText = title
        root.bodyText = body
        root.opacity = 1
        root.y = 0
        hideTimer.restart()
    }

    Rectangle {
        anchors.fill: parent
        radius: 6
        color: "#1A1A1A"
        border.color: "#3D3D3D"
        border.width: 1
    }

    Rectangle {
        x: 0
        y: 10
        width: 3
        height: parent.height - 20
        radius: 2
        color: root.colorFor(root.kind)
    }

    Text {
        x: 18
        y: 12
        text: root.titleText
        color: "#E8E8E8"
        font.pixelSize: 15
        font.weight: Font.DemiBold
    }

    Text {
        x: 18
        y: 38
        width: parent.width - 34
        text: root.bodyText
        color: "#C0C0C0"
        font.pixelSize: 14
        font.weight: Font.DemiBold
        wrapMode: Text.WordWrap
        lineHeight: 1.25
    }

    Timer {
        id: hideTimer
        interval: 4500
        onTriggered: root.opacity = 0
    }

    Behavior on opacity { NumberAnimation { duration: 180 } }
    Behavior on y { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
}
