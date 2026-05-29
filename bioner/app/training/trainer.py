import time

from app.training.callbacks import send_event


def train_model(request):

    callback = request.callback_url

    for epoch in range(request.num_epochs):

        time.sleep(2)

        send_event(callback, {
            "type": "epoch_update",
            "run_id": request.run_id,
            "epoch": epoch + 1,
            "loss": 0.1,
            "f1": 0.9,
        })

    output_path = f"model_store/runs/model_{request.run_id}"

    send_event(callback, {
        "type": "completed",
        "run_id": request.run_id,
        "output_path": output_path,
    })