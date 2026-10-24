.pragma library

// UI text in English and Vietnamese. t(lang, key, a, b) fills %1 and %2.
var table = {
  en: {
    starting: "Starting…",
    visibleFor: "Everyone can see this device · %1",
    untilOff: "until turned off",
    timeLeft: "%1 left",
    hidden: "Hidden · you can still find others",
    visibleFor_header: "VISIBLE FOR",
    min5: "5 min",
    min10: "10 min",
    min30: "30 min",
    hour1: "1 hour",
    always: "Always",
    hideDevice: "Hide this device",
    showDevice: "Let everyone see this device",
    wantsToSend: "%1 wants to send %2",
    filesCount: "%1 file(s)",
    andMore: "… and %1 more",
    decline: "Decline",
    accept: "Accept",
    searching: "Looking for nearby devices…",
    tapToSend: "Click a device on the radar to send to it",
    openOnPhone: "Open LocalSend on your phone or another computer on the same Wi‑Fi",
    sendTo: "Send to %1",
    file: "Files",
    folder: "Folder",
    clipboard: "Clipboard",
    pickFiles: "Send files to %1",
    pickFolder: "Send a folder to %1",
    waitingFor: "Waiting for %1 to accept…",
    preparing: "Preparing…",
    sendingTo: "Sending to %1",
    receivingFrom: "Receiving from %1",
    cancel: "Cancel",
    sent: "Sent",
    receivedVerb: "Received",
    doneMessage: "%1 message",
    doneFiles: "%1 %2 file(s)",
    failed: "%1 failed",
    declinedBy: "%1 declined",
    youDeclined: "Declined %1",
    cancelled: "Cancelled",
    device: "The device",
    messageCopied: "Message from %1 copied to the clipboard",
    clipboardEmpty: "The clipboard has no text",
    received_header: "RECEIVED",
    openFolder: "Open folder",
    from: "from %1",
    thisDevice: "This device: %1",
    updated: "LocalSend widget updated to the latest version"
  },
  vi: {
    starting: "Đang khởi động…",
    visibleFor: "Mọi người có thể thấy máy này · %1",
    untilOff: "đến khi tắt",
    timeLeft: "còn %1",
    hidden: "Đang ẩn · bạn vẫn tìm được người khác",
    visibleFor_header: "HIỂN THỊ TRONG",
    min5: "5 phút",
    min10: "10 phút",
    min30: "30 phút",
    hour1: "1 giờ",
    always: "Luôn bật",
    hideDevice: "Ẩn máy này",
    showDevice: "Cho mọi người thấy máy này",
    wantsToSend: "%1 muốn gửi %2",
    filesCount: "%1 tệp",
    andMore: "… và %1 tệp khác",
    decline: "Từ chối",
    accept: "Chấp nhận",
    searching: "Đang tìm thiết bị gần đây…",
    tapToSend: "Bấm vào một thiết bị trên radar để gửi",
    openOnPhone: "Mở LocalSend trên điện thoại hoặc máy khác cùng mạng Wi‑Fi",
    sendTo: "Gửi tới %1",
    file: "Tệp",
    folder: "Thư mục",
    clipboard: "Clipboard",
    pickFiles: "Gửi tệp tới %1",
    pickFolder: "Gửi thư mục tới %1",
    waitingFor: "Chờ %1 chấp nhận…",
    preparing: "Đang chuẩn bị…",
    sendingTo: "Đang gửi tới %1",
    receivingFrom: "Đang nhận từ %1",
    cancel: "Huỷ",
    sent: "Gửi",
    receivedVerb: "Nhận",
    doneMessage: "%1 tin nhắn xong",
    doneFiles: "%1 %2 tệp xong",
    failed: "%1 thất bại",
    declinedBy: "%1 đã từ chối",
    youDeclined: "Đã từ chối %1",
    cancelled: "Đã huỷ",
    device: "Thiết bị",
    messageCopied: "Tin nhắn từ %1 đã được chép vào clipboard",
    clipboardEmpty: "Clipboard không có chữ",
    received_header: "ĐÃ NHẬN",
    openFolder: "Mở thư mục",
    from: "từ %1",
    thisDevice: "Tên máy này: %1",
    updated: "Widget LocalSend đã được cập nhật lên bản mới nhất"
  }
}

function t(lang, key, a, b) {
  var s = (table[lang] && table[lang][key]) || table.en[key] || key
  if (a !== undefined) s = s.replace("%1", String(a))
  if (b !== undefined) s = s.replace("%2", String(b))
  return s
}

// "Auto" follows the system locale; anything else picks its language.
function resolve(setting, localeName) {
  var v = String(setting || "Auto")
  if (v === "English") return "en"
  if (v === "Tiếng Việt") return "vi"
  return String(localeName || "").toLowerCase().indexOf("vi") === 0 ? "vi" : "en"
}
