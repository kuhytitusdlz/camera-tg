# camera-tg — ONVIF/RTSP камера → Telegram

Проект запускает один или несколько контейнеров (по контейнеру на камеру), которые:

- подписываются на ONVIF-события (Motion / Tamper и др., в зависимости от камеры);
- при алёрте могут отправлять **фото** (snapshot) в Telegram;
- пишут RTSP-поток в файловые сегменты и/или клипы “по событию”;
- отправляют видео в Telegram, при необходимости **конвертируя** в MP4 и/или **нарезая** файл по размеру;
- опционально формируют **preview (JPG кадр)** перед видео;
- поддерживают команды Telegram (в рамках реализованного обработчика команд).

## Требования

- Docker + Docker Compose.
- Камера/регистратор с:
  - RTSP URL (для записи видео)
  - ONVIF (опционально, для алёртов)
  - Snapshot URL (опционально, для фото в алёртах)

## Быстрый старт

1) Скопируйте пример `.env` и заполните параметры:

- `cp .env.example .env1`
- `cp .env.example .env2` (если используете второй контейнер)

2) Проверьте `docker-compose.yml`:
- `env_file: .env1 / .env2`
- `volumes:` — куда на хосте складываются записи (`/tmp/camera1`, `/tmp/camera2` по умолчанию)

3) Запуск:

```bash
docker compose up -d --build
docker logs -f camera1
```

Остановка:

```bash
docker compose down
```

## Конфигурация (.env)

Ниже перечислены переменные окружения. Полный “чистый” пример без секретов — в файле `.env.example`.

### Telegram

- `TG_TOKEN` — токен бота (BotFather). **Секрет**.
- `TG_CHAT_ID` — chat_id, куда слать сообщения (личка/группа/канал).  
  Примечание: для групп/каналов могут потребоваться права бота.
- `TG_SILENT_MODE` — режим уведомления:
  - `0` = без звука
  - `1` = “тихо”
  - `2` = с уведомлением

### RTSP / запись видео

- `RTSP_URL` — RTSP URL потока. **Секрет** (часто содержит логин/пароль).
- `VIDEO_DIR` — путь внутри контейнера, куда пишутся видео (по умолчанию `/videos`).
- `RECORD_ON_ALERT_ONLY`:
  - `true` — писать клип только после ONVIF-алёрта (длина `ALERT_RECORD_SECONDS`)
  - `false` — писать постоянно сегментами (длина `CONTINUOUS_SEGMENT_SECONDS`)
- `ALERT_RECORD_SECONDS` — сколько секунд писать после алёрта (по умолчанию `120`).
- `CONTINUOUS_SEGMENT_SECONDS` — длина сегмента при непрерывной записи (по умолчанию `300`).
- `FFMPEG_LOGLEVEL` — уровень логов ffmpeg (например `error`, `warning`, `info`).

### Отправка / конвертация

- `SEND_ORIGINAL_MKV` (режим отправки):
  - `1` — отправлять оригинальный MKV
  - `2` — конвертировать в MP4 (H.264/AAC)
  - `3` — конвертировать в MP4 и опционально **обрезать старт** на `TRIM_START_SECONDS`
- `TRIM_START_SECONDS` — сколько секунд срезать с начала (по умолчанию `0`).
- `TG_MAX_FILE_MB` — ориентир по максимальному размеру одного файла для Telegram (по умолчанию `50`).
- `TG_SPLIT_SAFETY` — “запас” при нарезке (0..1), например `0.80`.

### Preview перед видео

- `VIDEO_PREVIEW_ENABLED`:
  - `true` — генерировать и отправлять JPG-превью перед видео
  - `false` — не делать превью (экономит CPU/IO)

### ONVIF / алёрты

- `ONVIF_ENABLED` — `0/1` включить ONVIF подписку.
- `ONVIF_HOST` — адрес камеры.
- `ONVIF_PORT` — порт ONVIF (по умолчанию `8899`).
- `ONVIF_USER` — пользователь ONVIF.
- `ONVIF_PASS` — пароль ONVIF. **Секрет**.
- `SNAPSHOT_URL` — URL для получения JPEG snapshot (для фото в алёртах).
- `ONVIF_LOG_LEVEL` — `0` (тихо) / `1` (дебаг XML/JSON, если включено в код).
- `IS_MOTION_ENABLED` — `0/1` реагировать на Motion.
- `IS_TAMPER_ENABLED` — `0/1` реагировать на Tamper.
- `ALERT_TIMEOUT` — антиспам по фото-алёртам (сек).  
  Если движения идут часто, фото может отправляться не на каждое событие — это ожидаемо.

### Логирование и скрытие секретов

Проект поддерживает отдельную настройку уровней логирования и режим “debug”.

- `DEBUG`:
  - `0` — по умолчанию: **секреты редактируются** (`<redacted>`) в логах
  - `1` — debug: санитизация отключается (удобно для отладки, но небезопасно)
- `LOG_LEVEL` — общий уровень stdlib logging (`DEBUG/INFO/WARNING/ERROR/CRITICAL`).
- `HTTPX_LOG_LEVEL` — уровень логов библиотеки `httpx`.  
  Рекомендуется `WARNING`, чтобы не печатать URL Telegram с токеном.
