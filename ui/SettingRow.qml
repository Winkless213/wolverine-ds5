import QtQuick
import "Theme.js" as Theme

Item {
    id: root
    property string title: ""
    property string desc: ""
    property bool divider: true
    property bool selected: false
    default property alias control: holder.data

    Rectangle {
        visible: root.selected
        x: -10
        width: 3
        height: Math.max(18, parent.height - 14)
        radius: 1.5
        color: Theme.green
        anchors.verticalCenter: parent.verticalCenter
    }

    implicitHeight: 76

    Column {
        anchors.left: parent.left
        anchors.right: holder.left
        anchors.rightMargin: 20
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4

        Text {
            width: parent.width
            text: root.title
            color: root.selected ? "#F0F0F0" : "#D8D8D8"
            font.pixelSize: 16
            font.weight: Font.DemiBold
        }
        Text {
            width: parent.width
            visible: root.desc !== ""
            text: root.desc
            color: "#B8B8B8"
            font.pixelSize: 14
            font.weight: Font.DemiBold
            wrapMode: Text.WordWrap
            lineHeight: 1.3
        }
    }

    Item {
        id: holder
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: childrenRect.width
        height: childrenRect.height
    }

    Rectangle {
        visible: root.divider
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Theme.line
    }
}
