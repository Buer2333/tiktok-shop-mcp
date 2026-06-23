"""Export current shops.json → ~/Downloads/tiktok_shop_tokens.xlsx for IT handoff.

Mirrors column layout of the existing Downloads/tiktok_shop_tokens.xlsx.
Run AFTER all 12 shops re-auth'd locally.
"""

import json
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

CONFIG = Path.home() / ".config" / "tiktok-mcp" / "shops.json"
OUT = Path.home() / "Downloads" / "tiktok_shop_tokens.xlsx"

COLUMNS = [
    "app_key",
    "open_id",
    "app_secret",
    "access_token",
    "access_token_expire_at",
    "refresh_token",
    "refresh_token_expire_at",
    "seller_name",
    "seller_base_region",
    "updated_at",
    "scope",
    "token_type",
    "app key",  # IT 旧表保留的副本列
    "secret",  # IT 旧表保留的副本列
]


def main():
    with open(CONFIG) as f:
        shops = json.load(f)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    wb = Workbook()
    ws = wb.active
    ws.title = "tiktok_shop_tokens"
    ws.append(COLUMNS)

    for s in shops:
        row = [
            s.get("app_key", ""),
            s.get("open_id", ""),
            s.get("app_secret", ""),
            s.get("access_token", ""),
            s.get("access_token_expire_at", ""),
            s.get("refresh_token", ""),
            s.get("refresh_token_expire_at", ""),
            s.get("seller_name", ""),
            s.get("seller_base_region", ""),
            now,
            s.get(
                "scope", ""
            ),  # 当前 shops.json 不存 scope，留空（IT 旧表此列也只有 re-auth 时才有）
            s.get("token_type", ""),
            s.get("app_key", ""),
            s.get("app_secret", ""),
        ]
        ws.append(row)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(f"✅ wrote {len(shops)} shops → {OUT}")
    print(f"   columns: {len(COLUMNS)} | rows incl header: {len(shops) + 1}")


if __name__ == "__main__":
    main()
