"""Download the BGE reranker snapshot from ModelScope into local cache."""

import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MODEL_ID = "BAAI/bge-reranker-base"
API_URL = f"https://www.modelscope.cn/api/v1/models/{MODEL_ID}/repo/files?Revision=master"
BASE_URL = (
    "https://www.modelscope.cn/models/"
    "BAAI/bge-reranker-base/resolve/master"
)
PART_SIZE = 32 * 1024 * 1024
PARALLEL_PARTS = 16
FILES = (
    "config.json",
    "configuration.json",
    "model.safetensors",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)


def remote_file_sizes() -> dict[str, int]:
    with urllib.request.urlopen(API_URL, timeout=30) as response:
        payload = json.load(response)
    return {
        item["Path"]: int(item["Size"])
        for item in payload["Data"]["Files"]
        if item["Type"] == "blob"
    }


def download_part(
    *,
    url: str,
    path: Path,
    start: int,
    end: int,
) -> None:
    expected_size = end - start + 1
    if path.is_file() and path.stat().st_size == expected_size:
        return
    partial = path.with_suffix(path.suffix + ".download")
    downloaded = partial.stat().st_size if partial.is_file() else 0
    if downloaded >= expected_size:
        partial.replace(path)
        return
    request = urllib.request.Request(
        url,
        headers={"Range": f"bytes={start + downloaded}-{end}"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        with partial.open("ab") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
    if not partial.is_file() or partial.stat().st_size != expected_size:
        raise OSError(
            f"Incomplete range {start}-{end}"
        )
    partial.replace(path)


def download_large_file(
    *,
    url: str,
    target: Path,
    expected_size: int,
) -> None:
    ranges = [
        (start, min(start + PART_SIZE - 1, expected_size - 1))
        for start in range(0, expected_size, PART_SIZE)
    ]
    part_paths = [
        target.with_suffix(target.suffix + f".part.{index:03d}")
        for index in range(len(ranges))
    ]

    with ThreadPoolExecutor(max_workers=PARALLEL_PARTS) as pool:
        futures = [
            pool.submit(
                download_part,
                url=url,
                path=part_path,
                start=start,
                end=end,
            )
            for part_path, (start, end) in zip(
                part_paths,
                ranges,
                strict=True,
            )
        ]
        for future in as_completed(futures):
            future.result()

    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("wb") as output:
        for part_path in part_paths:
            with part_path.open("rb") as part:
                while block := part.read(1024 * 1024):
                    output.write(block)
    if temporary.stat().st_size != expected_size:
        raise OSError("Combined model size does not match remote metadata")
    os.replace(temporary, target)
    for part_path in part_paths:
        part_path.unlink(missing_ok=True)


def main() -> int:
    project_root = Path(__file__).resolve().parents[2]
    target_root = (
        project_root
        / "storage"
        / "models"
        / MODEL_ID.replace("/", "--")
    )
    try:
        sizes = remote_file_sizes()
    except Exception as exc:
        print(
            f"failed to read ModelScope metadata: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1

    for relative_path in FILES:
        target = target_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        expected_size = sizes[relative_path]
        if target.is_file() and target.stat().st_size == expected_size:
            print(f"cached {relative_path}")
            continue

        url = f"{BASE_URL}/{relative_path}"
        print(f"downloading {relative_path}")
        try:
            if expected_size >= PART_SIZE:
                download_large_file(
                    url=url,
                    target=target,
                    expected_size=expected_size,
                )
            else:
                temporary = target.with_suffix(target.suffix + ".tmp")
                urllib.request.urlretrieve(url, temporary)
                temporary.replace(target)
        except Exception as exc:
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

