"""Сканер USB- устройств через внешнюю утилиту uuu (lsusb).

Запускает `uuu -lsusb` в отдельном потоке и парсит вывод.
Возвращает словарь в том же формате, что и парсер pyusb:
    {path: {"mode": mode, "serial": serial}, ...}

Путь — bus:port (например, "1:7" или "1:2.3" за хабом).
Фильтр — VID NXP (0x1fc9, 0x15a2).
Режим определяется по классу интерфейса: 0xFF — SDPS, 0x08 — MSC.
"""

import re
import subprocess

NXP_VIDS = {0x1FC9, 0x15A2}
SDPS_INTERFACE_CLASS = 0xFF
MSC_INTERFACE_CLASS = 0x08


def _device_mode(dev):
    """Определяем режим устройства по классу первого интерфейса."""
    try:
        for cfg in dev:
            for iface in cfg:
                cls = getattr(iface, "bInterfaceClass", None)
                if cls == SDPS_INTERFACE_CLASS:
                    return "SDPS"
                if cls == MSC_INTERFACE_CLASS:
                    return "MSC"
    except Exception:
        pass
    return "SDPS"  # NXP-ушки по умолчанию сидят в SDPS


def _device_serial(dev):
    try:
        return dev.iSerialNumber or ""
    except Exception:
        return ""


def _device_path(dev):
    """Формат bus:port, как в uuu -lsusb (точки вместо точек для хаба)."""
    try:
        ports = list(dev.port_numbers or [])
    except Exception:
        ports = []
    if ports:
        return f"{dev.bus}:" + ".".join(str(p) for p in ports)
    return f"{dev.bus}:{dev.address}"


def parse_uuu_output(raw):
    """Парсит вывод uuu -lsusb и возвращает словарь устройств."""
    devices = {}
    # Пример строки:
    # 1:7      MX865   SDPS:   0x1FC9 0x0146   0x0002  1212A800F871E059
    # 1:72     MX865   SDPS:   0x1FC9 0x0146   0x0002  1212A800F871E059
    lines = raw.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith("="):
            continue
        # Path Chip Pro Vid Pid BcdVersion Serial_no
        parts = line.split()
        if len(parts) < 6:
            continue
        path = parts[0]
        vid_hex = parts[4]
        pid_hex = parts[5]
        try:
            vid = int(vid_hex, 16)
        except ValueError:
            continue
        if vid not in NXP_VIDS:
            continue
        mode = "SDPS"  # по умолчанию, если класс не определен
        serial = parts[6] if len(parts) > 6 else ""
        devices[path] = {
            "mode": mode,
            "serial": serial,
        }
    return devices


def scan_usb():
    """Сканирует USB-шину, запуская uuu -lsusb в отдельном процессе.

    Возвращает словарь устройств. Вызывается в отдельном потоке.
    """
    try:
        result = subprocess.run(
            ["uuu", "-lsusb"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        devices = parse_uuu_output(result.stdout + result.stderr)
    except Exception as exc:
        print(f"[usb_scan] error running uuu -lsusb: {exc}")
        devices = {}
    return devices


def scan_usb_diff(prev_devices=None):
    """Сканирует USB и возвращает (текущие, список новых путей).

    Новые пути — те, которых не было в `prev_devices`.
    """
    current = scan_usb()
    prev = prev_devices or {}
    new_paths = [p for p in current if p not in prev]
    return current, new_paths


class UuuScanWorker(QtCore.QThread):
    """Сканер uuu -lsusb в отдельном потоке, не блокируя GUI."""

    parsed = QtCore.Signal(dict)
    error = QtCore.Signal(str)

    def run(self):
        try:
            devices = scan_usb()
        except Exception as exc:
            self.error.emit(f"Ошибка сканирования uuu: {exc}")
            devices = {}
        self.parsed.emit(devices)