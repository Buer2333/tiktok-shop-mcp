"""add_or_update_shop.py：新 App 的 app_secret 来源，以及恢复文件跟随配置目录。"""

import importlib
import sys

import pytest


def _load(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOK_SHOP_CONFIG", str(tmp_path / "shops.json"))
    sys.modules.pop("add_or_update_shop", None)
    return importlib.import_module("add_or_update_shop")


def test_recovery_dir_follows_config(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch)
    assert mod.RECOVERY_DIR == tmp_path / "recovery"


def test_existing_app_secret_wins_over_env(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch)
    monkeypatch.setenv("TIKTOK_SHOP_APP_SECRET", "from-env")
    shops = [{"app_key": "k", "app_secret": "from-shop"}]
    assert mod.get_app_secret(shops, "k") == "from-shop"


def test_new_app_reads_secret_from_env(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch)
    monkeypatch.setenv("TIKTOK_SHOP_APP_SECRET", "from-env")
    assert mod.get_app_secret([], "k") == "from-env"


def test_new_app_without_env_fails(tmp_path, monkeypatch):
    mod = _load(tmp_path, monkeypatch)
    monkeypatch.delenv("TIKTOK_SHOP_APP_SECRET", raising=False)
    with pytest.raises(SystemExit):
        mod.get_app_secret([], "k")
