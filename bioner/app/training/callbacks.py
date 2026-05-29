import requests


def send_event(callback_url: str, payload: dict):

    try:
        requests.post(
            callback_url,
            json=payload,
            timeout=10,
        )
    except Exception as e:
        print("Callback failed", e)