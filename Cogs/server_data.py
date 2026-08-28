"""Guild-scoped persistence used by the vending machine cogs.

The old implementation put every guild's inventory and login state in files in
the working directory.  Keep account secrets in their existing files for
backwards compatibility, but put public availability and shop data below
``data/<guild id>``.  Writes are atomic so a bot restart cannot leave half a
JSON document behind.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DATA_ROOT = Path(os.getenv("JIHANKI_DATA_DIR", "data"))
PAYMENT_DEFAULTS = {"paypay": False, "kyash": False, "ltc": False}


def guild_dir(guild_id: int | str) -> Path:
    path = DATA_ROOT / str(guild_id)
    path.mkdir(parents=True, exist_ok=True)
    (path / "cache").mkdir(exist_ok=True)
    return path


def _json_file(guild_id: int | str, name: str, default: Any) -> Any:
    path = guild_dir(guild_id) / name
    if not path.exists():
        save_guild_json(guild_id, name, default)
        return default.copy() if isinstance(default, dict) else list(default)
    try:
        with path.open(encoding="utf-8") as source:
            return json.load(source)
    except (json.JSONDecodeError, OSError):
        return default.copy() if isinstance(default, dict) else list(default)


def save_guild_json(guild_id: int | str, name: str, data: Any) -> None:
    path = guild_dir(guild_id) / name
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as destination:
        json.dump(data, destination, ensure_ascii=False, indent=2)
    temporary.replace(path)


def ensure_guild_files(guild_id: int | str) -> None:
    """Create the documented files even before the first product is added."""
    _json_file(guild_id, "payment.json", {"sellers": {}})
    _json_file(guild_id, "items.json", {})
    _json_file(guild_id, "stocks.json", {})


def payment_settings(guild_id: int | str, seller_id: int | str) -> dict[str, Any]:
    data = _json_file(guild_id, "payment.json", {"sellers": {}})
    seller = data.get("sellers", {}).get(str(seller_id), {})
    return {**PAYMENT_DEFAULTS, **seller}


def set_payment(
    guild_id: int | str, seller_id: int | str, method: str, enabled: bool, **extra: Any
) -> dict[str, Any]:
    if method not in PAYMENT_DEFAULTS:
        raise ValueError(f"Unsupported payment method: {method}")
    data = _json_file(guild_id, "payment.json", {"sellers": {}})
    sellers = data.setdefault("sellers", {})
    seller = sellers.setdefault(str(seller_id), PAYMENT_DEFAULTS.copy())
    seller[method] = bool(enabled)
    seller.update(extra)
    save_guild_json(guild_id, "payment.json", data)
    return seller


def disable_payment_for_all_guilds(seller_id: int | str, method: str) -> None:
    """Immediately hide a logged-out/expired method from every sales panel."""
    if not DATA_ROOT.exists():
        return
    for payment_file in DATA_ROOT.glob("*/payment.json"):
        data = _json_file(payment_file.parent.name, "payment.json", {"sellers": {}})
        seller = data.get("sellers", {}).get(str(seller_id))
        if seller is not None:
            seller[method] = False
            save_guild_json(payment_file.parent.name, "payment.json", data)


def save_product(guild_id: int | str, vending_machine_id: str, product: dict[str, Any]) -> None:
    """Mirror non-secret product metadata into the guild item/stock documents."""
    items = _json_file(guild_id, "items.json", {})
    stocks = _json_file(guild_id, "stocks.json", {})
    product_id = product["product_id"]
    public_product = {
        key: value
        for key, value in product.items()
        if key not in {"stock_file", "infinite_content"}
    }
    public_product["vending_machine_id"] = vending_machine_id
    items[product_id] = public_product
    stocks.setdefault(product_id, {"count": 0, "infinite": False})
    save_guild_json(guild_id, "items.json", items)
    save_guild_json(guild_id, "stocks.json", stocks)
