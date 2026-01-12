import time
import httpx
from zeep import exceptions as zeep_exceptions
from zeep.helpers import serialize_object
from onvif import ONVIFCamera
from lxml import etree

from modules.env_config import (
    ONVIF_ENABLED,
    ONVIF_HOST,
    ONVIF_PORT,
    ONVIF_USER,
    ONVIF_PASS,
    SNAPSHOT_URL,
    ONVIF_LOG_LEVEL,
    IS_MOTION_ENABLED,
    IS_TAMPER_ENABLED,
    ALERT_TIMEOUT,
    TG_TOKEN,
    TG_CHAT_ID,
    TG_SILENT_MODE,
)
from modules.logger import log
from modules.record_trigger import alert_event

API_URL = f"https://api.telegram.org/bot{TG_TOKEN}"


def _get_message_element(notification_message):
    """
    Из NotificationMessage достаём XML-элемент Message (_value_1).

    У разных версий zeep / onvif объекты могут выглядеть как dict
    или как объект с атрибутом Message, внутри которого лежит _value_1 (сырое XML).
    """
    any_message = None

    # object-style доступ: nm.Message
    try:
        any_message = getattr(notification_message, "Message", None)
    except Exception:
        any_message = None

    # dict-style: nm['Message']
    if any_message is None:
        try:
            any_message = notification_message["Message"]
        except Exception:
            any_message = None

    if isinstance(any_message, dict):
        return any_message.get("_value_1")

    return getattr(any_message, "_value_1", None)


def _is_truthy(val: str) -> bool:
    """
    Интерпретируем только строку 'true' (без 1/yes/on).
    """
    return (val or "").strip().lower() == "true"


def _classify_event(el):
    """
    Универсальная классификация события:
    - motion_alert: любые Motion / LogicalState цифрового входа
    - tamper_alert: любые Tamper
    """
    motion_alert = False
    tamper_alert = False

    # Собираем все SimpleItem
    simple_items = el.findall('.//{*}SimpleItem')
    items = []
    for si in simple_items:
        name = (si.get("Name") or "").strip()
        value = (si.get("Value") or "").strip()
        if not name:
            continue
        items.append((name, value))

    # 1) Motion / Tamper по имени
    for name, value in items:
        lname = name.lower()
        if IS_MOTION_ENABLED and "motion" in lname and _is_truthy(value):
            motion_alert = True
        if IS_TAMPER_ENABLED and "tamper" in lname and _is_truthy(value):
            tamper_alert = True

    # 2) Цифровой вход: InputToken / DIGIT_INPUT + LogicalState=true
    if IS_MOTION_ENABLED and not motion_alert:
        has_input = any(
            n.lower() in ("inputtoken", "input_token") or "digit_input" in v.lower()
            for n, v in items
        )
        logical_true = any(
            n.lower() == "logicalstate" and _is_truthy(v)
            for n, v in items
        )
        if has_input and logical_true:
            motion_alert = True

    return motion_alert, tamper_alert


def create_onvif_connection():
    cam = ONVIFCamera(ONVIF_HOST, ONVIF_PORT, ONVIF_USER, ONVIF_PASS)
    events_service = cam.create_events_service()
    # простая подписка без фильтра — чтобы ловить всё (включая Motion)
    events_service.CreatePullPointSubscription()
    pullpoint = cam.create_pullpoint_service()
    log("📡 ONVIF подписка активна")
    return pullpoint


def onvif_event_listener():
    if not ONVIF_ENABLED:
        log("ONVIF выключен (ONVIF_ENABLED=0), слушатель не запускается")
        return

    pullpoint = None
    last_alert = 0.0

    while True:
        if pullpoint is None:
            try:
                pullpoint = create_onvif_connection()
            except Exception as e:
                log(f"Ошибка инициализации ONVIF: {e}. Повтор через 10 сек.")
                time.sleep(10)
                continue

        try:
            # Timeout в миллисекундах
            messages = pullpoint.PullMessages({"Timeout": 2000, "MessageLimit": 5})

            # Уровень логирования ONVIF (debug)
            if ONVIF_LOG_LEVEL == 1:
                try:
                    msg_dict = serialize_object(messages)
                    log(f"ONVIF JSON: {msg_dict}")
                    for nm in getattr(messages, "NotificationMessage", []):
                        el = _get_message_element(nm)
                        if el is not None:
                            xml_str = etree.tostring(
                                el, pretty_print=True, encoding="unicode"
                            )
                            log(f"ONVIF XML:\n{xml_str}")
                except Exception as ex:
                    log(f"Ошибка логирования ONVIF debug: {ex}")

            # Основная обработка событий
            for nm in getattr(messages, "NotificationMessage", []):
                el = _get_message_element(nm)
                now = time.time()

                if el is None:
                    continue

                motion_alert, tamper_alert = _classify_event(el)

                if motion_alert or tamper_alert:
                    # триггерим запись
                    alert_event.set()

                    # антифлуд по ALERT_TIMEOUT
                    if now - last_alert >= ALERT_TIMEOUT:
                        try:
                            with httpx.Client(
                                timeout=httpx.Timeout(connect=10.0, read=10.0, write=10.0, pool=10.0),
                                http2=False,
                            ) as c:
                                snap = c.get(SNAPSHOT_URL)
                                snap.raise_for_status()

                            files = {
                                'photo': ('alert.jpg', snap.content, 'image/jpeg'),
                            }

                            caption_parts = []
                            if motion_alert:
                                caption_parts.append('Motion')
                            if tamper_alert:
                                caption_parts.append('Tamper')

                            caption = f"🚨 ONVIF Alert: {', '.join(caption_parts)}"

                            data = {
                                'chat_id': TG_CHAT_ID,
                                'caption': caption,
                                'disable_notification': 'true' if (TG_SILENT_MODE == 0) else 'false',
                            }

                            with httpx.Client(
                                timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=10.0),
                                http2=False,
                            ) as c:
                                tg = c.post(f"{API_URL}/sendPhoto", data=data, files=files)
                                tg.raise_for_status()

                            log(f"Sent ONVIF alert photo: {caption}")
                        except Exception as e:
                            log(f"Ошибка отправки alert-photo: {e}")
                        last_alert = now

        except zeep_exceptions.Fault as fault:
            log(f"ONVIF Fault: {fault}")
        except Exception as e:
            log(
                f"Ошибка при получении событий ONVIF: {e}. Пересоздание соединения через 10 сек."
            )
            pullpoint = None
            time.sleep(10)
            continue

        time.sleep(0.1)
