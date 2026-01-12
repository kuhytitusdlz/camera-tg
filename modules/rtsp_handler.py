"""Этот модуль сейчас не используется из main.py; оставлен на случай прямого запуска записи."""
import os
import time
import subprocess
from datetime import datetime, timezone
from modules.env_config import VIDEO_DIR, RTSP_URL, FFMPEG_LOGLEVEL, CONTINUOUS_SEGMENT_SECONDS
from modules.logger import log

# Ensure the video directory exists
os.makedirs(VIDEO_DIR, exist_ok=True)

def record_loop():
    while True:
        # 1) Rename leftover .mkv.part → .mkv
        for fname in os.listdir(VIDEO_DIR):
            if fname.endswith(".mkv.part"):
                part_path = os.path.join(VIDEO_DIR, fname)
                final_path = part_path[:-5]
                try:
                    os.rename(part_path, final_path)
                    log(f"Renamed leftover part {fname}")
                except Exception as e:
                    log(f"Error renaming {fname}: {e}")

        # 2) Расчёт длительности до следующей 5-мин. границы
        now_ts = time.time()
        next_stop = ((int(now_ts) // CONTINUOUS_SEGMENT_SECONDS) + 1) * CONTINUOUS_SEGMENT_SECONDS
        duration = next_stop - now_ts

        # 3) Запуск ffmpeg
        timestamp = datetime.now().strftime("%Y.%m.%d_%H.%M.%S")
        part_path = os.path.join(VIDEO_DIR, f"{timestamp}.mkv.part")
        cmd = [
            'ffmpeg', '-hide_banner', '-y',
            '-loglevel', FFMPEG_LOGLEVEL,
            "-fflags", "+genpts", "-rtsp_transport", "tcp",
            '-i', RTSP_URL,
            '-t', str(duration),
            "-c", "copy", "-movflags", "+faststart",
            '-f', 'matroska',
            part_path
        ]
        subprocess.run(cmd)

