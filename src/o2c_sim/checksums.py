import hashlib
from pathlib import Path

import pandas as pd


def frame_digest(frame: pd.DataFrame) -> str:
    payload = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def folder_manifest(folder: Path) -> dict[str, str]:
    manifest = {}
    for csv_path in sorted(folder.glob("*.csv")):
        frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        manifest[csv_path.name] = frame_digest(frame)
    return manifest


def write_manifest(folder: Path, census: dict[str, int], digests: dict[str, str]) -> None:
    lines = ["file,row_count,sha256"]
    for name in sorted(digests):
        rows = census.get(name.replace(".csv", ""), "")
        lines.append(f"{name},{rows},{digests[name]}")
    (folder / "checksum_manifest.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
