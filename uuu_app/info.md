# uuu_app — Firmware Flash Tool (FlasherFarm)

GUI-приложение на **PySide6** для параллельной прошивки нескольких устройств через утилиту NXP **uuu** (Universal Update Utility). Это «флеш-ферма» для конвейерного производства: оператор подключает к одному Linux-ПК несколько плат (i.MX 8M / SDPS), выбирает firmware и boot, нажимает одну кнопку — приложение само ждёт устройства, шьёт и повторяет цикл в автоматическом режиме.

---

## Возможности

- До **10 одновременных панелей прошивки** (`D1`–`D10`) с индивидуальными USB-путями.
- Два режима прошивки:
  - `UuuProcess` — однократная команда `uuu -v -m <dev> -b emmc_all <boot> <firmware>`.
  - `UuuScriptProcess` — сессия `uuu -s -m <dev>` со скриптом `SDPS: boot … → FB: flash … → FB: reboot` (используется для сжатых `.bz2`/`.zip` firmware, требует `/*` для разворачивания payload).
- **Автоматический режим (AUTO)** — после завершения панель ждёт повторного появления устройства и шьёт снова (типичный сценарий фермы: плата вышла, новая встала).
- **Разовая прошивка (Play)** — однократный прогон.
- **Групповые кнопки** сверху: «All-Auto», «All-Once», «All-Stop». Счётчик прошивок (просто число справа сверху) правится правой кнопкой мыши: «Редактировать...» и «Очистить».
- **Мониторинг USB** — фоновое сканирование `/sys/bus/usb` на NXP-устройства (VID `0x1fc9`, `0x15a2`); оверлей с перечнем устройств, цветовая подсветка панелей, мигание индикатора активности.
- **Прогресс-бар с калибровкой**:
  - если `uuu` печатает проценты, берётся напрямую;
  - иначе используется байтовая разметка (распакованный `.wic`), при необходимости — **калибровочная сессия**: первая панель замеряет ожидаемый размер файла и сохраняет хинт в конфиг.
- **Цветовая индикация состояний** панели: idle / flashing / success / error (красный маркер `!`, мигание зелёного по успеху).
- **Лог каждой панели** с фильтрацией шума (`util.is_main_log_noise`) и просмотром последней ошибки по клику на заголовок.
- **Полноэкранный режим** (F11) и **горячие клавиши Ctrl+1..9 / Ctrl+0 / Ctrl+X** для переключения количества активных панелей.
- **Сохранение конфигурации** в `data/firmware_config.json`: выбранные файлы, история (10 последних firmware), USB-пути панелей, хинты прогресса, позиция оверлея.
- **Тёмная QSS-тема** (`data/dark.qss`).
- **Локализация интерфейса**: русский + английский (иконки `qtawesome`).

---

## Структура проекта

```
uuu_app/
├── run.py        # точка входа QApplication
├── app.py        # главное окно FlasherFarmApp(QMainWindow)
├── panel.py      # DevicePanelWidget — панель одного устройства
├── proc.py       # UuuProcess, UuuScriptProcess, reboot_device()
├── ovl.py        # UsbDevicesOverlay, FileSettingsOverlay
├── ui.py         # ClickableLabel, RoundedProgressBar, PanelSignals
├── cfg.py        # пути, конфиг, QSS, калибровка прогресса
├── qt.py         # алиас PySide6 (Signal/Slot)
├── util.py       # format_t, is_main_log_noise
└── __init__.py
```

Внешние зависимости (рядом, в `tests/`):
```
data/firmware_config.json   # авто-создаётся cfg.save_firmware()
data/help_text.json         # переопределяет встроенную инструкцию
data/dark.qss               # тёмная тема
icons/i_firm.svg            # иконка приложения
firm_file/                  # каталог прошивок (rootfs.wic, imx-boot-...bin)
```

---

## Подробно о работе

### 1. Запуск и инициализация (`run.py`)

```python
app = QtWidgets.QApplication([])
app.setApplicationName("Firmware Flash Tool")
cfg.load_stylesheet(app)    # QSS из data/dark.qss
cfg.load_firmware()         # конфиг + сброс калибровки
window = FlasherFarmApp()   # app.py
window.show(); app.exec()
```

