import litserve as ls
import logging
import threading
from argparse import ArgumentParser, ArgumentTypeError
from app.interfaces import NERRequest
from app.engines import build_engine
from app.model_manager import STATE_PATH, read_desired, read_model_metadata, write_desired
from app.routes_model import register_model_context, router as model_router
from app.routes_training import router as training_router
from app.worker_supervisor import start_worker_supervisor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
                 engine: str,
                 model: str,
                 adapter_model: str | None = None,
                 prompt_path: str | None = None,
                 use_gpu: bool = False,
                 api_path: str = "/ner"):
        super().__init__(api_path=api_path)
        self.engine = engine
        self.model = model
        self.adapter_model = adapter_model
        self.prompt_path = prompt_path
        self.use_gpu = use_gpu
        # Active-model swap bookkeeping (used inside the inference worker).
        self.default_model = model
        self.active_model = model
        self._swap_lock = threading.Lock()
        self._state_mtime = None

    def __getstate__(self):
        # litserve spawns the inference worker and pickles this LitAPI to ship it
        # across; a threading.Lock can't be pickled, so drop it and recreate it in
        # the worker via __setstate__.
        state = self.__dict__.copy()
        state.pop("_swap_lock", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._swap_lock = threading.Lock()

    def setup(self, device):
        self.model = build_engine(
            engine=self.engine,
            model=self.active_model,
            adapter_model=self.adapter_model,
            prompt_path=self.prompt_path,
            use_gpu=self.use_gpu)

    def _maybe_swap_model(self):
        """Hot-swap the in-memory engine when the desired model has changed.

        Reads the shared state file (guarded by a cheap mtime check). On a load
        failure the previously loaded model is kept and the desired state is
        reset to it, so the service stays up and does not retry a broken model on
        every request. Must be called while holding ``self._swap_lock`` so a swap
        never races a concurrent inference.
        """
        try:
            mtime = STATE_PATH.stat().st_mtime
        except OSError:
            return
        if mtime == self._state_mtime:
            return
        self._state_mtime = mtime

        desired = read_desired()
        if not desired:
            return
        target = desired.get("model") or self.default_model
        if target == self.active_model:
            return

        logger.info("Activating NER model: %s", target)
        try:
            new_model = build_engine(
                engine=self.engine,
                model=target,
                adapter_model=self.adapter_model,
                prompt_path=self.prompt_path,
                use_gpu=self.use_gpu)
        except Exception as exc:
            logger.error(
                "Failed to load model '%s': %s; keeping '%s'",
                target, exc, self.active_model)
            # Revert desired state so we don't retry a broken model every call.
            write_desired(self.active_model, read_model_metadata(self.active_model))
            return
        self.model = new_model
        self.active_model = target

    def decode_request(self, request: NERRequest) -> dict:
        return {
            "medical_text": request.medical_text,
            "labels": request.labels or [],
        }

    def predict(self, inputs: dict) -> dict:
        # Serialize model swap + inference so a switch never happens mid-request.
        with self._swap_lock:
            self._maybe_swap_model()
            return self.model.extract_entities(medical_text=inputs["medical_text"],
                                               labels=inputs["labels"])

    def encode_response(self, output):
        return output

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--engine", # previously model_type
                        type=str,
                        # "gliner2" is not fully implemented yet — disabled until ready.
                        choices=["huggingface", "gliner"],
                        help="Type of model to use: 'huggingface' for Hugging Face LLM models or 'gliner' for GLiNER model."
    )
    parser.add_argument("--model", # previously model_path
                        type=str,
                        help="Path to the model to use. (Huggingface path)"
                        )
    parser.add_argument("--adapter_model", # previously adapter_path
                        type=str,
                        help="Path to the LLM adapter to use (if any)."
                        )
    parser.add_argument("--prompt_path",
                        type=str,
                        help="Path to the prompts file to use (if any)."
                        )
    parser.add_argument("--use_gpu",
                        type=str2bool,
                        default=False,
                        help="Flag to use GPU for inference."
                        )
    parser.add_argument("--host",
                        type=str,
                        default="0.0.0.0",
                        help="Host to run the server on."
                        )
    parser.add_argument("--port",
                        type=int,
                        default=8000,
                        help="Port to run the server on."
                        )
    args = parser.parse_args()
    model_metadata = read_model_metadata(args.model)
    api = NERAPI(
        engine=args.engine,
        model=args.model,
        adapter_model=args.adapter_model,
        prompt_path=args.prompt_path,
        use_gpu=args.use_gpu,
        api_path="/ner"
    )
    server = ls.LitServer(
        api,
        accelerator="auto",
        timeout=300,
        info_path="/model/info",
        model_metadata=model_metadata
    )
    server.app.include_router(training_router)
    server.app.include_router(model_router)
    # Wire the activate route and reset the desired-model state to the default so
    # a stale state file from a previous run can't change the startup model.
    register_model_context(server, args.model, args.engine)
    write_desired(args.model, model_metadata)
    # Exit on inference-worker death so the container restart policy recovers.
    start_worker_supervisor()
    server.run(host=args.host, port=args.port)
