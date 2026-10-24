# LocalSend for Omarchy

An AirDrop-style [LocalSend](https://localsend.org) widget for the [Omarchy](https://omarchy.org) bar: a radar of nearby devices, a receive window that closes on its own, and file / folder / clipboard sharing — without opening the LocalSend app.

[Tiếng Việt bên dưới ↓](#tiếng-việt)

![LocalSend panel](preview.png)

## Features

- **Radar** of nearby LocalSend devices (phones, laptops, desktops), found over multicast on your Wi‑Fi/LAN.
- **Visible for 5 min / 10 min / 30 min / 1 hour / Always**, like AirDrop's "Everyone for 10 minutes". Outside the window this computer stays hidden and refuses uploads, but you can still find and send to others.
- **Accept / Decline** card and desktop notification for incoming files. Files are saved to your Downloads folder.
- **Send files, a folder, or the clipboard text** to a device by clicking it on the radar.
- Incoming text messages are copied to the clipboard.
- Progress bar, cancel, and a list of recently received files.
- English and Vietnamese UI (follows the system locale, or pick one in the widget settings).
- Bar icon follows your theme. Left click opens the panel, right click toggles visibility.

## Requirements

- Omarchy 4.0+
- `python3` and `openssl` (both present on a stock Omarchy install)
- TCP and UDP port **53317** open. Omarchy's default firewall already allows it for LocalSend.
- The other device runs the LocalSend app on the same network.

Close the LocalSend desktop app before using this widget: both listen on port 53317.

## Install

```bash
omarchy plugin add https://github.com/ngiangbao/localsend_v2_omarchy_plugin.git --enable
```

## Settings

Set these in the widget settings, or with `omarchy bar set ngiangbao.localsend <key> <value>`:

| Key | Default | Meaning |
|---|---|---|
| `windowMinutes` | `10` | Initial "visible for" choice; `0` means until turned off |
| `deviceName` | hostname | The name other devices see |
| `language` | `Auto` | `Auto`, `English` or `Tiếng Việt` |

Keyboard (panel open): `v` toggle visibility, `f` send files, `d` send folder, `c` send clipboard.

IPC: `omarchy-shell ngiangbao.localsend open|close|toggle|receive|stop|status`

## How it works

`bin/lsd.py` is a small LocalSend protocol v2 peer written in Python with only the standard library. It announces itself on `224.0.0.167:53317`, serves HTTPS on port 53317 with a self-signed certificate kept in `~/.local/share/ngiangbao-localsend/`, and implements `/register`, `/prepare-upload`, `/upload`, `/cancel` and `/info`. The QML widget runs it as a child process and talks to it in JSON lines over stdin and stdout.

Received file names are sanitised, nothing is written outside the Downloads folder, and existing files are never overwritten.

## License

MIT. LocalSend is a trademark of its respective owners; this project is not affiliated with LocalSend.

---

## Tiếng Việt

Widget [LocalSend](https://localsend.org) kiểu AirDrop cho thanh bar của [Omarchy](https://omarchy.org): radar hiển thị thiết bị ở gần, chế độ hiển thị tự tắt sau một khoảng thời gian, và gửi tệp / thư mục / clipboard mà không cần mở app LocalSend.

### Tính năng

- **Radar** quét các thiết bị LocalSend ở gần (điện thoại, laptop, máy bàn) trong cùng mạng Wi‑Fi/LAN.
- **Hiển thị trong 5 phút / 10 phút / 30 phút / 1 giờ / Luôn bật**, giống "Mọi người trong 10 phút" của AirDrop. Ngoài khoảng thời gian đó máy được ẩn và từ chối nhận tệp, nhưng bạn vẫn tìm và gửi được cho người khác.
- **Chấp nhận / Từ chối** khi có tệp gửi đến, kèm thông báo. Tệp được lưu vào thư mục Downloads.
- **Gửi tệp, thư mục hoặc chữ trong clipboard**: bấm vào thiết bị trên radar.
- Tin nhắn văn bản nhận được sẽ tự chép vào clipboard.
- Thanh tiến trình, nút huỷ, danh sách tệp đã nhận gần đây.
- Giao diện tiếng Anh và tiếng Việt (tự theo ngôn ngữ hệ thống, hoặc chọn trong cài đặt widget).
- Icon trên bar theo màu theme. Chuột trái mở bảng, chuột phải bật/tắt hiển thị.

### Yêu cầu

- Omarchy 4.0 trở lên
- `python3` và `openssl` (có sẵn trên Omarchy)
- Mở cổng **53317** TCP và UDP. Tường lửa mặc định của Omarchy đã mở sẵn cho LocalSend.
- Thiết bị kia chạy app LocalSend trong cùng mạng.

Hãy tắt app LocalSend trên máy tính trước khi dùng widget này, vì cả hai cùng dùng cổng 53317.

### Cài đặt

```bash
omarchy plugin add https://github.com/ngiangbao/localsend_v2_omarchy_plugin.git --enable
```

### Cài đặt widget

| Khoá | Mặc định | Ý nghĩa |
|---|---|---|
| `windowMinutes` | `10` | Thời gian hiển thị mặc định; `0` là đến khi tắt |
| `deviceName` | tên máy | Tên thiết bị khác nhìn thấy |
| `language` | `Auto` | `Auto`, `English` hoặc `Tiếng Việt` |

Ví dụ: `omarchy bar set ngiangbao.localsend language "Tiếng Việt"`

Phím tắt khi bảng đang mở: `v` bật/tắt hiển thị, `f` gửi tệp, `d` gửi thư mục, `c` gửi clipboard.
