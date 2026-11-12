"""Download the BGE model snapshot from ModelScope into the local cache."""

import sys
import urllib.request
from pathlib import Path

MODEL_ID = "BAAI/bge-small-zh-v1.5"
BASE_URL = (
    "https://www.modelscope.cn/models/"
    "BAAI/bge-small-zh-v1.5/resolve/master"
)
FILES = (
    "config.json",
    "config_sentence_transformers.json",
    "configuration.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "1_Pooling/config.json",
)


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    target_root = (
        project_root
        / "storage"
        / "models"
        / MODEL_ID.replace("/", "--")
    )

    for relative_path in FILES:
        target = target_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.stat().st_size > 0:
            print(f"cached {relative_path}")
            continue

        url = f"{BASE_URL}/{relative_path}"
        temporary = target.with_suffix(target.suffix + ".tmp")
        print(f"downloading {relative_path}")
        try:
            urllib.request.urlretrieve(url, temporary)
            temporary.replace(target)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            print(
                f"failed to download {relative_path}: {type(exc).__name__}",
                file=sys.stderr,
            )
            return 1

    total_bytes = sum(
        path.stat().st_size
        for path in target_root.rglob("*")
        if path.is_file()
    )
    print(f"model_ready={target_root}")
    print(f"model_bytes={total_bytes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

