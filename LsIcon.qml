import QtQuick

// The LocalSend mark, drawn rather than loaded so it takes the bar's colour:
// a solid disc inside a ring broken into eight arcs.
Canvas {
  id: root

  property color color: "white"
  property real iconSize: 18

  implicitWidth: iconSize
  implicitHeight: iconSize

  onColorChanged: requestPaint()
  onWidthChanged: requestPaint()
  onHeightChanged: requestPaint()

  onPaint: {
    var ctx = getContext("2d")
    var s = Math.min(width, height)
    var cx = width / 2
    var cy = height / 2
    ctx.reset()
    ctx.fillStyle = root.color
    ctx.strokeStyle = root.color

    ctx.beginPath()
    ctx.arc(cx, cy, s * 0.205, 0, Math.PI * 2)
    ctx.fill()

    ctx.lineWidth = s * 0.075
    ctx.lineCap = "round"
    var r = s * 0.385
    var step = Math.PI * 2 / 8
    var arc = step * 0.52
    for (var i = 0; i < 8; i++) {
      var a = -Math.PI / 2 - step / 2 + i * step + (step - arc) / 2
      ctx.beginPath()
      ctx.arc(cx, cy, r, a, a + arc)
      ctx.stroke()
    }
  }
}
