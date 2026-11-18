import json
import os
import re


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_FILE = os.path.join(BASE_DIR, "data", "firmware_config.json")
HELP_FILE = os.path.join(BASE_DIR, "data", "help_text.json")
STYLE_FILE = os.path.join(BASE_DIR, "data", "dark.qss")
ICON_DIR = os.path.join(BASE_DIR, "icons")
FIRM_FILE = "rootfs.wic"
DIR = os.path.join(BASE_DIR, "firm_file") + os.sep
CMD_1 = "uuu -v -m"
CMD_2 = "-b emmc_all"
DEVICE_KEY = "SDPS"
FIRM_DATA = DIR + FIRM_FILE
BOOT_FILE = "imx-boot-imx8mpevk-sd.bin-flash_evk"
BOOT_DATA = DIR + BOOT_FILE
PANEL_NAMES = [f"D{i + 1}" for i in range(10)]
DEFAULT_DEVICE_PATHS = ["1:7", "1:9", "1:10", "1:111", "1:113", "1:114", "1:133", "1:134", "1:112", "1:3"]
device_paths_by_panel = dict(zip(PANEL_NAMES, DEFAULT_DEVICE_PATHS))
history_list = []
boot_history_list = []
progress_size_hints = {}
# Runtime state for calibration of compressed firmware progress.  It is shared
# by all panels because they run in the same application process.
progress_calibration_key = None
progress_calibration_owner = None
progress_calibration_active_count = 0
usb_overlay_pos = None

percent_re = re.compile(r"(\d{1,3})%")
byte_progress_re = re.compile(r"^\d{5,}$")
error_re = re.compile(r"\b(Fail|Error)\b", re.IGNORECASE)
ansi_escape = re.compile(r"(?:\x1B[@-Z\\-_]|\x1B\[[0-?]*[ -/]*[@-~])")
hex_progress_noise_re = re.compile(r"^0x[0-9a-fA-F]+0x[0-9a-fA-F]+$")
hex_value_re = re.compile(r"^0x[0-9a-fA-F]+(?:\s+0x[0-9a-fA-F]+)*$")


def icon_path(name):
    return os.path.join(ICON_DIR, name)


def resolve_firmware_path(firmware_value: str) -> str:
    val = (firmware_value or "").strip()
    if not val:
        return ""
    if os.path.isabs(val):
        return val
    return os.path.join(DIR, val)


def firmware_key(firmware_value: str) -> str:
    return os.path.abspath(resolve_firmware_path(firmware_value))


def get_progress_total_bytes(firmware_path: str) -> int:
    if not firmware_path or not os.path.isfile(firmware_path):
        return 0
    key = os.path.abspath(firmware_path)
    hinted = progress_size_hints.get(key)
    if isinstance(hinted, int) and hinted > 0:
        return hinted
    if firmware_path.lower().endswith((".bz2", ".gz", ".xz", ".zip", ".zst")):
        return 0
    try:
        return os.path.getsize(firmware_path)
    except OSError:
        return 0


def reset_progress_calibration(firmware_path: str = None):
    """Start one calibration session for the selected firmware."""
    global progress_calibration_key, progress_calibration_owner, progress_calibration_active_count
    progress_calibration_key = os.path.abspath(firmware_path) if firmware_path else None
    progress_calibration_owner = None
    progress_calibration_active_count = 0


def claim_progress_calibrator(firmware_path: str, panel_name: str) -> bool:
    """Return whether this panel owns unknown-size byte measurement."""
    global progress_calibration_key, progress_calibration_owner, progress_calibration_active_count
    key = os.path.abspath(firmware_path)
    if progress_calibration_key == key and progress_calibration_active_count == 0:
        progress_calibration_owner = None
    if get_progress_total_bytes(firmware_path) > 0:
        progress_calibration_active_count += 1
        return False
    if progress_calibration_key != key:
        progress_calibration_key = key
        progress_calibration_owner = None
    if progress_calibration_owner is None:
        progress_calibration_owner = panel_name
    progress_calibration_active_count += 1
    return progress_calibration_owner == panel_name


def finish_progress_calibration():
    global progress_calibration_active_count
    progress_calibration_active_count = max(0, progress_calibration_active_count - 1)


def load_stylesheet(app, path=STYLE_FILE):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
        except Exception as e:
            print(f"Error load style\n{e}")


def detect_language():
    """ru или en: из UUU_LANG, затем из локали, иначе en."""
    forced = os.environ.get("UUU_LANG", "").strip().lower()
    if forced in ("ru", "en"):
        return forced
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if not value:
            continue
        code = value.split(".")[0].split("_")[0].lower()
        if code == "ru":
            return "ru"
        if code:
            return "en"
    return "en"


