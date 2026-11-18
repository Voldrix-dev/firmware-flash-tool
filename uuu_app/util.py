import re

from . import cfg


def format_t(seconds):
    seconds = int(seconds)
    if seconds < 0:
        seconds = 0
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02}:{sec:02}"
    return f"{minutes:02}:{sec:02}"


def usb_path_in_line(line: str, usb_path: str) -> bool:
    if not usb_path:
        return False
    pattern = rf"(?<!\d){re.escape(usb_path)}(?!\d)"
    return re.search(pattern, line) is not None


def is_main_log_noise(line: str) -> bool:
    if not line:
        return True
    if cfg.hex_progress_noise_re.match(line):
        return True
    prefixes = (
        "uuu (Universal Update Utility)",
        "Build in config:",
        "Pctl",
        "==================================================",
        "Run built-in script:",
        "uuu_version",
        "# ",
        "SDPS:",
        "SDP:",
        "SDPU:",
        "SDPV:",
        "FBK:",
        "FB:",
        "Wait for Known USB",
    )
    return line.startswith(prefixes)

