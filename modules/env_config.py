import os
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# Telegram
# -----------------------------
TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
# 0=без звука, 1=вибро, 2=с уведомлением
TG_SILENT_MODE = int(os.getenv("TG_SILENT_MODE", "0"))

# -----------------------------
# RTSP / Recording
# -----------------------------
RTSP_URL = os.getenv("RTSP_URL", "")
VIDEO_DIR = os.getenv("VIDEO_DIR", "/videos")
FFMPEG_LOGLEVEL = os.getenv("FFMPEG_LOGLEVEL", "error")

# Управление режимами записи
# true  = писать только после алёрта; false = писать постоянно сегментами
RECORD_ON_ALERT_ONLY = os.getenv("RECORD_ON_ALERT_ONLY", "false").lower() == "true"

# Длительности (секунды)
# Сколько секунд писать после алёрта (одним файлом)
ALERT_RECORD_SECONDS = int(os.getenv("ALERT_RECORD_SECONDS", "120"))
# Длина одного сегмента при непрерывной записи (выравнивается по сетке)
CONTINUOUS_SEGMENT_SECONDS = int(os.getenv("CONTINUOUS_SEGMENT_SECONDS", "300"))

# -----------------------------
# Encoding / отправка
# -----------------------------
# Режимы:
# 1=отправлять оригинал MKV
# 2=конвертировать в H.264/AAC MP4
# 3=конвертировать и ОПЦИОНАЛЬНО обрезать старт на TRIM_START_SECONDS
SEND_ORIGINAL_MKV = int(os.getenv("SEND_ORIGINAL_MKV", "3"))
# Сколько секунд срезать с начала (для быстрого появления изображения в плеере)
TRIM_START_SECONDS = float(os.getenv("TRIM_START_SECONDS", "0"))

# Параметры нарезки перед отправкой в TG (чтобы уложиться в лимиты)
TG_MAX_FILE_MB = float(os.getenv("TG_MAX_FILE_MB", "50"))
TG_SPLIT_SAFETY = float(os.getenv("TG_SPLIT_SAFETY", "0.80"))  # 0..1

# -----------------------------
# Preview (кадр перед видео)
# -----------------------------
# true  = генерировать и отправлять jpg-превью перед видео
# false = не делать превью (экономит CPU/IO)
VIDEO_PREVIEW_ENABLED = os.getenv("VIDEO_PREVIEW_ENABLED", "true").lower() == "true"

# -----------------------------
# ONVIF Events
# -----------------------------
ONVIF_ENABLED = bool(int(os.getenv("ONVIF_ENABLED", "0")))
ONVIF_HOST = os.getenv("ONVIF_HOST", "")
ONVIF_PORT = int(os.getenv("ONVIF_PORT", "8899"))
ONVIF_USER = os.getenv("ONVIF_USER", "")
ONVIF_PASS = os.getenv("ONVIF_PASS", "")
SNAPSHOT_URL = os.getenv("SNAPSHOT_URL", "")
# 0=off, 1=debug JSON/XML
ONVIF_LOG_LEVEL = int(os.getenv("ONVIF_LOG_LEVEL", "0"))

# Фильтры алёртов
IS_MOTION_ENABLED = bool(int(os.getenv("IS_MOTION_ENABLED", "1")))
IS_TAMPER_ENABLED = bool(int(os.getenv("IS_TAMPER_ENABLED", "1")))
# Антиспам по фото-алёртам (сек)
ALERT_TIMEOUT = int(os.getenv("ALERT_TIMEOUT", "30"))

# -----------------------------
# Logging
# -----------------------------
# DEBUG=1 включает более подробные логи (включая потенциально чувствительные данные).
DEBUG = os.getenv("DEBUG", "0").strip().lower() in {"1", "true", "yes", "y", "on"}

# Уровни логирования (stdlib logging). Влияет на сторонние библиотеки (httpx/httpcore) и их вывод.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
HTTPX_LOG_LEVEL = os.getenv("HTTPX_LOG_LEVEL", "WARNING")
HTTPCORE_LOG_LEVEL = os.getenv("HTTPCORE_LOG_LEVEL", HTTPX_LOG_LEVEL)
