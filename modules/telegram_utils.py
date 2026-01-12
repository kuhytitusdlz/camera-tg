import os
import time
import mimetypes
import httpx

from modules.env_config import TG_TOKEN, TG_CHAT_ID, TG_SILENT_MODE, DEBUG
from modules.logger import log


def _safe_url(url: str) -> str:
    """Hide secrets in URLs unless DEBUG is enabled."""
    if DEBUG:
        return url
    if not url:
        return url
    # Telegram bot token is part of path: .../bot<token>/...
    if TG_TOKEN:
        return url.replace(TG_TOKEN, "<redacted>")
    return url


def _tg_trunc(s: str, max_len: int = 2500) -> str:
    try:
        s = s if s is not None else ""
        if len(s) > max_len:
            return s[:max_len] + "...[truncated]"
        return s
    except Exception:
        return "<unprintable>"


def _tg_resp_debug(status_code: int, headers: dict, text: str) -> str:
    try:
        ct = (headers or {}).get("content-type", "")
    except Exception:
        ct = ""
    return f"status={status_code} content-type={ct} body={_tg_trunc(text)!r}"


def _to_int(v: str, default: int) -> int:
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _to_float(v: str, default: float) -> float:
    try:
        return float(str(v).strip())
    except Exception:
        return default


# -----------------------------
# Telegram HTTP tuning (env)
# -----------------------------
TG_CONNECT_TIMEOUT = _to_float(os.getenv("TG_CONNECT_TIMEOUT", "10"), 10.0)
TG_READ_TIMEOUT = _to_float(os.getenv("TG_READ_TIMEOUT", "600"), 600.0)
# Отдельный write-timeout важен именно для upload.
TG_WRITE_TIMEOUT = _to_float(os.getenv("TG_WRITE_TIMEOUT", str(TG_READ_TIMEOUT)), TG_READ_TIMEOUT)

TG_RETRIES = _to_int(os.getenv("TG_RETRIES", "2"), 2)
TG_RETRY_BACKOFF_SEC = _to_float(os.getenv("TG_RETRY_BACKOFF_SEC", "2"), 2.0)

# Прогресс и размер чанка для upload
TG_UPLOAD_PROGRESS = os.getenv("TG_UPLOAD_PROGRESS", "0").strip() == "1"
TG_UPLOAD_PROGRESS_INTERVAL_SEC = _to_float(os.getenv("TG_UPLOAD_PROGRESS_INTERVAL_SEC", "2.0"), 2.0)
TG_UPLOAD_CHUNK_SIZE = _to_int(os.getenv("TG_UPLOAD_CHUNK_SIZE", str(256 * 1024)), 256 * 1024)


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=TG_CONNECT_TIMEOUT,
        read=TG_READ_TIMEOUT,
        write=TG_WRITE_TIMEOUT,
        pool=TG_CONNECT_TIMEOUT,
    )


def _client() -> httpx.Client:
    # http2=False: проще диагностика и более предсказуемый upload
    return httpx.Client(timeout=_timeout(), http2=False)


def _fmt_bytes(x: float) -> str:
    try:
        x = float(x)
    except Exception:
        return str(x)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024.0:
            return f"{x:.1f}{u}"
        x /= 1024.0
    return f"{x:.1f}PB"


def _bool_to_tg(v: bool) -> str:
    return "true" if v else "false"


def _tg_post_simple(url: str, *, data=None, files=None, json=None) -> httpx.Response:
    last_exc = None
    for attempt in range(1, TG_RETRIES + 1):
        try:
            with _client() as c:
                return c.post(url, data=data, files=files, json=json)
        except Exception as e:
            last_exc = e
            log(f"⚠️ TG request exception (attempt {attempt}/{TG_RETRIES}): {type(e).__name__}: {e!r}")
            if attempt < TG_RETRIES:
                time.sleep(TG_RETRY_BACKOFF_SEC)
    raise RuntimeError(
        f"httpx.post failed url={_safe_url(url)} attempts={TG_RETRIES} err={type(last_exc).__name__}: {last_exc!r}"
    ) from last_exc


def _multipart_stream(*, fields: dict, file_field: str, file_path: str, boundary: str, chunk_size: int):
    """
    Ручной multipart/form-data с чанками — чтобы прогресс отражал реальную отправку.
    """
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    # поля
    parts = []
    for k, v in (fields or {}).items():
        if v is None:
            continue
        p = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{k}\"\r\n\r\n"
            f"{v}\r\n"
        ).encode("utf-8")
        parts.append(p)

    file_hdr = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"{file_field}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")

    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")

    content_length = sum(len(p) for p in parts) + len(file_hdr) + file_size + len(tail)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(content_length),
    }

    def gen():
        sent_total = 0
        t0 = time.time()
        t_last = t0

        def maybe_progress(force: bool = False):
            nonlocal t_last
            if not TG_UPLOAD_PROGRESS and not force:
                return
            now = time.time()
            if not force and (now - t_last) < TG_UPLOAD_PROGRESS_INTERVAL_SEC:
                return
            dt = max(0.001, now - t0)
            rate = sent_total / dt
            pct = (sent_total / max(1, content_length)) * 100.0
            log(
                f"⬆️ upload {filename}: {_fmt_bytes(sent_total)}/{_fmt_bytes(content_length)} "
                f"({pct:.1f}%) avg~{_fmt_bytes(rate)}/s"
            )
            t_last = now

        for p in parts:
            sent_total += len(p)
            yield p
            maybe_progress()

        sent_total += len(file_hdr)
        yield file_hdr
        maybe_progress()

        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                sent_total += len(chunk)
                yield chunk
                maybe_progress()

        sent_total += len(tail)
        yield tail
        maybe_progress(force=True)

    return headers, gen(), content_length, filename, file_size