- `HTTPCORE_LOG_LEVEL` — уровень логов `httpcore` (по умолчанию берётся из `HTTPX_LOG_LEVEL`).

### Тюнинг HTTP к Telegram (httpx)

- `TG_CONNECT_TIMEOUT` — таймаут соединения (сек), по умолчанию `10`
- `TG_READ_TIMEOUT` — таймаут чтения (сек), по умолчанию `600`
- `TG_WRITE_TIMEOUT` — таймаут записи (сек), по умолчанию = `TG_READ_TIMEOUT`
- `TG_RETRIES` — число повторов при ошибке, по умолчанию `2`
- `TG_RETRY_BACKOFF_SEC` — пауза между повторами, по умолчанию `2`
- `TG_UPLOAD_CHUNK_SIZE` — размер чанка при отправке, по умолчанию `262144` (256 KiB)
- `TG_UPLOAD_PROGRESS` — `1` включить прогресс в логах, иначе `0`
- `TG_UPLOAD_PROGRESS_INTERVAL_SEC` — интервал логирования прогресса (сек), по умолчанию `2.0`

## Частые проблемы

### “Иногда фото (ONVIF Alert: Motion) есть, иногда нет”
Наиболее частая причина — `ALERT_TIMEOUT`: фото-алёрты отправляются не чаще одного раза за заданный интервал.  
Также возможны временные ошибки получения `SNAPSHOT_URL` или отправки в Telegram — это видно в логах.

### В логах видны токены/пароли
Проверьте:
- `DEBUG=0`
- `HTTPX_LOG_LEVEL=WARNING` (или выше)

Если токен уже “засветился” в логах, его рекомендуется **перевыпустить** в BotFather.

### Пример .env
```conf
# Telegram Bot
TG_TOKEN=xxx:xxx                 # Telegram bot token
TG_CHAT_ID=-100xxx               # ID чата или пользователя для отправки
TG_SILENT_MODE=0          # 0=без звука, 1=вибро, 2=с уведомлением

# Logging
DEBUG=0                   # 1=debug (может выводить чувствительные данные), 0=по умолчанию скрывает секреты
LOG_LEVEL=INFO            # CRITICAL|ERROR|WARNING|INFO|DEBUG
HTTPX_LOG_LEVEL=WARNING   # логирование httpx (в INFO будет светить Telegram URL)
HTTPCORE_LOG_LEVEL=WARNING

# RTSP Recording
RTSP_URL=rtsp://192.168.100.101:554/user=admin&password=&channel=1&stream=0.sdp                 # RTSP URL (rtsp://user:pass@host:port/…)
VIDEO_DIR=/videos         # Папка для хранения сегментов
FFMPEG_LOGLEVEL=error     # ffmpeg log level: panic,fatal,error,warning,info,verbose,debug,trace

# How to send originals
SEND_ORIGINAL_MKV=3       # 1=отправлять оригинал MKV, 2=конверт в H.264/AAC mp4, 3=усечь+opus mp4
TRIM_START_SECONDS=0.1    # Сколько секунд обрезать с начала перед конвертацией

# Video preview (jpg кадр перед видео)
VIDEO_PREVIEW_ENABLED=false   # true=делать превью, false=не делать (экономия CPU)

# ONVIF Events
ONVIF_ENABLED=1           # 0=выключено, 1=включено
ONVIF_HOST=192.168.100.101               # IP/хост ONVIF-камеры
ONVIF_PORT=8899           # Порт ONVIF (обычно 8899)
ONVIF_USER=admin               # Пользователь ONVIF
ONVIF_PASS=               # Пароль ONVIF
SNAPSHOT_URL=http://192.168.100.101/webcapture.jpg?command=snap&channel=1             # URL для JPEG-кадрирования (snapshot)
ONVIF_LOG_LEVEL=0         # 0=off, 1=debug JSON/XML

# Alert filters
IS_MOTION_ENABLED=1       # 0=не оповещать по движению, 1=оповещать
IS_TAMPER_ENABLED=1       # 0=не оповещать по саботажу, 1=оповещать
ALERT_TIMEOUT=4          # Задержка в секундах между повторными alert
RECORD_ON_ALERT_ONLY=true
ALERT_RECORD_SECONDS=60     # длительность записи при алёрте, в секундах
CONTINUOUS_SEGMENT_SECONDS=300 # длина сегмента при непрерывной записи, в секундах
TG_MAX_FILE_MB=50            # лимит размера файла для Bot API, МБ
TG_SPLIT_SAFETY=0.80         # коэффициент запаса при нарезке (0..1)

# tg upload
TG_CONNECT_TIMEOUT=10
TG_READ_TIMEOUT=600
TG_WRITE_TIMEOUT=600 #(важно именно для upload)
TG_RETRIES=2
TG_RETRY_BACKOFF_SEC=2

TG_UPLOAD_PROGRESS=1
TG_UPLOAD_PROGRESS_INTERVAL_SEC=5.0 # (как часто логировать)
TG_UPLOAD_CHUNK_SIZE=$((256*1024))   # можно 512*1024 если хотите реже лог
```