"""Shared read/write helpers for shops.json.

Every writer of the credentials file (the MCP server, the cron token
refresher, and the setup scripts) goes through this module so the
hardening lives in one place:

* The file and its directory are owner-only (0600 / 0700).
* Writes go to a uniquely named temp file in the same directory and are
  renamed into place, so a crash never leaves a truncated file and two
  writers never share a temp path.
* Read-modify-write cycles take an exclusive lock on a sidecar lock file,
  so concurrent writers serialize instead of overwriting each other.
* update_shop_on_disk() changes only the fields for one shop, so a
  process holding a stale in-memory copy cannot clobber tokens another
  process rotated on disk.

This module deliberately has no dependencies beyond the standard library
so the standalone scripts can import it without the MCP stack.
"""

import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

# Default config path: ~/.config/tiktok-mcp/shops.json
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "tiktok-mcp" / "shops.json"

ShopRecord = Dict[str, Any]


def resolve_shops_path() -> Path:
    """Resolve the shops.json path.

    Priority:
    1. TIKTOK_SHOP_CONFIG env var (explicit path)
    2. ~/.config/tiktok-mcp/shops.json (standard config dir)

    There is deliberately no project-local fallback: a shops.json next to the
    code can end up in a synced folder or a commit.
    """
    env_path = os.getenv("TIKTOK_SHOP_CONFIG")
    if env_path:
        return Path(env_path)
    return DEFAULT_CONFIG_PATH


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)


def read_shops(path: Path) -> List[ShopRecord]:
    """Load the shop list from disk. A missing file reads as an empty list."""
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list of shops")
    return data


@contextmanager
def shops_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive cross-process lock for a read-modify-write of shops.json.

    Uses flock on POSIX. On Windows there is no lock, but each write is still
    atomic and uses its own temp file.
    """
    _ensure_dir(path)
    lock_path = path.with_name(path.name + ".lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def write_shops_atomic(
    path: Path, shops: List[ShopRecord], *, backup: bool = False
) -> Optional[Path]:
    """Replace shops.json with `shops`, atomically and owner-only.

    With backup=True the previous file is first copied to
    shops.json.bak.YYYYMMDD-HHMMSS. Returns the backup path, if one was made.
    """
    _ensure_dir(path)

    bak: Optional[Path] = None
    if backup and path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = path.with_name(f"{path.name}.bak.{ts}")
        shutil.copy2(path, bak)
        os.chmod(bak, 0o600)

    # mkstemp gives a unique name and creates the file 0600; fchmod is belt
    # and braces in case a platform ignores the mode.
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        if hasattr(os, "fchmod"):  # not on Windows before Python 3.13
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(shops, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

    return bak


def update_shop_on_disk(
    path: Path,
    seller_name: str,
    fields: Dict[str, Any],
    *,
    default: Optional[ShopRecord] = None,
) -> List[ShopRecord]:
    """Merge `fields` into the on-disk entry for `seller_name` under lock.

    Other shops and any keys not in `fields` are left exactly as they are on
    disk. If the shop is absent, `default` (plus `fields`) is appended when
    given, otherwise KeyError is raised. Returns the full list as written.
    """
    with shops_lock(path):
        shops = read_shops(path)
        for entry in shops:
            if entry.get("seller_name") == seller_name:
                entry.update(fields)
                break
        else:
            if default is None:
                raise KeyError(f"Shop '{seller_name}' not found in {path}")
            record = dict(default)
            record["seller_name"] = seller_name
            record.update(fields)
            shops.append(record)
        write_shops_atomic(path, shops)
        return shops
