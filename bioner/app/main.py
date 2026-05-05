import litserve as ls
import logging
from argparse import ArgumentParser, ArgumentTypeError

from app.interfaces import NERRequest
from app.model_manager import get_model_manager
from app.routes_model_management import router as model_router

logging.basicConfig(level=logging.INFO)


def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    if v.lower() in ("no", "false", "f", "n", "0"):
        return False
    raise ArgumentTypeError("Boolean value expected.")


class NERAPI(ls.LitAPI):
    def __init__(self, 
                 engine: str | None = None, 
                 model: str | None = None, 
                 adapter_model: str | None = None,
                 prompt_path: str | None = None,
                 use_gpu: bool = False):
        super().__init__()
        self.engine = engine
        self.model_path = model
        self.adapter_model = adapter_model
        self.prompt_path = prompt_path
        self.use_gpu = use_gpu
        self.model_manager = get_model_manager()

    def setup(self, device):
        if self.engine and self.model_path:
            try:
                self.model_manager.switch_model(
                    engine=self.engine,
                    model=self.model_path,
                    adapter_model=self.adapter_model,
                    use_gpu=self.use_gpu
                )
                logging.info(f"Initial model loaded: {self.engine} - {self.model_path}")
            except Exception as e:
                logging.error(f"Failed to load initial model: {e}")
        else:
            logging.info("No initial model specified. Use /models/switch to load a model.")

    def decode_request(self, request: NERRequest) -> dict:
        return {
            "medical_text": request.medical_text,
            "labels": request.labels or [],
        }

    def predict(self, inputs: dict) -> dict:
        model = self.model_manager.get_model()
        if model is None:
            raise RuntimeError("No model is currently loaded. Use /models/switch to load a model.")
        
        return model.extract_entities(
            medical_text=inputs["medical_text"], 
            labels=inputs["labels"]
        )

    def encode_response(self, output):
        return output


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "--engine",
        type=str,
        choices=["huggingface", "gliner", "gliner2"],
        default=None,
        help="Type of model to use"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Path to the model to use"
    )
    parser.add_argument(
        "--adapter_model",
        type=str,
        help="Path to the LLM adapter to use (if any)"
    )
    parser.add_argument(
        "--prompt_path",
        type=str,
        help="Path to the prompts file to use (if any)"
    )
    parser.add_argument(
        "--use_gpu",
        type=str2bool,
        default=False,
        help="Flag to use GPU for inference"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to run the server on"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run the server on"
    )
    args = parser.parse_args()
    api = NERAPI(
        engine=args.engine,
        model=args.model,
        adapter_model=args.adapter_model,
        prompt_path=args.prompt_path,
        use_gpu=args.use_gpu
    )
    server = ls.LitServer(api, accelerator="auto", timeout=300, api_path="/ner")

    server.app.include_router(model_router)

    server.run(host=args.host, port=args.port)
