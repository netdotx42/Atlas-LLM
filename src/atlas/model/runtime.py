import shutil
import urllib.request
from pathlib import Path

from atlas.config import Settings


class ModelUnavailable(RuntimeError):
    pass


def model_url(settings: Settings) -> str:
    return f"https://huggingface.co/{settings.model_repo}/resolve/main/{settings.model_file}"


class LlamaCompleter:
    """Phi-3.5-mini (MIT, about 3.8B) through llama.cpp. Drafts only."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._llm = None

    def status(self) -> dict:
        path = self.settings.resolved_model_path
        return {
            "runtime": "llama.cpp",
            "model": "Phi-3.5-mini-instruct",
            "parameters": "3.8B",
            "license": "MIT",
            "file": self.settings.model_file,
            "path": str(path),
            "ready": path.is_file(),
            "embeddings": "feature-hash",
            "executes": False,
        }

    def complete(self, prompt: str) -> str:
        path = self.settings.resolved_model_path
        if not path.is_file():
            raise ModelUnavailable(f"No local model at {path}. Run: atlas pull-model")
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise ModelUnavailable(
                "llama-cpp-python is not installed. Run: uv sync --extra model"
            ) from exc
        if self._llm is None:
            self._llm = Llama(
                model_path=str(path),
                n_ctx=self.settings.model_n_ctx,
                verbose=False,
                chat_format="phi-3",
            )
        result = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": "Return one JSON object. Do not explain it."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=self.settings.model_max_tokens,
        )
        return str(result["choices"][0]["message"]["content"])


def pull_model(settings: Settings) -> Path:
    dest = settings.resolved_model_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(dest.suffix + ".partial")
    request = urllib.request.Request(model_url(settings), headers={"User-Agent": "atlas"})
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    temporary.replace(dest)
    return dest
