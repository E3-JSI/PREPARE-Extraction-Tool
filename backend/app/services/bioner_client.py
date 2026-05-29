import requests
from app.core.settings import settings


def start_training(payload: dict):
    response = requests.post(
        f"{settings.BIONER_HOST}/training/start",
        json=payload,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def stop_training(run_id: int):
    response = requests.post(
        f"{settings.BIONER_HOST}/training/stop/{run_id}",
        timeout=10,
    )

    response.raise_for_status()

    return response.json()