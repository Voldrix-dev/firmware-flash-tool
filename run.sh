#!/usr/bin/env bash

# ==========================================
#       FIRMWARE FLASH TOOL LAUNCHER
# ==========================================

set -Ee

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
    exit 1
}

trap 'error "Ошибка в строке $LINENO. Проверь вывод выше."' ERR

clear 2>/dev/null || true

echo -e "${CYAN}"
echo "=========================================="
echo "        FIRMWARE FLASH TOOL"
echo "          UNIVERSAL LAUNCHER"
echo "=========================================="
echo -e "${NC}"

# ==========================================
# 1. Определяем директорию проекта
# ==========================================

PROJECT_DIR="$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)"

cd "$PROJECT_DIR"

log "Проект: $PROJECT_DIR"

# ==========================================
# 2. Информация о компьютере
# ==========================================

echo
echo "Компьютер: $(hostname)"
echo "Пользователь: $(whoami)"
echo "Система: $(uname -s)"

# ==========================================
# 3. Проверяем Python
# ==========================================

if ! command -v python3 >/dev/null 2>&1; then
    error "Python3 не установлен"
fi

PYTHON_VERSION="$(python3 --version)"

log "$PYTHON_VERSION найден"

# ==========================================
# 4. Проверяем структуру проекта
# ==========================================

[ -f "$PROJECT_DIR/run_uuu_app.py" ] \
    || error "run_uuu_app.py не найден"

# ==========================================
# 5. Глобальное виртуальное окружение пользователя
# ==========================================

VENV="$HOME/.venv"
VENV_PYTHON="$VENV/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then

    if [ -e "$VENV" ]; then
        error "Найдено поврежденное окружение: $VENV. Автоматическое удаление запрещено."
    fi

    warn "Локальное окружение не найдено"
    log "Создаем $VENV"

    python3 -m venv "$VENV" \
        || error "Не удалось создать виртуальное окружение"

else

    log "Используем существующее окружение: $VENV"

fi

# ==========================================
# 6. Проверяем pip
# ==========================================

"$VENV_PYTHON" -m pip --version \
    || error "pip отсутствует в виртуальном окружении"
"$VENV_PYTHON" -m pip install --upgrade pip

# ==========================================
# 7. Устанавливаем зависимости
# ==========================================

REQUIREMENTS="$PROJECT_DIR/scripts/requirements.txt"

if [ -f "$REQUIREMENTS" ]; then

    REQUIREMENTS_HASH="$(sha256sum "$REQUIREMENTS" | awk '{print $1}')"
    HASH_FILE="$VENV/.requirements_hash"

    OLD_HASH=""
    if [ -f "$HASH_FILE" ]; then
        OLD_HASH="$(cat "$HASH_FILE")"
    fi

    if [ "$REQUIREMENTS_HASH" != "$OLD_HASH" ]; then

        warn "Список зависимостей изменился или установка выполняется впервые"

        "$VENV_PYTHON" -m pip install -r "$REQUIREMENTS" \
            || error "Не удалось установить зависимости"

        printf '%s\n' "$REQUIREMENTS_HASH" > "$HASH_FILE"

        log "Зависимости установлены"

    else

        log "Зависимости не изменились. Установка пропущена"

    fi

else

    warn "requirements.txt не найден, пропускаем установку зависимостей"

fi

# ==========================================
# 8. Ярлыки (меню приложений + рабочий стол)
# ==========================================

DESKTOP_MENU_FILE="$HOME/.local/share/applications/Firmware_Flash_Tool.desktop"
DESKTOP_SHORTCUT="$HOME/Desktop/Firmware_Flash_Tool.desktop"
ICON_PATH="$PROJECT_DIR/icons/i_firm.svg"

mkdir -p "$(dirname "$DESKTOP_MENU_FILE")"

cat > "$DESKTOP_MENU_FILE" <<EOF
[Desktop Entry]
Name=Firmware Flash Tool
Comment=Flash devices using Universal Update Utility
GenericName=Firmware Tool
Exec=$PROJECT_DIR/run.sh
Icon=$ICON_PATH
Type=Application
Categories=Development;Utility;
Keywords=firmware;flash;uuu;device;
Terminal=false
StartupWMClass=Firmware_Flash_Tool
EOF
    chmod +x "$DESKTOP_MENU_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
fi

log "Ярлык в меню: $DESKTOP_MENU_FILE"

if [ ! -f "$ICON_PATH" ]; then
    warn "Иконка не найдена: $ICON_PATH (ярлык будет без иконки)"
fi

mkdir -p "$HOME/Desktop"

cat > "$DESKTOP_SHORTCUT" <<EOF
[Desktop Entry]
Name=Firmware Flash Tool
Comment=Flash devices using Universal Update Utility
Exec=$PROJECT_DIR/run.sh
Icon=$ICON_PATH
Type=Application
Categories=Utility;Development;
Keywords=firmware;flash;uuu;device;
Terminal=false
StartupWMClass=Firmware_Flash_Tool
EOF
    chmod +x "$DESKTOP_SHORTCUT"

log "Ярлык на рабочем столе: $DESKTOP_SHORTCUT"

# ==========================================
# 9. Запуск приложения
# ==========================================

echo
echo -e "${CYAN}=========================================="
echo "          STARTING FIRMWARE FLASH TOOL"
echo "==========================================${NC}"

log "Окружение: $VENV"

exec "$VENV_PYTHON" "$PROJECT_DIR/run_uuu_app.py"
