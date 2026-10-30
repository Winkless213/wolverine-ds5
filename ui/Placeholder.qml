import QtQuick

QtObject {
    property string statusTitle: "正在检测手柄"
    property string statusDetail: ""
    property string statusColor: "#E8B454"
    property string actionText: "启动桥接"
    property bool actionEnabled: false
    property string modeLabel: "未检测"
    property bool connected: false
    property real leftLevel: 0
    property real rightLevel: 0
    property bool testable: false
    property string testing: ""
    property string ds5State: "检查中"
    property string ds5Detail: "usbip · 127.0.0.1:3240"
    property string sensaState: "未检测"
    property string hideWarning: ""
    property bool gripEnabled: true
    property int gripGainPercent: 100
    property bool gripReady: true
    property bool reduceMotion: false
    property bool audioGuard: true
    property bool hidePhysical: false
    property bool autostart: false
    property string version: "1.1.27"
    property string logDirectory: ""
    property bool trayAvailable: false
    property string uptime: ""
}
