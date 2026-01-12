import os
import time
import subprocess
from glob import glob
from os import listdir
from os.path import join, exists, getsize, splitext

from modules.env_config import (
    VIDEO_DIR,
    SEND_ORIGINAL_MKV,
    TRIM_START_SECONDS,
    FFMPEG_LOGLEVEL,
    TG_MAX_FILE_MB,
    TG_SPLIT_SAFETY,
    VIDEO_PREVIEW_ENABLED,
)
from modules.telegram_utils import send_preview_image, send_video_file
from modules.logger import log
from modules.telegram_utils import send_telegram_message

MAX_TELEGRAM_SIZE = int(TG_MAX_FILE_MB * 1024 * 1024)
SAFETY_MARGIN = TG_SPLIT_SAFETY

_LAST_FFMPEG_ALERT_TS = 0.0


def make_preview_jpg(src_video_path: str, preview_jpg_path: str, *, max_width: int = 960, quality: int = 6) -> bool:
    """
    Дёшево по ресурсам: вытаскиваем 1 кадр, можно ресайзнуть и сжать.
    quality: 2..10 (меньше = лучше качество/больше размер). 5-7 обычно ок.
    """
    try:
        cmd = ["ffmpeg", "-y", "-loglevel", FFMPEG_LOGLEVEL]

        # небольшой сдвиг, чтобы не словить пустой первый кадр
        ss = TRIM_START_SECONDS if (TRIM_START_SECONDS and TRIM_START_SECONDS > 0) else 0.2
        cmd += ["-ss", str(ss)]

        cmd += ["-i", src_video_path, "-an", "-frames:v", "1"]

        # ресайз по ширине (с сохранением пропорций) + явный range, т.к. вход yuvj420p/color_range=pc
        if max_width and max_width > 0:
            cmd += ["-vf", f"scale='min({max_width},iw)':-2:in_range=pc:out_range=pc,format=yuv420p"]

        # важно: -update 1, иначе ffmpeg может ругаться и/или сделать 0-byte файл
        cmd += ["-q:v", str(quality), "-update", "1", preview_jpg_path]

        subprocess.run(cmd, check=True)

        ok = os.path.exists(preview_jpg_path) and os.path.getsize(preview_jpg_path) > 0
        if not ok:
            log(f"⚠️ Preview empty or missing: {preview_jpg_path}")
        return ok

    except Exception as e:
        log(f"Ошибка make_preview_jpg: {type(e).__name__}: {e!r}")
        return False


def _tg_alert_ffmpeg_once_per(min_seconds: int, text: str) -> None:
    global _LAST_FFMPEG_ALERT_TS
    now = time.time()
    if now - _LAST_FFMPEG_ALERT_TS < float(min_seconds):
        return
    _LAST_FFMPEG_ALERT_TS = now
    try:
        send_telegram_message(text)
    except Exception as e:
        log(f"⚠️ Не удалось отправить алерт в TG: {type(e).__name__}: {e!r}")


def _run_cmd_logged(cmd, *, what: str, timeout: int | None = None):
    def _tail(s: str, n: int = 120) -> str:
        if not s:
            return ""
        lines = s.splitlines()
        if len(lines) <= n:
            return s
        return "\n".join(lines[-n:])

    log(f"▶️ {what}: {' '.join(cmd)}")
    p = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False
    )

    if p.returncode != 0:
        log(f"❌ {what} failed rc={p.returncode}")
        if p.stdout:
            log(f"{what} stdout (tail):\n{_tail(p.stdout)}")
        if p.stderr:
            log(f"{what} stderr (tail):\n{_tail(p.stderr)}")

        stderr_tail = _tail(p.stderr or "", n=40)
        msg = (
            f"❌ ffmpeg ошибка: {what}\n"
            f"rc={p.returncode}\n"
            f"cmd: {' '.join(cmd)[:900]}\n"
            f"stderr:\n{stderr_tail[:2500]}"
        )
        _tg_alert_ffmpeg_once_per(120, msg)

        raise RuntimeError(f"{what} failed rc={p.returncode}")

    return p


