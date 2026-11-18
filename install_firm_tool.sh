#!/usr/bin/env bash
set -e

APP_DIR="$HOME/tests"
VENV_DIR="$APP_DIR/firm_env"
APP_SCRIPT="$APP_DIR/run_uuu_app.py"
WRAPPER="$APP_DIR/firm.sh"

PYTHON="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

DESKTOP_MENU_FILE="$HOME/.local/share/applications/Firmware_Flash_Tool.desktop"
DESKTOP_SHORTCUT="$HOME/Desktop/Firmware_Flash_Tool.desktop"

CLI_NAME="firm"
CLI_PATH="/usr/local/bin/$CLI_NAME"

ICON_PATH="$APP_DIR/icons/i_firm.svg"

echo "======================================"
echo " Firmware Flash Tool Installer"
echo "======================================"

########################################
# 0. Install UUU
########################################

echo "[1/6] Checking UUU..."

if command -v uuu >/dev/null 2>&1; then
    echo "UUU already installed:"
    uuu -version || uuu --version || true
else
    if command -v apt-get >/dev/null 2>&1; then
        echo "Installing UUU via apt..."
        sudo apt-get update
        sudo apt-get install -y uuu

    elif command -v yay >/dev/null 2>&1; then
        echo "Installing UUU via yay..."
        yay -S --noconfirm uuu

    elif command -v pacman >/dev/null 2>&1; then
        echo "Installing UUU via pacman..."
        sudo pacman -S --needed --noconfirm uuu

    else
        echo "ERROR: No supported package manager found."
        exit 1
    fi

    echo "UUU installed:"
    uuu || true
fi

########################################
# 1b. Install libusb + udev rules for pyusb
########################################

echo "[1b/6] Installing USB dependencies for pyusb..."

if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y libusb-1.0-0 udev
elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed --noconfirm libusb udev
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y libusb1-devel udev
fi

UDEV_RULES="/etc/udev/rules.d/99-firmware-tool.rules"
if [ ! -f "$UDEV_RULES" ]; then
    echo "Installing udev rules for NXP SDPS devices..."
    sudo tee "$UDEV_RULES" > /dev/null <<'UDEV'
# NXP i.MX SDPS (VID 0x1fc9, 0x15a2) — allow non-root access
SUBSYSTEM=="usb", ATTRS{idVendor}=="1fc9", MODE="0666"
SUBSYSTEM=="usb", ATTRS{idVendor}=="15a2", MODE="0666"
UDEV
    if command -v udevadm >/dev/null 2>&1; then
        sudo udevadm control --reload-rules
        sudo udevadm trigger
    fi
fi

########################################
# 1. Create venv
########################################

if [ ! -d "$VENV_DIR" ]; then
    echo "[2/6] Creating virtual environment..."

    python3 -m venv "$VENV_DIR"

    echo "Installing Python dependencies..."
    "$PIP" install --upgrade pip
else
    echo "[2/6] VENV already exists"
fi

"$PIP" install PySide6 qtawesome pyusb

export LD_LIBRARY_PATH="$APP_DIR/lib:$LD_LIBRARY_PATH"

########################################
# 2. Wrapper
########################################

echo "[3/6] Creating wrapper..."

cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

export LD_LIBRARY_PATH="$DIR/lib:$LD_LIBRARY_PATH"

"$DIR/firm_env/bin/python" "$DIR/run_uuu_app.py"
EOF

chmod +x "$WRAPPER"

########################################
# 3. CLI install
########################################

echo "[4/6] Installing CLI command..."

if sudo ln -sf "$WRAPPER" "$CLI_PATH"; then
    echo "Installed: $CLI_PATH"
else
    echo "ERROR: Failed to install CLI command."
    exit 1
fi

########################################
# 4. Desktop menu entry
########################################

echo "[5/6] Creating application menu entry..."

mkdir -p "$(dirname "$DESKTOP_MENU_FILE")"

cat > "$DESKTOP_MENU_FILE" <<EOF
[Desktop Entry]
Name=Firmware Flash Tool
Comment=Flash devices using Universal Update Utility
GenericName=Firmware Tool
Exec=$WRAPPER
Icon=$ICON_PATH
Type=Application
Categories=Development;Utility;
Keywords=firmware;flash;uuu;device;
Terminal=false
StartupWMClass=Firmware_Flash_Tool
EOF

chmod +x "$DESKTOP_MENU_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications"
fi

########################################
# 5. Desktop shortcut
########################################

echo "[6/6] Desktop shortcut setup"

read -r -p "Create Desktop shortcut? (Y/n): " desk_ans
desk_ans=${desk_ans:-Y}

if [[ "$desk_ans" =~ ^[Yy]$ ]]; then
    mkdir -p "$HOME/Desktop"

    cat > "$DESKTOP_SHORTCUT" <<EOF
[Desktop Entry]
Name=Firmware Flash Tool
Comment=Flash devices using Universal Update Utility
Exec=$WRAPPER
Icon=$ICON_PATH
Type=Application
Categories=Utility;Development;
Keywords=firmware;flash;uuu;device;
Terminal=false
StartupWMClass=Firmware_Flash_Tool
EOF

    chmod +x "$DESKTOP_SHORTCUT"

    echo "Desktop shortcut created:"
    echo "  $DESKTOP_SHORTCUT"
else
    echo "Skipping desktop shortcut"
fi

########################################
# DONE
########################################

echo
echo "======================================"
echo " INSTALL COMPLETE"
echo "======================================"
echo
echo "Run:"
echo "  firm"
echo
echo "Or directly:"
echo "  $WRAPPER"
echo
echo "No shell reload required."
echo