import time
import os
import httpx
from modules.env_config import (
    TG_TOKEN, TG_CHAT_ID, TG_SILENT_MODE,
    IS_MOTION_ENABLED, IS_TAMPER_ENABLED, ALERT_TIMEOUT,
    ONVIF_ENABLED, SEND_ORIGINAL_MKV, TRIM_START_SECONDS
)
from modules.logger import log

API_URL = f"https://api.telegram.org/bot{TG_TOKEN}"

def handle_command(command, args):
    from modules.env_config import (
        IS_MOTION_ENABLED, IS_TAMPER_ENABLED, ALERT_TIMEOUT,
        ONVIF_ENABLED, SEND_ORIGINAL_MKV, TG_SILENT_MODE,
        TRIM_START_SECONDS, RECORD_ON_ALERT_ONLY
    )
    from modules.telegram_utils import send_snapshot, send_telegram_message
    from modules.record_trigger import trigger_record
    import sys, os

    if command == '/help':
        return (
            "🤖 Доступные команды:\n"
            "/help - показать эту справку\n"
            "/photo - сделать и отправить снимок с камеры\n"
            "/video [минуты] - записать видео (1-30 мин)\n"
            "/env - показать текущие настройки окружения\n"
            "/reboot - перезагрузить контейнер (SIGTERM)\n"
            "/exit - остановить бота (SIGTERM)\n"
        )
    elif command == '/photo':
        try:
            return send_snapshot()
        except:
            return "❌ Ошибка при отправке снимка"
    elif command == '/video':
        try:
            minutes = 1
            if args and args[0].isdigit():
                minutes = min(max(1, int(args[0])), 30)
            send_telegram_message(f"🎥 Начинаю запись видео {minutes} мин...")
            trigger_record(minutes * 60)
            return "✅ Запись завершена"
        except:
            return "❌ Ошибка при записи"
    elif command == '/env':
        return (
            f"IS_MOTION_ENABLED = {IS_MOTION_ENABLED}\n"
            f"IS_TAMPER_ENABLED = {IS_TAMPER_ENABLED}\n"
            f"ONVIF_ENABLED = {ONVIF_ENABLED}\n"
            f"SEND_ORIGINAL_MKV = {SEND_ORIGINAL_MKV}\n"
            f"TRIM_START_SECONDS = {TRIM_START_SECONDS}\n"
            f"ALERT_TIMEOUT = {ALERT_TIMEOUT}\n"
            f"TG_SILENT_MODE = {TG_SILENT_MODE}\n"
            f"RECORD_ON_ALERT_ONLY = {RECORD_ON_ALERT_ONLY}\n"
            f"ALERT_RECORD_SECONDS = {__import__('modules.env_config').env_config.ALERT_RECORD_SECONDS}\n"
            f"CONTINUOUS_SEGMENT_SECONDS = {__import__('modules.env_config').env_config.CONTINUOUS_SEGMENT_SECONDS}\n"
            f"TG_MAX_FILE_MB = {__import__('modules.env_config').env_config.TG_MAX_FILE_MB}\n"
            f"TG_SPLIT_SAFETY = {__import__('modules.env_config').env_config.TG_SPLIT_SAFETY}\n"
        )
    elif command == '/toggle_motion':
        if not IS_MOTION_ENABLED:
            return "❌ Функция детекции движения отключена в конфиге"
        os.environ['IS_MOTION_ENABLED'] = '0' if IS_MOTION_ENABLED else '1'
        return f"🔄 Motion detection {'off' if IS_MOTION_ENABLED else 'on'}"
    elif command == '/toggle_tamper':
        if not IS_TAMPER_ENABLED:
            return "❌ Функция детекции подмены отключена в конфиге"
        os.environ['IS_TAMPER_ENABLED'] = '0' if IS_TAMPER_ENABLED else '1'
        return f"🔄 Tamper detection {'off' if IS_TAMPER_ENABLED else 'on'}"
    elif command == '/toggle_onvif':
        if not ONVIF_ENABLED:
            return "❌ ONVIF-оповещения отключены в конфиге"
        os.environ['ONVIF_ENABLED'] = '0' if ONVIF_ENABLED else '1'
        return f"🔄 ONVIF alerts {'off' if ONVIF_ENABLED else 'on'}"
    elif command == '/toggle_mkv':
        os.environ['SEND_ORIGINAL_MKV'] = '0' if SEND_ORIGINAL_MKV else '1'
        return f"🔄 Send original MKV {'off' if SEND_ORIGINAL_MKV else 'on'}"
    elif command == '/set_trim':
        if not args or not args[0].isdigit():
            return "❌ Укажите число секунд для обрезки старта видео"
        seconds = max(0, min(60, int(args[0])))
        os.environ['TRIM_START_SECONDS'] = str(seconds)
        return f"✂️ Trim start seconds set to {seconds}"
    elif command == '/status':
        parts = []
        parts.append(f"Motion: {'✅' if IS_MOTION_ENABLED else '❌'}")
        parts.append(f"Tamper: {'✅' if IS_TAMPER_ENABLED else '❌'}")
        parts.append(f"ONVIF: {'✅' if ONVIF_ENABLED else '❌'}")
        parts.append(f"MKV send: {'✅' if SEND_ORIGINAL_MKV else '❌'}")
        return "\n".join(parts)
    elif command == '/reboot':
        from modules.telegram_utils import send_telegram_message
        send_telegram_message("♻️ Перезагружаю контейнер...")
        import os, signal; os.kill(os.getpid(), signal.SIGTERM)
    elif command == '/exit':
        from modules.telegram_utils import send_telegram_message
        send_telegram_message("⏹ Останавливаю бота по команде /exit…")
        import os, signal; os.kill(os.getpid(), signal.SIGTERM)
    else:
        return "Неизвестная команда. Используй /help для списка."

def run():
    from modules.env_config import TG_TOKEN, TG_CHAT_ID
    from modules.telegram_utils import send_telegram_message

    if not TG_TOKEN or not TG_CHAT_ID:
        log("⚠️ TG_TOKEN/TG_CHAT_ID пусты. Обработчик команд Telegram отключен.")
        return

    offset = None
    log("🔧 Telegram command handler started")

    timeout = httpx.Timeout(connect=5.0, read=40.0, write=40.0, pool=5.0)

    with httpx.Client(timeout=timeout, http2=False) as client:
        while True:
            params = {
                'timeout': 30,
                'allowed_updates': ['message']
            }
            if offset:
                params['offset'] = offset

            try:
                log("⌛ Telegram: polling for updates")
                resp = client.get(f"{API_URL}/getUpdates", params=params)
                resp.raise_for_status()
                data = resp.json()
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                log(f"❌ Polling error: {e}. retry in 5s")
                time.sleep(5)
                continue
            except ValueError as e:
                log(f"❌ JSON parse error: {e}. retry in 5s")
                time.sleep(5)
                continue

            for update in data.get('result', []):
                offset = update.get('update_id', 0) + 1
                msg = update.get('message')
                if not msg or str(msg.get('chat', {}).get('id')) != str(TG_CHAT_ID):
                    continue

                text = (msg.get('text') or '').strip()
                if not text.startswith('/'):
                    continue

                parts = text.split()
                cmd = parts[0].split('@')[0]
                args = parts[1:]

                reply = handle_command(cmd, args)
                if reply is None:
                    continue

                try:
                    send_telegram_message(reply)
                    log("Sent message")
                except Exception as e:
                    log(f"⚠️ Ошибка отправки сообщения: {e}")

            time.sleep(0.1)
