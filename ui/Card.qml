import QtQuick
import QtQuick.Layouts
import "Theme.js" as Theme

Rectangle {
    id: root
    property string title: ""
    default property alias content: body.data

    color: Theme.card
    border.color: Theme.line
    border.width: 1
    radius: 6
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 27
            spacing: 8

            Rectangle {
                Layout.preferredWidth: 3
                Layout.preferredHeight: 13
                radius: 2
                color: Theme.green
            }
            Text {
                text: root.title
                color: Theme.green
                font.pixelSize: 18
                font.weight: Font.Bold
            }
            Item { Layout.fillWidth: true }
        }

        Item {
            id: body
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
}
