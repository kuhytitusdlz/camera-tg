import os
import time
import subprocess
from datetime import datetime, timezone
from threading import Event

from modules.env_config import (
    VIDEO_DIR, RTSP_URL, FFMPEG_LOGLEVEL,
    RECORD_ON_ALERT_ONLY, ALERT_RECORD_SECONDS, CONTINUOUS_SEGMENT_SECONDS
)
from modules.logger import log

# Глобальное событие алёрта (устанавливается onvif_handler)
alert_event = Event()

os.makedirs(VIDEO_DIR, exist_ok=True)

def clean_leftovers():
    """Переименовать хвосты .mkv.part в .mkv после падения/рестарта."""
    for fname in os.listdir(VIDEO_DIR):
        if fname.endswith('.mkv.part'):
            part_path = os.path.join(VIDEO_DIR, fname)
            final_path = part_path[:-5]
            try:
                os.rename(part_path, final_path)
                log(f"Renamed leftover part {fname} -> {os.path.basename(final_path)}")
            except Exception as e:
                log(f"Error renaming {fname}: {e}")

_last_rtsp_warn = 0

def _rtsp_ready() -> bool:
    # пустой RTSP_URL -> предупреждаем раз в 60 сек
    global _last_rtsp_warn
    if not RTSP_URL:
        now = time.time()
        if now - _last_rtsp_warn > 60:
            log("⚠️ RTSP_URL пуст. Запись не запускается. Укажите RTSP_URL в .env")
            _last_rtsp_warn = now
        return False
    return True

def trigger_record(duration: int = ALERT_RECORD_SECONDS):
    if not _rtsp_ready():
        time.sleep(5)
        return

    timestamp = datetime.now(timezone.utc).strftime('%Y.%m.%d_%H.%M.%S')
    part_path = os.path.join(VIDEO_DIR, f"{timestamp}.mkv.part")
    final_path = part_path[:-5]

    cmd = [
        'ffmpeg', '-y', '-loglevel', FFMPEG_LOGLEVEL,
        '-rtsp_transport', 'tcp', '-i', RTSP_URL,
        '-map', '0:v:0', '-map', '0:a:0?',
        '-c', 'copy',
        '-t', str(int(duration)),
        '-f', 'matroska',
        part_path
    ]

    try:
        subprocess.run(cmd, check=True, timeout=int(duration) + 30)
        try:
            os.rename(part_path, final_path)
            log(f"Triggered recording saved: {final_path}")
        except Exception as e:
            log(f"Error renaming {part_path}: {e}")
    except subprocess.TimeoutExpired:
        log("ffmpeg timeout: killing record process")
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except Exception:
            pass
        time.sleep(3)
    except Exception as e:
        log(f"ffmpeg error during record: {e}")
        try:
            if os.path.exists(part_path):
                os.remove(part_path)
        except Exception:
            pass
        # небольшой бэк-офф, чтобы не спамить
        time.sleep(3)


def record_loop():
    """Главный цикл записи.
    - RECORD_ON_ALERT_ONLY = true: ждать алёрт -> писать ALERT_RECORD_SECONDS одной порцией.
    - RECORD_ON_ALERT_ONLY = false: писать постоянно сегментами CONTINUOUS_SEGMENT_SECONDS,
      выравниваясь к ближайшей сетке, чтобы файлы начинались на "ровных" отметках.
    """
    clean_leftovers()

    if RECORD_ON_ALERT_ONLY:
        while True:
            alert_event.wait()
            alert_event.clear()
            trigger_record(ALERT_RECORD_SECONDS)
    else:
        # Непрерывная запись: сегменты выравниваем по сетке CONTINUOUS_SEGMENT_SECONDS
        seg = max(1, int(CONTINUOUS_SEGMENT_SECONDS))
        while True:
            if not _rtsp_ready():
                time.sleep(5)
                continue
            now_ts = time.time()
            next_stop = ((int(now_ts) // seg) + 1) * seg
            duration = max(1, int(next_stop - now_ts))
            trigger_record(duration)