`run.py` корректно работает как обычный скрипт и как PyInstaller-бинарник (`sys._MEIPASS`), и при запуске через `-m uuu_app.run` (за счёт ветки `if __package__ in (None, "")`).

### 2. Главное окно (`app.py` — `FlasherFarmApp`)

В конструкторе вызываются 11 шагов:

| Метод | Что делает |
|---|---|
| `_init_state` | Создаёт списки панелей, словарь USB-устройств, флаг `fullscreen`, счётчик `flash_count`. |
| `_create_ui` | Верхняя панель: часы, кнопка выбора файлов (тултип показывает текущие firmware/boot), **индикатор активности** (10 точек по панелям), кнопки `All-Auto / All-Once / All-Stop`, счётчик прошивок (контекстное меню: «Редактировать...», «Очистить»). Снизу — пустая сетка `grid_layout` для панелей. |
| `_create_panels` | Создаёт 10 объектов `DevicePanelWidget`, но скрывает лишние в зависимости от `desired_active_panels_count` (по умолчанию 5). |
| `_connect_signals` | Подключает кнопки к слотам; связывает сигнал успешной прошивки панели с инкрементом глобального счётчика. |
| `_create_timers` | `QTimer` часов (1 с), `QTimer` USB-мониторинга (~500 мс), таймер мигания активности. |
| `_create_shortcuts` | F11 (fullscreen), Ctrl+1..9/0/X (изменить число видимых панелей). |
| `rebuild_panel_grid` | Перераскладывает активные панели в сетке 2×N. |
| `start_usb_monitor` | Включает периодический опрос USB. |

**USB-мониторинг** (`_scan_usb_devices`):
- читает `/sys/bus/usb/devices/*/idVendor` и `idProduct`;
- фильтрует по VID NXP (`1fc9`, `15a2`);
- читает `devpath` (например, `1.7` → USB-путь для `uuu` — `1:7`);
- дифф-состояния (`появилось / пропало`) подсвечивают панели и мигают индикатор.

**Rebuild grid**: при изменении числа активных панелей приложение пересчитывает ряды/столбцы и переразмещает виджеты, сохраняя порядок `D1..D10`.

### 3. Панель устройства (`panel.py` — `DevicePanelWidget`)

Каждая панель — полноценная FSM. Ключевые поля:

```python
self.flash_stage      # WAIT_DEVICE → SDPS_BOOT → FLASH_ROOTFS →
                      # FLASH_BOOTLOADER → FINALIZE → DONE
self.auto             # включён AUTO-режим
self.is_flashing      # сейчас идёт прошивка
self.use_script_process  # переключатель UuuProcess ↔ UuuScriptProcess
self.uuu              # текущий объект процесса
self.progress_mode    # SDPS | FLASH
```

#### Цикл AUTO (`_auto_timer_tick`)
```
если AUTO включён и устройство подключено (usb_devices[id]):
    если не идёт прошивка → start_flash()
иначе:
    переход в WAIT_DEVICE
```
Таймаут AUTO — 2 секунды; состояние «DONE» сбрасывается на «WAIT_DEVICE» при отключении устройства, чтобы при следующем подключении снова шить.

#### Запуск прошивки (`start_flash`)
- выбирается процессор по типу firmware:
  - `.bz2 / .zip / .gz / .xz / .zst` → `UuuScriptProcess` (через `-s`, со скриптом — обязательно, иначе `uuu` примет сжатый файл без записи);
  - остальное → `UuuProcess` (однократная команда).
- коннектятся сигналы `output / error / finished` к слотам `_on_stdout / _on_stderr / _on_finished`.

#### Парсинг вывода uuu (`_on_stdout`)
Используются регулярки из `cfg.py`:
- `percent_re` — `(\d{1,3})%`;
- `byte_progress_re` — `^\d{5,}$` (отдельная строка с числом байт);
- `error_re` — `\b(Fail|Error)\b`;
- `hex_progress_noise_re` — отбраковка `0x…0x…`.

Логика распознавания стадии:
- `SDPS:` → `FlashStage.SDPS_BOOT`;
- `FB:` → переход в `FLASH_ROOTFS` или `FLASH_BOOTLOADER`;
- `100%` + отсутствие ошибок → `DONE`, инкремент счётчика, мигание, запуск AUTO-таймера.

