import QtQuick
import QtQuick.Layouts
import "Theme.js" as Theme

Item {
    id: root
    objectName: "systemPage"
    property var appModel: Placeholder {}

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        Card {
            Layout.fillWidth: true
            Layout.fillHeight: true
            title: "系统"

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                SettingRow {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    title: "开机自启"
                    desc: "登录后在托盘静默启动"
                    Toggle {
                        value: appModel.autostart
                        onToggled: appModel.setAutostart(checked)
                    }
                }

                SettingRow {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    title: "默认音频自动切回"
                    desc: "虚拟设备抢占默认音频时自动切回"
                    Toggle {
                        value: appModel.audioGuard
                        onToggled: appModel.setAudioGuard(checked)
                    }
                }

                SettingRow {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    title: "对游戏隐藏实体手柄"
                    desc: appModel.hideWarning !== "" ? appModel.hideWarning
                                                     : "退出时自动恢复；需要 HidHide"
                    Toggle {
                        value: appModel.hidePhysical
                        onToggled: appModel.setHidePhysical(checked)
                    }
                }

                SettingRow {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    title: "日志"
                    desc: appModel.logDirectory
                    divider: false
                    Row {
                        spacing: 8

                        Rectangle {
                            width: 88
                            height: 30
                            radius: 4
                            color: "#1D1D1D"
                            border.color: "#444444"
                            border.width: 1
                            Text {
                                anchors.centerIn: parent
                                text: "打开目录"
                                color: "#D0D0D0"
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: appModel.openLogs()
                            }
                        }

                        Rectangle {
                            width: 92
                            height: 30
                            radius: 4
                            color: "#1D1D1D"
                            border.color: Theme.green
                            border.width: 1
                            Text {
                                anchors.centerIn: parent
                                text: "导出日志"
                                color: Theme.green
                                font.pixelSize: 14
                                font.weight: Font.DemiBold
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: appModel.exportLogs()
                            }
                        }
                    }
                }

            }
        }

    }
}