def _default_help(lang):
    if lang == "ru":
        return "Инструкция", (
            "Firmware Flash Tool — параллельная прошивка плат NXP i.MX через uuu.\n\n"
            "1. Прошивка и загрузчик — кнопка с иконкой папки (Firmware / boot files).\n"
            "2. USB-путь панели (например 1:7), Enter — применить; путь виден в USB-панели (F10).\n"
            "3. ▶ Play — прошить один раз; ⟳ AUTO — автоматически; ■ STOP — остановить.\n"
            "4. </> — режим UuuProcess / UuuScriptProcess.\n"
            "5. Горячие клавиши: Ctrl+A/S/R/U, Ctrl+1..9/0/X, F10, F11, Alt+...\n"
        )
    return "Instructions", (
        "Firmware Flash Tool — parallel flashing of NXP i.MX boards via uuu.\n\n"
        "1. Firmware & bootloader — folder button (Firmware / boot files).\n"
        "2. Panel USB path (e.g. 1:7), Enter to apply; visible in USB panel (F10).\n"
        "3. ▶ Play — flash once; ⟳ AUTO — automatic; ■ STOP — stop.\n"
        "4. </> — UuuProcess / UuuScriptProcess mode.\n"
        "5. Hotkeys: Ctrl+A/S/R/U, Ctrl+1..9/0/X, F10, F11, Alt+...\n"
    )


def load_help_text():
    lang = detect_language()
    if os.path.exists(HELP_FILE):
        try:
            with open(HELP_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                node = data.get(lang)
                if not isinstance(node, dict):
                    node = data.get("ru") if lang == "en" else data.get("en")
                if isinstance(node, dict):
                    title = node.get("title") or "Инструкция"
                    text = node.get("text") or ""
                    return str(title), str(text)
                title = data.get("title")
                text = data.get("text")
                if title is not None or text is not None:
                    return str(title or "Инструкция"), str(text or "")
        except Exception:
            pass
    ru_title, ru_text = _default_help("ru")
    en_title, en_text = _default_help("en")
    payload = {
        "ru": {"title": ru_title, "text": ru_text},
        "en": {"title": en_title, "text": en_text},
    }
    try:
        os.makedirs(os.path.dirname(HELP_FILE), exist_ok=True)
        with open(HELP_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    title, text = (ru_title, ru_text) if lang == "ru" else (en_title, en_text)
    return title, text


def load_firmware():
    global FIRM_FILE, FIRM_DATA, BOOT_FILE, BOOT_DATA, history_list, boot_history_list, device_paths_by_panel, progress_size_hints, usb_overlay_pos
    history_list = []
    boot_history_list = []
    device_paths_by_panel = dict(zip(PANEL_NAMES, DEFAULT_DEVICE_PATHS))
    progress_size_hints = {}
    usb_overlay_pos = None
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded_firmware = data.get("firmware", FIRM_FILE)
            FIRM_FILE = loaded_firmware.strip() if isinstance(loaded_firmware, str) else FIRM_FILE
            loaded_boot = data.get("boot", BOOT_FILE)
            BOOT_FILE = loaded_boot.strip() if isinstance(loaded_boot, str) else BOOT_FILE
            raw_history = data.get("history", [])
            history_list = [x.strip() for x in raw_history if isinstance(x, str) and x.strip()][:10] if isinstance(raw_history, list) else []
            raw_boot_history = data.get("boot_history", [])
            boot_history_list = [x.strip() for x in raw_boot_history if isinstance(x, str) and x.strip()][:10] if isinstance(raw_boot_history, list) else []
            raw_paths = data.get("device_paths", {})
            if isinstance(raw_paths, dict):
                for panel_name in PANEL_NAMES:
                    path_value = raw_paths.get(panel_name)
                    if isinstance(path_value, str) and path_value.strip():
                        device_paths_by_panel[panel_name] = path_value.strip()
            raw_hints = data.get("progress_size_hints", {})
            if isinstance(raw_hints, dict):
                progress_size_hints = {
                    str(path): int(size)
                    for path, size in raw_hints.items()
                    if isinstance(path, str) and isinstance(size, int) and size > 0
                }
            raw_overlay_pos = data.get("usb_overlay_pos")
            if isinstance(raw_overlay_pos, dict):
                x = raw_overlay_pos.get("x")
                y = raw_overlay_pos.get("y")
                if isinstance(x, int) and isinstance(y, int):
                    usb_overlay_pos = {"x": x, "y": y}
        except Exception:
            history_list = []
            boot_history_list = []
    if FIRM_FILE and FIRM_FILE not in history_list:
        history_list.insert(0, FIRM_FILE)
        history_list = history_list[:10]
    if BOOT_FILE and BOOT_FILE not in boot_history_list:
        boot_history_list.insert(0, BOOT_FILE)
        boot_history_list = boot_history_list[:10]
    FIRM_DATA = resolve_firmware_path(FIRM_FILE)
    BOOT_DATA = resolve_firmware_path(BOOT_FILE)
    reset_progress_calibration(FIRM_DATA)


def save_firmware():
    if FIRM_FILE and FIRM_FILE not in history_list:
        history_list.insert(0, FIRM_FILE)
        del history_list[10:]
    if BOOT_FILE and BOOT_FILE not in boot_history_list:
        boot_history_list.insert(0, BOOT_FILE)
        del boot_history_list[10:]
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "firmware": FIRM_FILE,
                    "boot": BOOT_FILE,
                    "history": history_list,
                    "boot_history": boot_history_list,
                    "device_paths": device_paths_by_panel,
                    "progress_size_hints": progress_size_hints,
                    "usb_overlay_pos": usb_overlay_pos,
                },
                f,
                indent=4,
            )
    except Exception:
        pass
