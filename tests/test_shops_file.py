"""Tests for the shared shops.json read/write helpers and config persistence."""

import json
import os
import stat
import threading

import pytest

from tiktok_shop_mcp.shops_file import (
    read_shops,
    update_shop_on_disk,
    write_shops_atomic,
)


def _shop(name, **overrides):
    base = {
        "seller_name": name,
        "app_key": "key",
        "app_secret": "secret",
        "access_token": f"{name}-access-1",
        "refresh_token": f"{name}-refresh-1",
    }
    base.update(overrides)
    return base


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_write_creates_owner_only_file_and_dir(tmp_path):
    path = tmp_path / "cfg" / "shops.json"
    write_shops_atomic(path, [_shop("A")])

    assert json.loads(path.read_text()) == [_shop("A")]
    assert _mode(path) == 0o600
    assert _mode(path.parent) == 0o700
    # No temp file left behind
    assert [p.name for p in path.parent.iterdir()] == ["shops.json"]


def test_write_leaves_previous_file_intact_on_failure(tmp_path):
    path = tmp_path / "shops.json"
    write_shops_atomic(path, [_shop("A")])

    with pytest.raises(TypeError):
        write_shops_atomic(path, [{"bad": object()}])

    assert json.loads(path.read_text()) == [_shop("A")]
    assert [p.name for p in path.parent.iterdir()] == ["shops.json"]


def test_write_with_backup_snapshots_previous_contents(tmp_path):
    path = tmp_path / "shops.json"
    write_shops_atomic(path, [_shop("A")])
    bak = write_shops_atomic(path, [_shop("B")], backup=True)

    assert bak is not None
    assert bak.name.startswith("shops.json.bak.")
    assert json.loads(bak.read_text()) == [_shop("A")]
    assert _mode(bak) == 0o600
    assert json.loads(path.read_text()) == [_shop("B")]


def test_read_missing_file_returns_empty_list(tmp_path):
    assert read_shops(tmp_path / "nope.json") == []


def test_update_merges_only_given_fields_and_preserves_others(tmp_path):
    path = tmp_path / "shops.json"
    write_shops_atomic(
        path,
        [_shop("A", extra="keep-me"), _shop("B", updated_at="yesterday")],
    )

    update_shop_on_disk(path, "A", {"access_token": "A-access-2"})

    on_disk = {s["seller_name"]: s for s in read_shops(path)}
    assert on_disk["A"]["access_token"] == "A-access-2"
    assert on_disk["A"]["refresh_token"] == "A-refresh-1"
    assert on_disk["A"]["extra"] == "keep-me"
    assert on_disk["B"] == _shop("B", updated_at="yesterday")


def test_update_unknown_shop_raises_without_default(tmp_path):
    path = tmp_path / "shops.json"
    write_shops_atomic(path, [_shop("A")])

    with pytest.raises(KeyError):
        update_shop_on_disk(path, "Z", {"access_token": "x"})


def test_update_unknown_shop_appends_default_record(tmp_path):
    path = tmp_path / "shops.json"
    write_shops_atomic(path, [_shop("A")])

    update_shop_on_disk(path, "Z", {"access_token": "z-2"}, default=_shop("Z"))

    on_disk = read_shops(path)
    assert [s["seller_name"] for s in on_disk] == ["A", "Z"]
    assert on_disk[1]["access_token"] == "z-2"


def test_concurrent_updates_do_not_lose_writes_or_corrupt_file(tmp_path):
    path = tmp_path / "shops.json"
    names = [f"S{i}" for i in range(8)]
    write_shops_atomic(path, [_shop(n) for n in names])

    def worker(name):
        for i in range(20):
            update_shop_on_disk(path, name, {"access_token": f"{name}-{i}"})

    threads = [threading.Thread(target=worker, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    on_disk = {s["seller_name"]: s for s in read_shops(path)}
    for n in names:
        assert on_disk[n]["access_token"] == f"{n}-19"
    assert [p.name for p in path.parent.iterdir() if p.name.endswith(".tmp")] == []


def test_config_save_shop_does_not_clobber_tokens_rotated_on_disk(tmp_path, monkeypatch):
    """Server holds A and B in memory; cron rotates B on disk; server then
    saves A. B's new token must survive, and the server must pick it up."""
    path = tmp_path / "shops.json"
    write_shops_atomic(path, [_shop("A"), _shop("B")])
    monkeypatch.setenv("TIKTOK_SHOP_CONFIG", str(path))

    from tiktok_shop_mcp.config import TikTokShopConfig

    cfg = TikTokShopConfig()
    assert cfg.shops["B"].refresh_token == "B-refresh-1"

    # Simulate the cron refresher rotating B behind the server's back
    update_shop_on_disk(path, "B", {"refresh_token": "B-refresh-2"})

    cfg.shops["A"].access_token = "A-access-2"
    cfg.shops["A"].refresh_token = "A-refresh-2"
    cfg.save_shop("A")

    on_disk = {s["seller_name"]: s for s in read_shops(path)}
    assert on_disk["A"]["access_token"] == "A-access-2"
    assert on_disk["A"]["refresh_token"] == "A-refresh-2"
    assert on_disk["B"]["refresh_token"] == "B-refresh-2"
    # In-memory copy of B was refreshed from disk, same object identity kept
    assert cfg.shops["B"].refresh_token == "B-refresh-2"
