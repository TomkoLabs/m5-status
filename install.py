#!/usr/bin/env python3
"""Install one executable atomically, preserving a changed prior version."""

import argparse
import datetime
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile


def install(source, destination):
    source, destination = Path(source), Path(destination)
    data = source.read_bytes()
    expected = hashlib.sha256(data).hexdigest()
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must be different files")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and not destination.is_symlink() and destination.read_bytes() == data:
        destination.chmod(0o755)
        return None, expected
    backup = None
    if destination.exists() or destination.is_symlink():
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup = destination.with_name(destination.name + ".backup." + stamp)
        shutil.copy2(destination, backup, follow_symlinks=False)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=str(destination.parent), prefix=".m5-status.", delete=False) as stream:
            staged = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        staged.chmod(0o755)
        os.replace(str(staged), str(destination))
        if hashlib.sha256(destination.read_bytes()).hexdigest() != expected:
            raise OSError("installed source checksum mismatch")
    finally:
        if staged is not None and staged.exists():
            staged.unlink()
    return backup, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local/bin",
                        help="destination directory (default: ~/.local/bin)")
    args = parser.parse_args()
    if sys.version_info < (3, 9):
        parser.exit(1, "Installation requires Python 3.9 or later.\n")
    if sys.platform != "darwin":
        parser.exit(1, "m5-status monitoring and installation require macOS.\n")
    target = args.bin_dir / "m5-status"
    try:
        backup, digest = install(Path(__file__).resolve().with_name("m5-status"), target)
    except (OSError, ValueError) as exc:
        parser.exit(1, "Installation failed: {}\n".format(exc))
    if backup:
        print("Preserved: " + str(backup))
    print("Installed: " + str(target))
    print("Verified SHA-256: " + digest)
    print("Ensure this directory is in your login PATH; start a fresh terminal/SSH session.")


if __name__ == "__main__":
    main()
