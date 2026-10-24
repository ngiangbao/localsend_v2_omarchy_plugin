import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Strings.js" as Strings

// LocalSend, AirDrop-style: a bar icon, a radar of nearby devices, and a
// receive window that closes on its own. bin/lsd.py does the protocol; this
// file only draws its state and sends it commands (JSON lines on stdin).
Panel {
  id: root
  moduleName: "ngiangbao.localsend"
  ipcTarget: "ngiangbao.localsend"
  manageIpc: false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color accent: Color.accent
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property string lang: Strings.resolve(setting("language", "Auto"), Qt.locale().name)
  function t(key, a, b) { return Strings.t(lang, key, a, b) }
  onLangChanged: command({ cmd: "lang", code: lang })

  readonly property string daemonPath: {
    var url = String(Qt.resolvedUrl("bin/lsd.py"))
    return url.indexOf("file://") === 0 ? url.substring(7) : url
  }

  // ---- daemon state ------------------------------------------------
  property bool ready: false
  property string alias: ""
  property bool receiving: false
  property int until: 0
  property string error: ""
  property string downloadDir: ""
  property var peers: []
  property string selected: ""
  property var request: null
  property var transfer: null
  property var received: []
  property string notice: ""
  property int now: Math.floor(Date.now() / 1000)

  readonly property var selectedPeer: {
    for (var i = 0; i < peers.length; i++)
      if (String(peers[i].fingerprint) === selected) return peers[i]
    return null
  }

  // ---- visibility window ---------------------------------------------
  readonly property var windowOptions: [
    { value: "5", label: t("min5") },
    { value: "10", label: t("min10") },
    { value: "30", label: t("min30") },
    { value: "60", label: t("hour1") },
    { value: "0", label: t("always") }
  ]
  property string windowValue: {
    var m = parseInt(String(setting("windowMinutes", 10)), 10)
    if (!isFinite(m) || m < 0) m = 10
    for (var i = 0; i < windowOptions.length; i++)
      if (windowOptions[i].value === String(m)) return String(m)
    return "10"
  }

  readonly property string countdown: {
    if (!receiving) return ""
    if (until <= 0) return t("untilOff")
    var left = Math.max(0, until - now)
    var m = Math.floor(left / 60)
    var s = left % 60
    return t("timeLeft", m + ":" + (s < 10 ? "0" : "") + s)
  }

  readonly property string statusText: {
    if (error !== "") return error
    if (!ready) return t("starting")
    if (receiving) return t("visibleFor", countdown)
    return t("hidden")
  }

  readonly property color barIconColor: receiving ? barForeground : Qt.darker(barForeground, 1.55)

  function command(obj) {
    if (daemon.running) daemon.write(JSON.stringify(obj) + "\n")
  }

  function startReceiving() {
    command({ cmd: "receive", seconds: parseInt(windowValue, 10) * 60 })
  }

  function toggleReceiving() {
    if (receiving) command({ cmd: "stop" })
    else startReceiving()
  }

  function setWindow(value) {
    windowValue = value
    if (receiving) startReceiving()
  }

  function decide(accept) {
    if (!request) return
    command({ cmd: "decide", id: request.id, accept: accept })
    request = null
  }

  function flash(text) {
    notice = text
    noticeTimer.restart()
  }

  function pick(mode) {
    if (!selectedPeer || picker.running) return
    picker.target = selected
    picker.command = mode === "folder"
      ? ["omarchy-file-select", "--title", t("pickFolder", selectedPeer.alias), "--directory"]
      : ["omarchy-file-select", "--title", t("pickFiles", selectedPeer.alias), "--multiple"]
    picker.running = true
  }

  function sendClipboard() {
    if (!selectedPeer || clip.running) return
    clip.target = selected
    clip.running = true
  }

  // ---- self-update ---------------------------------------------------
  // The plugin is a git checkout; `omarchy plugin update` fast-forwards it,
  // validates it and reloads the shell. Upstream LocalSend changes reach it
  // through this repository (see .github/workflows/upstream.yml). It runs
  // detached because the reload it triggers replaces this widget.
  readonly property bool autoUpdate: String(setting("autoUpdate", true)) !== "false"
  readonly property bool busy: request !== null
                              || (transfer !== null && (transfer.status === "waiting" || transfer.status === "transferring"))

  function checkForUpdate() {
    if (!autoUpdate) return
    if (busy) { updateTimer.interval = 10 * 60 * 1000; updateTimer.restart(); return }
    updateTimer.interval = 6 * 60 * 60 * 1000
    Quickshell.execDetached(["bash", "-c",
      "command -v omarchy-plugin-update >/dev/null || exit 0; "
      + "out=$(omarchy-plugin-update \"$1\" --yes 2>&1) || exit 1; "
      + "case $out in *Updated*) notify-send -a LocalSend -i software-update-available LocalSend \"$2\" ;; esac",
      "lsd-update", moduleName, t("updated")])
  }

  function formatSize(n) {
    n = Number(n || 0)
    if (n < 1024) return n + " B"
    if (n < 1048576) return (n / 1024).toFixed(0) + " KB"
    if (n < 1073741824) return (n / 1048576).toFixed(1) + " MB"
    return (n / 1073741824).toFixed(2) + " GB"
  }

  function handleLine(line) {
    var e
    try { e = JSON.parse(line) } catch (err) { return }
    if (e.ev === "state") {
      ready = true
      alias = e.alias || ""
      receiving = !!e.receiving
      until = e.until || 0
      error = e.error || ""
      downloadDir = e.downloadDir || ""
    } else if (e.ev === "peers") {
      peers = e.peers || []
      if (selected !== "" && !selectedPeer) selected = ""
    } else if (e.ev === "request") {
      request = e
      if (!opened) open()
    } else if (e.ev === "transfer") {
      if (request && request.id === e.id && e.status !== "transferring") request = null
      transfer = e
      if (e.status === "done" || e.status === "failed" || e.status === "declined" || e.status === "cancelled") {
        var verb = e.dir === "in" ? t("receivedVerb") : t("sent")
        var msg = {
          done: e.text ? t("doneMessage", verb) : t("doneFiles", verb, e.count || 1),
          failed: t("failed", verb) + (e.message ? ": " + e.message : ""),
          declined: e.dir === "in" ? t("youDeclined", e.peer || "") : t("declinedBy", e.peer || t("device")),
          cancelled: t("cancelled")
        }[e.status]
        flash(msg)
        transferClear.restart()
      }
    } else if (e.ev === "received") {
      var list = [e].concat(received)
      received = list.slice(0, 6)
    } else if (e.ev === "message") {
      flash(t("messageCopied", e.peer))
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: {
    command({ cmd: "scan", on: opened })
    if (opened) Qt.callLater(function() { keyCatcher.forceActiveFocus() })
    else selected = ""
  }

  Process {
    id: daemon
    command: ["python3", "-u", root.daemonPath, String(root.setting("deviceName", "") || ""), root.lang]
    running: true
    stdinEnabled: true
    stdout: SplitParser { onRead: line => root.handleLine(line) }
    stderr: SplitParser { onRead: line => console.warn("[localsend] " + line) }
    onExited: function(code, status) {
      root.ready = false
      root.receiving = false
      root.peers = []
      restart.start()
    }
  }

  Timer {
    id: restart
    interval: 3000
    onTriggered: daemon.running = true
  }

  Timer {
    interval: 1000
    repeat: true
    running: root.receiving && root.until > 0
    onTriggered: root.now = Math.floor(Date.now() / 1000)
  }

  Timer { id: noticeTimer; interval: 4000; onTriggered: root.notice = "" }
  Timer { id: transferClear; interval: 4000; onTriggered: root.transfer = null }

  Timer {
    id: updateTimer
    interval: 2 * 60 * 1000
    repeat: true
    running: root.autoUpdate
    onTriggered: root.checkForUpdate()
  }

  Process {
    id: picker
    property string target: ""
    stdout: StdioCollector {
      onStreamFinished: {
        var paths = text.split("\n").filter(function(p) { return p.trim() !== "" })
        if (paths.length > 0) root.command({ cmd: "send", fingerprint: picker.target, paths: paths })
      }
    }
  }

  Process {
    id: clip
    property string target: ""
    command: ["wl-paste", "--no-newline", "--type", "text"]
    stdout: StdioCollector {
      onStreamFinished: {
        if (text.length > 0) root.command({ cmd: "sendText", fingerprint: clip.target, text: text })
        else root.flash(root.t("clipboardEmpty"))
      }
    }
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function receive(): string { root.startReceiving(); return "ok" }
    function stop(): string { root.command({ cmd: "stop" }); return "ok" }
    function status(): string { return root.statusText }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    iconComponent: Component {
      Item {
        LsIcon {
          anchors.centerIn: parent
          iconSize: Style.space(13)
          color: root.barIconColor

          SequentialAnimation on opacity {
            running: root.request !== null
            loops: Animation.Infinite
            NumberAnimation { to: 0.35; duration: 600; easing.type: Easing.InOutQuad }
            NumberAnimation { to: 1.0; duration: 600; easing.type: Easing.InOutQuad }
          }
        }
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) root.toggleReceiving()
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(720))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        var k = String(t || "").toLowerCase()
        if (k === "v") root.toggleReceiving()
        else if (k === "f") root.pick("file")
        else if (k === "d") root.pick("folder")
        else if (k === "c") root.sendClipboard()
      }

      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: flick.width
          spacing: Style.space(12)

          PanelHero {
            id: hero
            width: parent.width
            title: "LocalSend"
            meta: root.statusText
            foreground: root.error !== "" ? root.urgent : root.foreground
            fontFamily: root.fontFamily
            iconOpacity: root.receiving ? 1.0 : 0.6
            iconComponent: Component {
              LsIcon {
                iconSize: Style.font.display
                color: root.receiving ? root.accent : root.foreground
              }
            }
            trailingControl: Component {
              ToggleSwitch {
                id: visibleSwitch
                checked: root.receiving
                interactive: root.ready && root.error === ""
                foreground: hero.foreground
                onToggled: root.toggleReceiving()
                PanelToolTip {
                  visible: visibleSwitch.containsMouse
                  text: root.receiving ? root.t("hideDevice") : root.t("showDevice")
                  fontFamily: root.fontFamily
                }
              }
            }
          }

          // ---------- visibility window ----------
          Column {
            width: parent.width
            spacing: Style.space(6)
            PanelSectionHeader { text: root.t("visibleFor_header"); foreground: root.foreground; fontFamily: root.fontFamily }
            ButtonGroup {
              width: parent.width
              options: root.windowOptions
              value: root.windowValue
              foreground: root.foreground
              accent: root.accent
              fontFamily: root.fontFamily
              fontSize: Style.font.bodySmall
              onChanged: function(v) { root.setWindow(v) }
            }
          }

          // ---------- incoming request ----------
          Rectangle {
            visible: root.request !== null
            width: parent.width
            height: requestBody.implicitHeight + Style.space(20)
            radius: Style.space(8)
            color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.12)
            border.width: 1
            border.color: root.accent

            Column {
              id: requestBody
              anchors.fill: parent
              anchors.margins: Style.space(10)
              spacing: Style.space(6)

              Text {
                width: parent.width
                textFormat: Text.PlainText
                wrapMode: Text.WordWrap
                text: root.request ? root.t("wantsToSend", root.request.peer,
                                      root.t("filesCount", root.request.count) + " (" + root.formatSize(root.request.total) + ")") : ""
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
              }

              Repeater {
                model: root.request ? root.request.files.slice(0, 4) : []
                Text {
                  required property var modelData
                  width: requestBody.width
                  textFormat: Text.PlainText
                  elide: Text.ElideMiddle
                  text: "• " + modelData.name + "  " + root.formatSize(modelData.size)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              Text {
                visible: root.request && root.request.count > 4
                textFormat: Text.PlainText
                text: root.request ? root.t("andMore", root.request.count - 4) : ""
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              Row {
                anchors.right: parent.right
                spacing: Style.space(8)
                Button {
                  text: root.t("decline")
                  bordered: true
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  onClicked: root.decide(false)
                }
                Button {
                  text: root.t("accept")
                  bordered: true
                  selected: true
                  foreground: root.foreground
                  accent: root.accent
                  fontFamily: root.fontFamily
                  onClicked: root.decide(true)
                }
              }
            }
          }

          // ---------- radar ----------
          Radar {
            width: parent.width
            height: Math.min(parent.width, Style.space(270))
            peers: root.peers
            selected: root.selected
            receiving: root.receiving
            active: root.opened
            foreground: root.foreground
            accent: root.accent
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            emptyText: root.t("searching")
            onPeerClicked: function(fp) { root.selected = root.selected === fp ? "" : fp }
          }

          // ---------- send actions ----------
          Text {
            visible: root.selectedPeer === null
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.peers.length > 0 ? root.t("tapToSend") : root.t("openOnPhone")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Column {
            visible: root.selectedPeer !== null
            width: parent.width
            spacing: Style.space(6)

            Text {
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              textFormat: Text.PlainText
              elide: Text.ElideRight
              text: root.selectedPeer ? root.t("sendTo", root.selectedPeer.alias)
                                        + (root.selectedPeer.deviceModel ? " · " + root.selectedPeer.deviceModel : "") : ""
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              font.bold: true
            }

            Row {
              anchors.horizontalCenter: parent.horizontalCenter
              spacing: Style.space(8)
              Button { text: root.t("file"); bordered: true; foreground: root.foreground; fontFamily: root.fontFamily; onClicked: root.pick("file") }
              Button { text: root.t("folder"); bordered: true; foreground: root.foreground; fontFamily: root.fontFamily; onClicked: root.pick("folder") }
              Button { text: root.t("clipboard"); bordered: true; foreground: root.foreground; fontFamily: root.fontFamily; onClicked: root.sendClipboard() }
            }
          }

          // ---------- progress / notices ----------
          Column {
            visible: root.transfer !== null && (root.transfer.status === "waiting" || root.transfer.status === "transferring")
            width: parent.width
            spacing: Style.space(4)

            Text {
              width: parent.width
              textFormat: Text.PlainText
              elide: Text.ElideRight
              text: {
                var t = root.transfer
                if (!t) return ""
                if (t.status === "waiting") return t.dir === "out" ? root.t("waitingFor", t.peer) : root.t("preparing")
                var pct = t.total > 0 ? Math.floor(t.done * 100 / t.total) : 0
                return root.t(t.dir === "out" ? "sendingTo" : "receivingFrom", t.peer) + " · " + pct + "% · "
                       + root.formatSize(t.done) + " / " + root.formatSize(t.total)
              }
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            Rectangle {
              width: parent.width
              height: Style.space(5)
              radius: height / 2
              color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.15)
              Rectangle {
                height: parent.height
                radius: parent.radius
                color: root.accent
                width: root.transfer && root.transfer.total > 0
                       ? parent.width * Math.min(1, root.transfer.done / root.transfer.total) : 0
                Behavior on width { NumberAnimation { duration: 180 } }
              }
            }

            Button {
              visible: root.transfer !== null && root.transfer.dir === "out"
              anchors.right: parent.right
              text: root.t("cancel")
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.command({ cmd: "cancel", id: root.transfer.id })
            }
          }

          Text {
            visible: root.notice !== ""
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.notice
            color: root.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          // ---------- received ----------
          PanelSeparator { foreground: root.foreground; visible: root.received.length > 0 }

          Column {
            visible: root.received.length > 0
            width: parent.width
            spacing: Style.space(4)

            RowLayout {
              width: parent.width
              PanelSectionHeader {
                Layout.fillWidth: true
                text: root.t("received_header")
                foreground: root.foreground
                fontFamily: root.fontFamily
              }
              Button {
                text: root.t("openFolder")
                foreground: root.foreground
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                onClicked: Quickshell.execDetached(["xdg-open", root.downloadDir])
              }
            }

            Repeater {
              model: root.received
              CursorSurface {
                id: row
                required property var modelData
                width: parent.width
                foreground: root.foreground
                hasCursor: rowMouse.containsMouse
                implicitHeight: rowText.implicitHeight + Style.space(10)

                MouseArea {
                  id: rowMouse
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: Quickshell.execDetached(["xdg-open", row.modelData.path])
                }

                Column {
                  id: rowText
                  anchors.left: parent.left
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.leftMargin: Style.space(8)
                  anchors.rightMargin: Style.space(8)
                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    elide: Text.ElideMiddle
                    text: row.modelData.name
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.bodySmall
                  }
                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    text: root.t("from", row.modelData.peer) + " · " + root.formatSize(row.modelData.size)
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }
              }
            }
          }

          Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            textFormat: Text.PlainText
            text: root.alias !== "" ? root.t("thisDevice", root.alias) : ""
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }
}
