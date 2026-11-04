import QtQuick
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: root
    objectName: "statusPage"
    property var appModel: Placeholder {}

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 250
            Layout.minimumHeight: 220

            ControllerHero {
                id: hero
                anchors.fill: parent
            }

            Column {
                x: 0
                y: 2
                width: Math.max(180, Math.min(280, (parent.width - hero.padWidth) / 2 - 30))
                spacing: 5

                Text {
                    text: appModel.statusTitle
                    color: appModel.statusColor
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width
                    text: appModel.statusDetail
                    visible: text !== ""
                    color: "#D0D0D0"
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                    lineHeight: 1.35
                }

                Rectangle {
                    width: 118
                    height: 30
                    radius: 4
                    color: "#1D1D1D"
                    border.color: Theme.green
                    border.width: 1
                    opacity: appModel.actionEnabled ? 1 : 0.4
                    // Xbox 模式下来回重复同一句提示，按钮也点不了；文案与标题相同时只留标题。
                    visible: appModel.actionText !== appModel.statusTitle

                    Text {
                        anchors.centerIn: parent
                        text: appModel.actionText
                        color: Theme.green
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }

                    MouseArea {
                        id: actionMouse
                        anchors.fill: parent
                        enabled: appModel.actionEnabled
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: appModel.toggleBridge()
                    }
                }

                // 未就绪时把第一条失败和修复入口放在首屏；就绪后整段隐藏，不占地方。
                Text {
                    width: parent.width
                    visible: !appModel.readinessReady
                    text: appModel.readinessSummary
                    color: appModel.readinessColor
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                    lineHeight: 1.3
                }
                Text {
                    width: parent.width
                    visible: !appModel.readinessReady && appModel.readinessDetail !== ""
                    text: appModel.readinessDetail
                    color: "#9C9C9C"
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                    lineHeight: 1.3
                    maximumLineCount: 3
                    elide: Text.ElideRight
                }
                Rectangle {
                    width: 104
                    height: 24
                    radius: 4
                    color: "#1D1D1D"
                    border.color: Theme.warn
                    border.width: 1
                    visible: !appModel.readinessReady && appModel.readinessFixText !== ""
                    Text {
                        anchors.centerIn: parent
                        text: appModel.readinessFixText
                        color: Theme.warn
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: appModel.requestFix()
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 40
            radius: 5
            color: "#191919"
            border.color: "#2E2E2E"
            border.width: 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                spacing: 20

                Row {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 8
                    Rectangle { width: 6; height: 6; radius: 3; color: appModel.ds5Color; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: "虚拟 DualSense"
                        color: "#D0D0D0"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: appModel.ds5State
                        color: "#E8E8E8"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Row {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 8
                    Rectangle { width: 6; height: 6; radius: 3; color: appModel.sensaColor; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: "雷蛇 Sensa"
                        color: "#D0D0D0"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: appModel.sensaState
                        color: "#E8E8E8"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Rectangle {
                        visible: appModel.synapseStartable
                        width: 78
                        height: 22
                        radius: 4
                        color: "#1D1D1D"
                        border.color: Theme.green
                        border.width: 1
                        anchors.verticalCenter: parent.verticalCenter

                        Text {
                            anchors.centerIn: parent
                            text: "启动雷云"
                            color: Theme.green
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: appModel.requestSynapse()
                        }
                    }
                }

                Row {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 8
                    Rectangle { width: 6; height: 6; radius: 3; color: appModel.gameColor; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: "游戏触觉"
                        color: "#D0D0D0"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: appModel.audioState
                        color: "#E8E8E8"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                Row {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 8
                    Rectangle { width: 6; height: 6; radius: 3; color: appModel.hideColor; anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        text: "HidHide"
                        color: "#D0D0D0"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: appModel.hideStateText
                        color: "#E8E8E8"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 12

            Card {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: "握把震动"

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    SettingRow {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        title: "握把震动"
                        Toggle {
                            value: appModel.gripEnabled
                            onToggled: {
                                appModel.setGripEnabled(checked)
                                if (!checked && appModel.testing === "grip") appModel.requestTest()
                            }
                        }
                    }

                    SettingRow {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        title: "握把强度"
                        enabled: appModel.gripEnabled
                        opacity: appModel.gripEnabled ? 1 : 0.45
                        Row {
                            spacing: 10
                            GainSlider {
                                width: 230
                                maximum: 150
                                value: appModel.gripGainPercent
                                enabled: appModel.gripEnabled
                                onMoved: appModel.setGripGain(value)
                            }
                            Rectangle {
                                width: 36
                                height: 22
                                radius: 3
                                color: appModel.gripEnabled ? Theme.green : "#3F3F3F"
                                Text {
                                    anchors.centerIn: parent
                                    text: appModel.gripGainPercent
                                    color: appModel.gripEnabled ? "#0A0A0A" : "#9A9A9A"
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                }
                            }
                        }
                    }

                    SettingRow {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        title: "触觉配置文件"
                        enabled: appModel.gripEnabled
                        opacity: appModel.gripEnabled ? 1 : 0.45
                        Row {
                            spacing: 5
                            Repeater {
                                model: [["legacy", "旧版"], ["controlled", "受控"],
                                        ["balanced", "平衡"], ["balanced_plus", "平衡+"],
                                        ["dynamic", "动态"], ["full", "打击"]]
                                delegate: Rectangle {
                                    width: 46
                                    height: 26
                                    radius: 4
                                    color: appModel.hapticProfile === modelData[0] ? Theme.green : "#1D1D1D"
                                    border.width: 1
                                    border.color: appModel.hapticProfile === modelData[0] ? Theme.green : "#3F3F3F"
                                    Text {
                                        anchors.centerIn: parent
                                        text: modelData[1]
                                        color: appModel.hapticProfile === modelData[0] ? "#0A0A0A" : "#D8D8D8"
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        enabled: appModel.gripEnabled
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: appModel.setHapticProfile(modelData[0])
                                    }
                                }
                            }
                        }
                    }

                    SettingRow {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        title: "打击加重"
                        desc: "关闭即加重前的手感"
                        enabled: appModel.gripEnabled
                        opacity: appModel.gripEnabled ? 1 : 0.45
                        Toggle {
                            value: appModel.hapticTransient
                            enabled: appModel.gripEnabled
                            onToggled: appModel.setHapticTransient(checked)
                        }
                    }

                    Item { Layout.fillHeight: true }

                    SettingRow {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        title: "震动测试"
                        desc: appModel.gripReady ? "" : "雷云还没识别到握把，此时测试不会有输出"
                        divider: false
                        enabled: appModel.gripEnabled
                        opacity: appModel.gripEnabled ? 1 : 0.45
                        Row {
                            spacing: 8
                            Rectangle {
                                width: 168
                                height: 30
                                radius: 4
                                color: appModel.testing === "grip" ? Theme.green : "#1D1D1D"
                                border.color: appModel.gripReady ? Theme.green : "#5A5A5A"
                                border.width: 1
                                opacity: (appModel.testable && appModel.gripEnabled && appModel.gripReady) ? 1 : 0.45

                                Text {
                                    anchors.centerIn: parent
                                    text: !appModel.gripReady ? "等待雷云…"
                                          : (appModel.testing === "grip" ? "结束测试" : "按住 LT / RT 测试")
                                    color: !appModel.gripReady ? "#9A9A9A"
                                           : (appModel.testing === "grip" ? "#0A0A0A" : Theme.green)
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }

                                MouseArea {
                                    id: testMouse
                                    anchors.fill: parent
                                    enabled: appModel.testable && appModel.gripEnabled && appModel.gripReady
                                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onClicked: appModel.requestTest()
                                }
                            }

                            Rectangle {
                                width: 128
                                height: 30
                                radius: 4
                                color: "#1D1D1D"
                                border.color: appModel.gripReady ? Theme.warn : "#5A5A5A"
                                border.width: 1
                                opacity: (appModel.testable && appModel.gripEnabled && appModel.gripReady) ? 1 : 0.45

                                Text {
                                    anchors.centerIn: parent
                                    text: "全链路测试"
                                    color: appModel.gripReady ? Theme.warn : "#9A9A9A"
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    enabled: appModel.testable && appModel.gripEnabled && appModel.gripReady
                                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onClicked: appModel.requestChainTest()
                                }
                            }
                        }
                    }
                }
            }

            Card {
                Layout.preferredWidth: 400
                Layout.minimumWidth: 330
                Layout.maximumWidth: 440
                Layout.fillHeight: true
                title: "实时输出（估算）"

                Item {
                    anchors.fill: parent

                    Row {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 84
                        height: parent.height - 8

                        OutputBar {
                            height: parent.height
                            label: "左握把"
                            value: appModel.leftLevel
                        }
                        OutputBar {
                            height: parent.height
                            label: "右握把"
                            value: appModel.rightLevel
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 16
            spacing: 8

            Rectangle {
                width: 5
                height: 5
                radius: 2.5
                color: appModel.readinessColor
                Layout.alignment: Qt.AlignVCenter
            }
            Text {
                text: appModel.readinessSummary
                color: appModel.readinessColor
                font.pixelSize: 12
                font.letterSpacing: 1.4
                Layout.alignment: Qt.AlignVCenter
            }
            Item { Layout.fillWidth: true }
            // 有新版本时在版本号左边挂一条，点了去发布页；不自动更新。
            Text {
                visible: appModel.updateAvailable
                text: "发现新版 " + appModel.updateVersion
                color: Theme.green
                font.pixelSize: 12
                font.letterSpacing: 1.2
                Layout.alignment: Qt.AlignVCenter
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: appModel.openUpdate()
                }
            }
            Text {
                text: "Wolverine to DS5 · " + appModel.version + " · " + appModel.modeLabel
                color: "#A8A8A8"
                font.pixelSize: 12
                font.letterSpacing: 1.2
                Layout.alignment: Qt.AlignVCenter
            }
        }
    }
}
