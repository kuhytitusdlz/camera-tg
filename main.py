import threading
from dotenv import load_dotenv
import os
import time


load_dotenv()
if os.getenv("TZ"):
    time.tzset()
    
from modules.logging_setup import setup_logging

# Configure stdlib logging (controls 3rd party libs like httpx).
setup_logging()

from modules.record_trigger import record_loop
from modules.onvif_handler import onvif_event_listener
from modules.commands_handler import run as commands_listener
from modules.sender import send_loop
from modules.telegram_utils import send_telegram_message


import signal
import sys

_SENT_STOP = False

def _notify_stop(reason: str | None = None):
    global _SENT_STOP
    if _SENT_STOP:
        return
    _SENT_STOP = True
    try:
        text = "🔴 Бот камеры остановлен"
        if reason:
            text += f": {reason}"
        send_telegram_message(text)
    except Exception:
        pass

def _signal_handler(signum, frame):
    name = {signal.SIGINT: "SIGINT", signal.SIGTERM: "SIGTERM"}.get(signum, str(signum))
    _notify_stop(name)
    # немедленно завершаем процесс (демон-потоки завершатся автоматически)
    sys.exit(0)

# регистрируем обработчики сигналов
signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)
if __name__ == "__main__":
    # уведомление о старте
    try:
        send_telegram_message("🟢 Бот камеры запущен")
    except Exception:
        pass
    threading.Thread(target=record_loop, daemon=True).start()
    threading.Thread(target=onvif_event_listener, daemon=True).start()
    threading.Thread(target=commands_listener, daemon=True).start()
    send_loop()