def _tg_post_streaming(url: str, *, fields: dict, file_field: str, file_path: str) -> httpx.Response:
    last_exc = None

    for attempt in range(1, TG_RETRIES + 1):
        boundary = "----camera_tg_" + os.urandom(8).hex()
        try:
            headers, content_iter, content_length, filename, file_size = _multipart_stream(
                fields=fields,
                file_field=file_field,
                file_path=file_path,
                boundary=boundary,
                chunk_size=TG_UPLOAD_CHUNK_SIZE,
            )

            log(
                f"➡️ TG upload start: file={file_path} size={file_size} total_multipart={content_length} "
                f"attempt={attempt}/{TG_RETRIES}"
            )

            with _client() as c:
                return c.post(url, headers=headers, content=content_iter)

        except Exception as e:
            last_exc = e
            log(f"⚠️ TG request exception (attempt {attempt}/{TG_RETRIES}): {type(e).__name__}: {e!r}")
            if attempt < TG_RETRIES:
                time.sleep(TG_RETRY_BACKOFF_SEC)

    raise RuntimeError(
        f"httpx.post(stream) failed url={_safe_url(url)} attempts={TG_RETRIES} err={type(last_exc).__name__}: {last_exc!r}"
    ) from last_exc


def send_telegram_message(text: str):
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "disable_notification": _bool_to_tg(TG_SILENT_MODE == 0),
        "disable_web_page_preview": _bool_to_tg(True),
    }
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

    resp = _tg_post_simple(url, data=payload)

    if resp.status_code < 200 or resp.status_code >= 300:
        log(f"⚠️ TG sendMessage HTTP error: {_tg_resp_debug(resp.status_code, dict(resp.headers), resp.text)}")
        resp.raise_for_status()

    result = resp.json()
    if not result.get("ok", False):
        log(f"⚠️ TG sendMessage ok=false: {result}")
        raise Exception(result)

    log(f"Sent message: {text}")


def send_snapshot():
    from modules.env_config import SNAPSHOT_URL

    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=10.0, write=10.0, pool=10.0), http2=False) as c:
        snap = c.get(SNAPSHOT_URL)
        snap.raise_for_status()

    data = {
        "chat_id": TG_CHAT_ID,
        "disable_notification": _bool_to_tg(TG_SILENT_MODE == 0),
    }
    files = {"photo": ("snapshot.jpg", snap.content, "image/jpeg")}
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"

    resp = _tg_post_simple(url, data=data, files=files)

    if resp.status_code < 200 or resp.status_code >= 300:
        log(f"⚠️ TG sendPhoto HTTP error: {_tg_resp_debug(resp.status_code, dict(resp.headers), resp.text)}")
        resp.raise_for_status()

    result = resp.json()
    if not result.get("ok", False):
        log(f"⚠️ TG sendPhoto ok=false: {result}")
        raise Exception(result)

    log("Sent snapshot")


def send_preview_image(preview_path: str):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    data = {
        "chat_id": TG_CHAT_ID,
        "disable_notification": _bool_to_tg(TG_SILENT_MODE == 0),
    }

    with open(preview_path, "rb") as f:
        files = {"photo": (os.path.basename(preview_path), f, "image/jpeg")}
        resp = _tg_post_simple(url, data=data, files=files)

    if resp.status_code < 200 or resp.status_code >= 300:
        log(
            f"⚠️ TG sendPhoto(preview) HTTP error: file={preview_path} "
            f"{_tg_resp_debug(resp.status_code, dict(resp.headers), resp.text)}"
        )
        resp.raise_for_status()

    result = resp.json()
    if not result.get("ok", False):
        log(f"⚠️ TG sendPhoto(preview) ok=false: file={preview_path} result={result}")
        raise Exception(result)

    log(f"Sent preview image: {preview_path}")


def send_video_file(path: str, as_document: bool = False):
    method = "sendDocument" if as_document else "sendVideo"
    file_key = "document" if as_document else "video"
    url = f"https://api.telegram.org/bot{TG_TOKEN}/{method}"

    # Подпись к видео/документу: имя файла без расширения (в имени уже есть дата/время)
    caption = os.path.splitext(os.path.basename(path))[0]

    fields = {
        "chat_id": TG_CHAT_ID,
        "disable_notification": _bool_to_tg(TG_SILENT_MODE == 0),
        "caption": caption,
    }

    try:
        sz = os.path.getsize(path)
    except Exception:
        sz = None
    log(f"➡️ TG {method} start: file={path} size={sz}")

    resp = _tg_post_streaming(url, fields=fields, file_field=file_key, file_path=path)

    if resp.status_code < 200 or resp.status_code >= 300:
        log(
            f"⚠️ TG {method} HTTP error: file={path} "
            f"{_tg_resp_debug(resp.status_code, dict(resp.headers), resp.text)}"
        )
        resp.raise_for_status()

    result = resp.json()
    if not result.get("ok", False):
        log(f"⚠️ TG {method} ok=false: file={path} result={result}")
        raise Exception(result)

    log(f"✅ TG {method} success: {path}")
