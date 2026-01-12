import os
import time
import logging

from onvif import ONVIFCamera
from lxml import etree

# Берём параметры камеры из окружения
ONVIF_HOST = os.getenv("ONVIF_HOST", "192.168.100.102")
ONVIF_PORT = int(os.getenv("ONVIF_PORT", "8899"))
ONVIF_USER = os.getenv("ONVIF_USER", "admin")
ONVIF_PASS = os.getenv("ONVIF_PASS", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _walk_topics(node, path="", results=None):
    """
    Рекурсивный обход TopicSet — просто чтобы один раз увидеть, какие есть топики.
    """
    if results is None:
        results = []

    tag = getattr(node, "tag", None)
    try:
        children = list(node)
    except TypeError:
        children = []

    if tag:
        local_name = tag.split("}")[-1]
        new_path = f"{path}/{local_name}" if path else local_name
    else:
        new_path = path

    if not children and new_path:
        results.append(new_path)
        return results

    for child in children:
        _walk_topics(child, new_path, results)

    return results


def _get_message_element(notification_message):
    """
    Из NotificationMessage достаем XML-элемент Message (_value_1).
    """
    any_message = getattr(notification_message, "Message", None)
    if isinstance(any_message, dict):
        return any_message.get("_value_1")
    return getattr(any_message, "_value_1", None)


def main():
    logging.info("Подключаюсь к камере %s:%s ...", ONVIF_HOST, ONVIF_PORT)
    cam = ONVIFCamera(ONVIF_HOST, ONVIF_PORT, ONVIF_USER, ONVIF_PASS)

    # 1) GetEventProperties — один раз посмотреть, что вообще есть
    try:
        events_service = cam.create_events_service()
        logging.info("Запрашиваю GetEventProperties ...")
        props = events_service.GetEventProperties()

        print("=== GetEventProperties (сокращённо) ===")
        print({
            "TopicNamespaceLocation": props.TopicNamespaceLocation,
            "FixedTopicSet": props.FixedTopicSet,
            "MessageContentFilterDialect": props.MessageContentFilterDialect,
            "MessageContentSchemaLocation": props.MessageContentSchemaLocation,
        })

        # Дерево топиков, чтобы знать, какие Motion/Alarm есть
        topic_set = getattr(props, "TopicSet", None)
        if topic_set is not None:
            print("\n=== TopicSet (пути топиков) ===")
            roots = getattr(topic_set, "_value_1", [])
            all_paths = []
            for root in roots:
                _walk_topics(root, "", all_paths)
            for p in sorted(set(all_paths)):
                print("  ", p)
    except Exception as e:
        logging.warning("Не удалось получить GetEventProperties: %s", e)

    # 2) Подписка + PullPoint
    logging.info("Создаю PullPoint-сервис ...")
    events_service = cam.create_events_service()
    try:
        # без фильтра — ловим всё
        events_service.CreatePullPointSubscription()
    except Exception as e:
        logging.warning("CreatePullPointSubscription error: %s", e)

    pullpoint = cam.create_pullpoint_service()
    logging.info("Subscribed to events, start pulling...")

    while True:
        try:
            res = pullpoint.PullMessages({
                "Timeout": "PT10S",
                "MessageLimit": 10,
            })
        except Exception as e:
            logging.error("PullMessages error: %s", e)
            time.sleep(5)
            continue

        msgs = getattr(res, "NotificationMessage", None)
        if not msgs:
            continue

        for nm in msgs:
            print("-" * 80)

            # Topic — без выкрутасов
            topic_obj = getattr(nm, "Topic", None)
            topic_val = getattr(topic_obj, "_value_1", None)
            print("Topic:", topic_val if topic_val is not None else topic_obj)

            # Само сообщение
            el = _get_message_element(nm)
            if el is None:
                print("Нет XML элемента (_value_1) в Message")
                continue

            xml_str = etree.tostring(el, pretty_print=True, encoding="unicode")
            print("RAW XML:")
            print(xml_str)

            # Все SimpleItem
            simple_items = el.findall('.//{*}SimpleItem')
            if simple_items:
                print("SimpleItems:")
                for item in simple_items:
                    name = item.get("Name")
                    value = item.get("Value")
                    print(f"  {name} = {value}")

        time.sleep(1)


if __name__ == "__main__":
    main()