#### Прогресс-бар (`RoundedProgressBar`)
Виджет из `ui.py`. Два режима:
- **Процентный** — `setValue(int(percent))`, без калибровки;
- **Байтовый** — `setRange(0, total_bytes)`, обновление по `byte_progress_re`.
Если `cfg.get_progress_total_bytes(firmware) == 0` (сжатый файл) — панель становится **calibrator'ом**: измеряет наибольшее значение байтов за прогон, затем `cfg.progress_size_hints[key] = total` сохраняется в конфиг.

#### Обработка ошибок
- Любая строка с `Fail|Error` → `error_marker` загорается, заголовок панели становится красным с маркером `!`.
- По клику на заголовок — диалог `show_error_log_dialog` с полным последним логом.

### 4. Процессы (`proc.py`)

#### `UuuProcess` — простой вариант
```python
self.proc.start("uuu", ["-v", "-m", dev_path, "-b", "emmc_all", boot, firmware])
```
stdout и stderr читаются через `readyReadStandardOutput/Error`, буферизуются до `\n` или `\r` (uuu использует `\r` для прогресса) и эмитятся построчно. Сигнал `finished(code, error_flag)` сообщает UI о завершении.

#### `UuuScriptProcess` — скриптовый вариант
Запускается интерактивная сессия `uuu -s -m <dev>`, далее посылаются команды с ожиданием приглашения `U>`:

```
SDPS: boot -scanterm -f <boot> -scanlimited 0x800000
FB: ucmd setenv fastboot_dev mmc
FB: ucmd setenv mmcdev ${emmc_dev}
FB: ucmd mmc dev ${emmc_dev}
FB: flash -raw2sparse all <firmware>/*      # /* обязательно для .bz2
FB: flash -scanterm -scanlimited 0x800000 bootloader <boot>
FB: ucmd if env exists emmc_ack; then ; else setenv emmc_ack 0; fi;
FB: ucmd mmc partconf ${emmc_dev} ${emmc_ack} 1 0
FB: done
FB: reboot
```

Парсер ищет `U>` в выводе, между приглашениями ищет `Okay` (успех) или `Fail` (провал). Таймауты:
- `COMMAND_TIMEOUT_MS = 60_000` для большинства команд;
- `FLASH_TIMEOUT_MS = 15 * 60_000` для `FB: flash -raw2sparse`.

При ошибке **не повторяет** (`MAX_ATTEMPTS = 1`) — частично прошитое устройство небезопасно перешивать «в лоб», сессия прерывается (`quit\n` → `terminate` → через 1 с `kill`).

#### `reboot_device(dev_path)`
«Выстрелил и забыл» — отдельный `QProcess` с `MergedChannels`, ключи `-t 2 -s`, пишет `FB: reboot\nquit\n`. Не имеет сигналов — нельзя зациклить.

### 5. Оверлеи (`ovl.py`)

#### `UsbDevicesOverlay`
Плавающая рамка поверх окна (можно таскать мышью, **pin** для фиксации позиции). Показывает все найденные USB-устройства с их VID/PID и devpath. Позиция сохраняется в `usb_overlay_pos`.

#### `FileSettingsOverlay`
Диалог выбора файлов:
- **firmware** — имя файла или полный путь (резолвится через `cfg.resolve_firmware_path`);
- **boot** — путь к `imx-boot-...bin-flash_evk`;
- список истории (последние 10 файлов);
- кнопка `Set` сохраняет выбор в `cfg.FIRM_FILE/BOOT_FILE` и `save_firmware()`.

### 6. Конфигурация (`cfg.py`)

Файл `data/firmware_config.json`:
```json
{
  "firmware": "rootfs.wic",
  "boot": "imx-boot-imx8mpevk-sd.bin-flash_evk",
  "history": ["rootfs.wic", "..."],
  "device_paths": {"D1": "1:7", "D2": "1:9", ...},
  "progress_size_hints": {"/abs/path/rootfs.wic": 12345678},
  "usb_overlay_pos": {"x": 100, "y": 100}
}
```

Пути:
- `BASE_DIR` — корень проекта (`tests/`);
- `DIR = firm_file/` — каталог прошивок;
- `FIRM_FILE` по умолчанию — `rootfs.wic`;
- `BOOT_FILE` по умолчанию — `imx-boot-imx8mpevk-sd.bin-flash_evk`;
- `DEFAULT_DEVICE_PATHS` — массив из 10 USB-путей для `D1..D10`.

