import QtQuick

Item {
    id: root
    implicitHeight: 300

    readonly property real padWidth: Math.min(width * 0.55, height * 1.466)
    readonly property real padHeight: padWidth / 1.466

    Image {
        objectName: "padImage"
        width: root.padWidth
        height: root.padHeight
        anchors.centerIn: parent
        source: "assets/wolverine-v3-pro.png"
        fillMode: Image.PreserveAspectFit
        asynchronous: false
    }
}