def split_video(path, ext):
    size = getsize(path)
    limit = MAX_TELEGRAM_SIZE * SAFETY_MARGIN
    if size <= limit:
        return [path]

    # duration probe (ffprobe)
    try:
        out = subprocess.check_output([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path
        ], stderr=subprocess.STDOUT, text=True)
        duration = float((out or "").strip())
        segment_time = max(1, duration * limit / size)
    except Exception as e:
        log(f"⚠️ ffprobe duration failed for {path}: {type(e).__name__}: {e!r}")
        segment_time = 60

    # Важно: имя частей должно быть ДЕТЕРМИНИРОВАННЫМ,
    # иначе после рестарта мы не сможем однозначно сопоставить части между собой.
    base_name, _ = splitext(os.path.basename(path))
    pattern = os.path.join(VIDEO_DIR, f"{base_name}_part%03d{ext}")

    cmd = [
        "ffmpeg", "-y", "-loglevel", FFMPEG_LOGLEVEL,
        "-i", path,
        "-c", "copy",
        "-f", "segment",
        "-segment_time", str(segment_time),
        "-reset_timestamps", "1",
        pattern
    ]

    try:
        _run_cmd_logged(cmd, what=f"ffmpeg split {os.path.basename(path)}")
        parts = sorted(glob(os.path.join(VIDEO_DIR, f"{base_name}_part*{ext}")))
        return parts if parts else [path]
    except Exception as e:
        log(f"⚠️ Error splitting video {path}: {type(e).__name__}: {e!r}")
        return [path]


