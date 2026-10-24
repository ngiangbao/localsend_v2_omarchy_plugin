import QtQuick

// The radar: this device in the middle, every LocalSend peer heard in the
// last half minute around it. A peer keeps its bearing (hashed from its
// fingerprint) so the picture doesn't reshuffle on every refresh.
Item {
  id: root

  property var peers: []
  property string selected: ""
  property bool receiving: false
  property bool active: true          // animate only while the panel is open
  property color foreground: "white"
  property color accent: "white"
  property string fontFamily: ""
  property real fontSize: 12
  property string emptyText: "Looking for nearby devices…"

  signal peerClicked(string fingerprint)

  readonly property real radius: Math.min(width, height) / 2 - 4
  readonly property real cx: width / 2
  readonly property real cy: height / 2

  function hash(s) {
    var h = 2166136261
    for (var i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i)
      h = (h * 16777619) >>> 0
    }
    return h
  }

  function placement(peer, index, count) {
    var h = hash(String(peer.fingerprint || peer.alias || index))
    // Spread evenly, then nudge by the hash so two peers rarely line up.
    var angle = (index / Math.max(1, count)) * Math.PI * 2 + (h % 628) / 100 * 0.35 - Math.PI / 2
    var ring = count <= 3 ? 0.68 : ((h >> 10) % 2 ? 0.86 : 0.58)
    return { x: cx + Math.cos(angle) * radius * ring, y: cy + Math.sin(angle) * radius * ring }
  }

  function initials(name) {
    var parts = String(name || "?").trim().split(/[\s_\-.]+/).filter(function(p) { return p.length > 0 })
    if (parts.length === 0) return "?"
    if (parts.length === 1) return parts[0].substring(0, 2).toUpperCase()
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }

  // Rings and cross-hairs.
  Canvas {
    id: grid
    anchors.fill: parent
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    Connections {
      target: root
      function onForegroundChanged() { grid.requestPaint() }
    }
    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      ctx.strokeStyle = Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.16)
      ctx.lineWidth = 1
      for (var i = 1; i <= 3; i++) {
        ctx.beginPath()
        ctx.arc(root.cx, root.cy, root.radius * i / 3, 0, Math.PI * 2)
        ctx.stroke()
      }
      ctx.strokeStyle = Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.07)
      ctx.beginPath()
      ctx.moveTo(root.cx - root.radius, root.cy); ctx.lineTo(root.cx + root.radius, root.cy)
      ctx.moveTo(root.cx, root.cy - root.radius); ctx.lineTo(root.cx, root.cy + root.radius)
      ctx.stroke()
    }
  }

  // The sweep: a fading wedge that turns once every three seconds.
  Item {
    id: sweep
    anchors.fill: parent
    visible: root.active

    Canvas {
      id: wedge
      anchors.fill: parent
      onWidthChanged: requestPaint()
      Connections {
        target: root
        function onAccentChanged() { wedge.requestPaint() }
      }
      onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var g = ctx.createConicalGradient(root.cx, root.cy, 0)
        var c = root.accent
        g.addColorStop(0.0, Qt.rgba(c.r, c.g, c.b, 0.42))
        g.addColorStop(0.12, Qt.rgba(c.r, c.g, c.b, 0.0))
        g.addColorStop(1.0, Qt.rgba(c.r, c.g, c.b, 0.0))
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.moveTo(root.cx, root.cy)
        ctx.arc(root.cx, root.cy, root.radius, 0, Math.PI * 2)
        ctx.closePath()
        ctx.fill()
        ctx.strokeStyle = Qt.rgba(c.r, c.g, c.b, 0.65)
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.moveTo(root.cx, root.cy)
        ctx.lineTo(root.cx + root.radius, root.cy)
        ctx.stroke()
      }
    }

    RotationAnimation on rotation {
      running: root.active
      from: 0
      to: -360
      duration: 3000
      loops: Animation.Infinite
    }
  }

  // Waves leaving this device while it is visible.
  Repeater {
    model: 2
    Rectangle {
      id: wave
      required property int index
      width: root.radius * 2 * scaleFactor
      height: width
      radius: width / 2
      x: root.cx - width / 2
      y: root.cy - height / 2
      color: "transparent"
      border.width: 1.5
      border.color: root.accent
      property real scaleFactor: 0.2
      opacity: 0
      visible: root.receiving && root.active

      SequentialAnimation {
        running: root.receiving && root.active
        loops: Animation.Infinite
        PauseAnimation { duration: wave.index * 1200 }
        ParallelAnimation {
          NumberAnimation { target: wave; property: "scaleFactor"; from: 0.2; to: 1.0; duration: 2400; easing.type: Easing.OutCubic }
          NumberAnimation { target: wave; property: "opacity"; from: 0.7; to: 0.0; duration: 2400; easing.type: Easing.OutCubic }
        }
      }
    }
  }

  // This device.
  Rectangle {
    id: me
    width: Math.round(root.radius * 0.42)
    height: width
    radius: width / 2
    x: root.cx - width / 2
    y: root.cy - height / 2
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.08)
    border.width: 1.5
    border.color: root.receiving ? root.accent : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.35)

    LsIcon {
      anchors.centerIn: parent
      iconSize: parent.width * 0.62
      color: root.receiving ? root.accent : root.foreground
    }
  }

  // Peers.
  Repeater {
    model: root.peers
    delegate: Item {
      id: peerItem
      required property var modelData
      required property int index
      readonly property var pos: root.placement(modelData, index, root.peers.length)
      readonly property bool isSelected: root.selected === String(modelData.fingerprint)
      readonly property real dot: Math.round(root.radius * 0.34)

      width: Math.max(dot, label.implicitWidth)
      height: dot + label.implicitHeight + 2
      x: pos.x - width / 2
      y: pos.y - dot / 2
      scale: 0.4
      opacity: 0
      Component.onCompleted: { scale = 1; opacity = 1 }
      Behavior on scale { NumberAnimation { duration: 380; easing.type: Easing.OutBack } }
      Behavior on opacity { NumberAnimation { duration: 260 } }
      Behavior on x { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
      Behavior on y { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }

      Rectangle {
        id: avatar
        anchors.horizontalCenter: parent.horizontalCenter
        width: peerItem.dot
        height: width
        radius: width / 2
        color: peerItem.isSelected || mouse.containsMouse ? root.accent
                                                           : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.14)
        border.width: 1.5
        border.color: peerItem.isSelected ? root.foreground : Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.8)
        Behavior on color { ColorAnimation { duration: 140 } }

        Text {
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: root.initials(peerItem.modelData.alias)
          color: peerItem.isSelected || mouse.containsMouse ? "black" : root.foreground
          font.family: root.fontFamily
          font.pixelSize: root.fontSize
          font.bold: true
        }
      }

      Text {
        id: label
        anchors.top: avatar.bottom
        anchors.topMargin: 2
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.min(implicitWidth, root.radius * 0.9)
        horizontalAlignment: Text.AlignHCenter
        textFormat: Text.PlainText
        text: String(peerItem.modelData.alias || "")
        elide: Text.ElideRight
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: root.fontSize * 0.85
      }

      MouseArea {
        id: mouse
        anchors.fill: avatar
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.peerClicked(String(peerItem.modelData.fingerprint))
      }
    }
  }

  Text {
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    visible: root.peers.length === 0
    textFormat: Text.PlainText
    text: root.emptyText
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.55)
    font.family: root.fontFamily
    font.pixelSize: root.fontSize * 0.9
  }
}
