#!/usr/bin/env python3
"""Build a deterministic Home Assistant custom-integration release ZIP."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from hashlib import sha256
from pathlib import Path

SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ARCHIVE_ROOT = Path("custom_components/vacuum_planner")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="semantic version without a leading v")
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    return parser.parse_args()


def _release_files(source: Path) -> list[Path]:
    files = [
        path
        for path in source.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ]
    if any(path.is_symlink() for path in files):
        raise SystemExit("release source must not contain symbolic links")
    return sorted(files, key=lambda path: path.relative_to(source).as_posix())


def build_release(root: Path, output_dir: Path, version: str) -> tuple[Path, str]:
    """Write one deterministic ZIP and its SHA-256 checksum file."""
    if not SEMVER.fullmatch(version):
        raise SystemExit(f"invalid semantic version: {version}")
    source = root / ARCHIVE_ROOT
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        raise SystemExit(
            f"manifest version {manifest.get('version')!r} does not match requested {version!r}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"vacuum_planner-v{version}.zip"
    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as bundle:
        for path in _release_files(source):
            relative = path.relative_to(source)
            archive_name = (ARCHIVE_ROOT / relative).as_posix()
            info = zipfile.ZipInfo(archive_name, FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            bundle.writestr(
                info,
                path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )

    digest = sha256(archive.read_bytes()).hexdigest()
    (output_dir / "SHA256SUMS").write_text(
        f"{digest}  {archive.name}\n",
        encoding="utf-8",
        newline="\n",
    )
    return archive, digest


def main() -> None:
    """CLI entry point."""
    args = _arguments()
    root = Path(__file__).resolve().parents[1]
    archive, digest = build_release(root, args.output_dir.resolve(), args.version)
    sys.stdout.write(f"built {archive}\nsha256 {digest}\n")


if __name__ == "__main__":
    main()