def send_loop():
    while True:
        # Обрабатываем в стабильном порядке (старые файлы первыми)
        for fname in sorted(listdir(VIDEO_DIR)):
            if not fname.endswith(".mkv"):
                continue

            path = join(VIDEO_DIR, fname)
            preview_jpg = path.replace(".mkv", ".jpg")
            mp4_file = path.replace(".mkv", ".mp4")
            sent = False

            # Если mp4 уже существует (например, конвертация успела пройти до падения),
            # не конвертим заново.
            mp4_ready = exists(mp4_file)

            # превью (опционально)
            if VIDEO_PREVIEW_ENABLED:
                try:
                    if make_preview_jpg(path, preview_jpg, max_width=960, quality=6):
                        send_preview_image(preview_jpg)
                except Exception as e:
                    log(f"Ошибка генерации/отправки превью: {e}")
                finally:
                    try:
                        if exists(preview_jpg):
                            os.remove(preview_jpg)
                    except Exception:
                        pass

            try:
                # 1) Получаем mp4 (если надо)
                if SEND_ORIGINAL_MKV == 1:
                    # отправляем mkv как есть
                    to_send = path

                else:
                    to_send = mp4_file

                    if not mp4_ready:
                        if SEND_ORIGINAL_MKV == 2:
                            conversion_args = [
                                "ffmpeg", "-y", "-loglevel", FFMPEG_LOGLEVEL,
                            ]
                            if TRIM_START_SECONDS and TRIM_START_SECONDS > 0:
                                conversion_args += ["-ss", str(TRIM_START_SECONDS)]
                            conversion_args += [
                                "-i", path,
                                "-map", "0:v:0", "-map", "0:a:0?",
                                "-c:v", "libx264",
                                "-preset", "fast",
                                "-crf", "28",
                                # если нужен AAC: "-c:a", "aac", "-b:a", "128k"
                                "-c:a", "libopus",
                                "-b:a", "128k",
                                "-f", "mp4", "-movflags", "+faststart", mp4_file
                            ]
                            _run_cmd_logged(conversion_args, what=f"ffmpeg transcode {os.path.basename(path)} -> {os.path.basename(mp4_file)}")

                        elif SEND_ORIGINAL_MKV == 3:
                            conversion_args = [
                                "ffmpeg", "-y", "-loglevel", FFMPEG_LOGLEVEL,
                            ]
                            if TRIM_START_SECONDS and TRIM_START_SECONDS > 0:
                                conversion_args += ["-ss", str(TRIM_START_SECONDS)]
                            conversion_args += [
                                "-i", path,
                                "-map", "0:v:0", "-map", "0:a:0?",
                                "-c:v", "copy",
                                "-c:a", "libopus",
                                "-f", "mp4", "-movflags", "+faststart", mp4_file
                            ]
                            _run_cmd_logged(
                                conversion_args,
                                what=f"ffmpeg remux(copy v) {os.path.basename(path)} -> {os.path.basename(mp4_file)}"
                            )

                        else:
                            # неизвестный режим — не трогаем файл
                            log(f"⚠️ Unknown SEND_ORIGINAL_MKV={SEND_ORIGINAL_MKV}, skip: {path}")
                            continue

                # 2) Отправляем (с поддержкой докачки частей после рестарта)
                parts = split_video(to_send, ".mp4") if to_send.endswith(".mp4") else [to_send]
                log(f"Отправка видеофайла: {to_send}")

                for p in parts:
                    if p.endswith(".mp4.sent"):
                        continue
                    # если уже помечен как отправленный
                    if exists(p + ".sent"):
                        continue

                    # MP4 отправляем как video (режим 3)
                    send_video_file(p, as_document=False)

                    # помечаем отправленную часть, чтобы можно было продолжить после рестарта
                    if p.endswith(".mp4") and "_part" in os.path.basename(p):
                        try:
                            os.rename(p, p + ".sent")
                        except Exception:
                            pass

                sent = True

            except Exception as e:
                # ничего не удаляем — пусть повторит позже
                log(f"Ошибка отправки видео ({path}): {e}")

            if sent:
                try:
                    # удаляем исходник только ПОСЛЕ успешной отправки
                    if exists(path) and path.endswith(".mkv"):
                        os.remove(path)

                    # удаляем mp4 (если это не оригинальный mkv)
                    if (to_send != path) and exists(mp4_file) and mp4_file.endswith(".mp4"):
                        os.remove(mp4_file)

                    base, _ = splitext(os.path.basename(to_send))
                    # чистим сегменты (включая помеченные .sent)
                    for seg in glob(join(VIDEO_DIR, f"{base}_part*.mp4")) + glob(join(VIDEO_DIR, f"{base}_part*.mp4.sent")):
                        try:
                            os.remove(seg)
                        except Exception:
                            pass

                except Exception as e:
                    log(f"Ошибка очистки после отправки: {e}")

        # ---- Досылка зависших mp4/частей после падения ----

        # 1) цельные mp4
        for fname in sorted(listdir(VIDEO_DIR)):
            if not fname.endswith(".mp4"):
                continue
            if "_part" in fname:
                continue

            path = join(VIDEO_DIR, fname)
            base, _ = splitext(os.path.basename(path))

            try:
                parts = split_video(path, ".mp4")
                log(f"♻️ Повторная отправка видео: {path}")

                for p in parts:
                    if exists(p + ".sent"):
                        continue
                    send_video_file(p, as_document=False)
                    if "_part" in os.path.basename(p):
                        try:
                            os.rename(p, p + ".sent")
                        except Exception:
                            pass

                # всё ушло — чистим
                if exists(path):
                    os.remove(path)
                for seg in glob(join(VIDEO_DIR, f"{base}_part*.mp4")) + glob(join(VIDEO_DIR, f"{base}_part*.mp4.sent")):
                    try:
                        os.remove(seg)
                    except Exception:
                        pass

            except Exception as e:
                log(f"⚠️ Ошибка повторной отправки ({path}): {e}")

        # 2) если остались ТОЛЬКО части (без базового mp4)
        part_candidates = sorted(glob(join(VIDEO_DIR, "*_part*.mp4")))
        groups: dict[str, list[str]] = {}
        for p in part_candidates:
            if p.endswith(".sent"):
                continue
            prefix = p.rsplit("_part", 1)[0]
            groups.setdefault(prefix, []).append(p)

        for prefix, parts in groups.items():
            base_mp4 = prefix + ".mp4"
            if exists(base_mp4):
                continue  # обработает блок (1)

            pending = [p for p in sorted(parts) if exists(p)]
            if not pending:
                continue

            try:
                log(f"♻️ Досылка набором частей: {prefix} ({len(pending)} частей)")
                for p in pending:
                    if exists(p + ".sent"):
                        continue
                    send_video_file(p, as_document=False)
                    try:
                        os.rename(p, p + ".sent")
                    except Exception:
                        pass

                # если все части отправлены — чистим
                for p in glob(prefix + "_part*.mp4") + glob(prefix + "_part*.mp4.sent"):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

            except Exception as e:
                log(f"⚠️ Ошибка досылки частей ({prefix}): {e}")

        time.sleep(10)
