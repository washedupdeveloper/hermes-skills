"""Snapshot persistence and identity.

The snapshot is the only thing the router prices from. It is written by a
refresh, read by a plan, and hashed into every report so a later reader can
tell whether two decisions saw the same market.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .model import ModelMarket, Offer, Price, Snapshot


class SnapshotError(ValueError):
    """The file is not a snapshot this build understands."""


def _price_to_dict(price: Price) -> dict:
    return {
        "input": price.input,
        "output": price.output,
        **({"cache_read": price.cache_read} if price.cache_read is not None else {}),
    }


def _price_from_dict(data: dict) -> Price:
    return Price(
        input=float(data["input"]),
        output=float(data["output"]),
        cache_read=(float(data["cache_read"]) if data.get("cache_read") is not None else None),
    )


def _offer_to_dict(offer: Offer) -> dict:
    return {
        "provider": offer.provider,
        "price": _price_to_dict(offer.price),
        **({"discount": offer.discount} if offer.discount is not None else {}),
        **({"success": offer.success} if offer.success is not None else {}),
        **({"latency_p50": offer.latency_p50} if offer.latency_p50 is not None else {}),
        **({"sold": offer.sold} if offer.sold is not None else {}),
    }


def _market_to_dict(model: ModelMarket) -> dict:
    return {
        "model_id": model.model_id,
        "name": model.name,
        "context": model.context,
        "list_price": _price_to_dict(model.list_price),
        **({"best": _price_to_dict(model.best)} if model.best else {}),
        **({"best_discount": model.best_discount} if model.best_discount is not None else {}),
        **({"median_discount": model.median_discount} if model.median_discount is not None else {}),
        **({"realised_discount": model.realised_discount} if model.realised_discount is not None else {}),
        **({"requests_24h": model.requests_24h} if model.requests_24h is not None else {}),
        "offers": [_offer_to_dict(offer) for offer in model.offers],
    }


def _market_from_dict(data: dict) -> ModelMarket:
    return ModelMarket(
        model_id=str(data["model_id"]),
        name=str(data.get("name", data["model_id"])),
        context=int(data.get("context", 0)),
        list_price=_price_from_dict(data["list_price"]),
        best=_price_from_dict(data["best"]) if data.get("best") else None,
        best_discount=(
            float(data["best_discount"]) if data.get("best_discount") is not None else None
        ),
        median_discount=(
            float(data["median_discount"]) if data.get("median_discount") is not None else None
        ),
        realised_discount=(
            float(data["realised_discount"]) if data.get("realised_discount") is not None else None
        ),
        requests_24h=(int(data["requests_24h"]) if data.get("requests_24h") is not None else None),
        offers=tuple(
            Offer(
                provider=str(item["provider"]),
                price=_price_from_dict(item["price"]),
                discount=(float(item["discount"]) if item.get("discount") is not None else None),
                success=(float(item["success"]) if item.get("success") is not None else None),
                latency_p50=(
                    float(item["latency_p50"]) if item.get("latency_p50") is not None else None
                ),
                sold=(float(item["sold"]) if item.get("sold") is not None else None),
            )
            for item in data.get("offers", [])
        ),
    )


def to_dict(snapshot: Snapshot) -> dict:
    return {
        "schema": 1,
        "provider": snapshot.provider,
        "base_url": snapshot.base_url,
        "fetched_at": snapshot.fetched_at.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "capabilities": snapshot.capabilities,
        "source_hashes": snapshot.source_hashes,
        "models": {
            key: _market_to_dict(model) for key, model in sorted(snapshot.models.items())
        },
    }


def from_dict(data: dict) -> Snapshot:
    if int(data.get("schema", 0)) != 1:
        raise SnapshotError(f"unsupported snapshot schema {data.get('schema')!r}")
    try:
        fetched = datetime.fromisoformat(str(data["fetched_at"]))
    except (KeyError, ValueError) as exc:
        raise SnapshotError("snapshot has no valid fetched_at") from exc
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    models = {}
    for key, value in (data.get("models") or {}).items():
        models[key] = _market_from_dict(value)
    return Snapshot(
        provider=str(data.get("provider", "unknown")),
        base_url=str(data.get("base_url", "")),
        fetched_at=fetched,
        capabilities=dict(data.get("capabilities") or {}),
        models=models,
        source_hashes=dict(data.get("source_hashes") or {}),
    )


def canonical_json(snapshot: Snapshot) -> str:
    return json.dumps(to_dict(snapshot), sort_keys=True, separators=(",", ":"))


def digest(snapshot: Snapshot) -> str:
    return sha256(canonical_json(snapshot).encode("utf-8")).hexdigest()[:16]


def save(snapshot: Snapshot, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(to_dict(snapshot), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def load(path: str | Path) -> Snapshot:
    source = Path(path)
    if not source.is_file():
        raise SnapshotError(f"no snapshot at {source}")
    return from_dict(json.loads(source.read_text(encoding="utf-8")))