`cfg.load_stylesheet` грузит `data/dark.qss` (если файл есть) и применяет к `QApplication`.

`cfg.load_help_text` — берёт текст из `data/help_text.json` или использует встроенный русский quick-start.

### 7. Стиль и UI-утилиты

- **`ui.py`** — `ClickableLabel` (метка с сигналом `clicked`), `RoundedProgressBar` (скруглённый QProgressBar в QSS), `PanelSignals` (фасад Qt-сигналов из фоновых потоков в GUI).
- **`util.py`** — `format_t(seconds)` (формат `HH:MM:SS`), `is_main_log_noise(line)` (фильтр шумовых строк `uuu`, которые не нужны оператору).
- **`qt.py`** — единая точка импорта `PySide6.QtCore/QtGui/QtWidgets`, чтобы не разъезжались версии.
- **Иконки** — `qtawesome` (FontAwesome 5): `fa5s.sync-alt`, `fa5s.play`, `fa5s.stop`, `fa5s.folder-open`, `fa5s.sign-out-alt`, `fa5s.question`.

### 8. Полный сценарий оператора

1. Запустить `python -m uuu_app.run` (или установленный `.desktop`-ярлык).
2. Нажать **📁 Firmware / boot files** → выбрать `rootfs.wic` (или `.bz2`) и `imx-boot-...bin-flash_evk`. Нажать **Set**.
3. Убедиться, что USB-пути панелей `D1..DN` соответствуют физическим подключениям (по умолчанию заданы в `DEFAULT_DEVICE_PATHS`).
4. Подключить платы в режиме **Serial Download (SDPS)**.
5. Нажать **▶ Run ONCE (All)** для разового прогона или **🔄 Start AUTO (All)** для непрерывного режима.
6. Наблюдать:
   - прогресс-бары каждой панели,
   - мигание индикатора активности,
   - точки активности в верхней панели,
   - счётчик прошивок справа сверху (ПКМ по нему — «Редактировать...» / «Очистить»).
7. По завершении — зелёная вспышка, `DONE`, AUTO автоматически ждёт следующую плату.

### 9. Клавиши

| Клавиша | Действие |
|---|---|
| `F11` | Полноэкранный режим |
| `Ctrl+1` … `Ctrl+9` | Показать N панелей |
| `Ctrl+0` / `Ctrl+X` | Все 10 панелей |
| `Enter` в поле USB-пути | Применить путь к панели |
| Клик по заголовку панели с `!` | Открыть последнюю ошибку |

### 10. Типовые проблемы и поведение

- **`uuu: command not found`** — `proc.py` ловит через `errorOccurred` → `QProcess start error` → панель остаётся в `WAIT_DEVICE`, маркируется ошибкой.
- **`.bz2` прошит «молча» без реальной записи** — лечится использованием `UuuScriptProcess` (флаг `use_script_process = True`) и `/*` в команде `FB: flash -raw2sparse all <firmware>/*`.
- **`Fail` посередине сессии** — `_command_failed` шлёт `quit`, через 1 с `terminate`, ещё через 1 с `kill`. Повторов нет (`MAX_ATTEMPTS = 1`).
- **Устройство осталось в bootloader после успеха** — AUTO ждёт нового `SDPS`-события и шьёт снова.
- **Прогресс-бар завис на 0%** — панель стала calibrator'ом; после первого успешного прогона хинт сохранится и остальные панели будут показывать прогресс по байтам.

### 11. Что стоит знать при доработке

- Все потоковые операции (чтение stdout/stderr `uuu`) идут через сигналы Qt — прямого Python-потока нет, поэтому GIL не мешает параллельной прошивке.
- `progress_calibration_*` — глобальные переменные модуля `cfg.py`, т.к. состояние калибровки одно на приложение.
- `device_paths_by_panel` — глобальный dict `cfg.py`, но пишется в конфиг при `save_firmware()`.
- Точка расширения: новый режим прошивки = новый класс в `proc.py` с теми же сигналами `output / error / finished(int, bool)`.
- Точка расширения UI: новый оверлей = класс-наследник `QWidget` с `WA_DeleteOnClose`, создаётся из `app.py` по событию.