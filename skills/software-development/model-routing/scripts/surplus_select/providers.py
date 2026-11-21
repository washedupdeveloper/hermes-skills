"""Provider adapters.

A provider is a module that answers two questions: what models exist and what
they list for, and what a model actually sells for right now. Only the second
is allowed to be provider-specific; the snapshot shape is shared.

Surplus is the reference adapter. A generic OpenAI-compatible adapter covers
any other `/v1` endpoint with list prices and no discount book, and records
that gap instead of inventing a discount.
"""

from __future__ import annotations

import http.client
import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from html import unescape
from typing import Protocol
from urllib.parse import urlparse

from .model import ModelMarket, Offer, Price, Snapshot


class ProviderError(RuntimeError):
    """The provider answered, but not in a shape this adapter understands."""


class Http(Protocol):
    def get(self, url: str, timeout: float = 30.0) -> str:
        """Return the response body as text; raise ProviderError on failure."""


class UrllibHttp:
    def __init__(
        self,
        user_agent: str = "surplus-select/0.1",
        *,
        timeout: float = 30.0,
        retries: int = 3,
    ) -> None:
        self.user_agent = user_agent
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if retries < 1:
            raise ValueError("retries must be at least 1")
        self.timeout = timeout
        self.retries = retries

    def get(self, url: str, timeout: float | None = None) -> str:
        effective = self.timeout if timeout is None else timeout
        last: Exception | None = None
        for _ in range(self.retries):
            request = urllib.request.Request(
                url, headers={"User-Agent": self.user_agent, "Connection": "close"}
            )
            try:
                with urllib.request.urlopen(request, timeout=effective) as response:
                    return response.read().decode("utf-8", "replace")
            except (
                urllib.error.URLError,
                http.client.HTTPException,
                TimeoutError,
                OSError,
            ) as exc:
                last = exc
        raise ProviderError(f"GET {url}: {last}") from last


def page_text(markup: str) -> str:
    """Flatten the server-rendered model page into the pipe-delimited text."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S | re.I)
    text = re.sub(r"<svg.*?</svg>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "|", text)
    text = unescape(text)
    text = re.sub(r"\|+", "|", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text


def _number(raw: str) -> float:
    return float(raw.replace("$", "").replace(",", "").strip())


def _discount(text: str, label: str) -> float | None:
    match = re.search(rf"{label}\|([0-9.]+)%", text)
    return float(match.group(1)) if match else None


def parse_market_text(text: str) -> dict:
    """Extract the four price bases, volume and offers from a model page.

    Returns a partial dict; the caller merges it over the catalog entry.
    """
    reference = re.search(
        r"Benchmark price · \$([0-9.]+) input / \$([0-9.]+) output", text
    )
    if not reference:
        raise ProviderError("no benchmark price on the model page")
    list_price = Price(float(reference.group(1)), float(reference.group(2)))

    best_discount = _discount(text, "Best discount now")
    median_discount = _discount(text, "Median discount")
    realised_discount = _discount(text, r"Realized · 7 days")
    requests_match = re.search(r"Requests · 24h\|([0-9,]+)\|", text)
    requests = int(requests_match.group(1).replace(",", "")) if requests_match else None

    offers: list[Offer] = []
    route_success = _route_success(text)
    for match in re.finditer(
        r"\|([A-Za-z0-9][A-Za-z0-9 .&_-]{1,40})\|(\d+)%\|"
        r"\s*\$?([0-9.]+)\| in\|\$?([0-9.]+)\| out\|"
        r"([0-9.]+)s\|([0-9.]+)%\|([0-9.]+)%\|\$?([0-9.,]+)\|",
        text,
    ):
        provider = match.group(1).strip()
        offers.append(
            Offer(
                provider=provider,
                price=Price(float(match.group(3)), float(match.group(4))),
                discount=float(match.group(2)),
                success=route_success.get(provider, float(match.group(6))),
                latency_p50=float(match.group(5)),
                sold=_number(match.group(8)) if match.group(8) else None,
            )
        )

    best: Price | None = None
    if offers:
        cheapest = min(offers, key=lambda item: (item.price.input, item.price.output))
        best = cheapest.price
    elif best_discount is not None:
        keep = 1 - best_discount / 100
        best = Price(
            round(list_price.input * keep, 6),
            round(list_price.output * keep, 6),
        )

    return {
        "list_price": list_price,
        "best": best,
        "best_discount": best_discount,
        "median_discount": median_discount,
        "realised_discount": realised_discount,
        "requests_24h": requests,
        "offers": tuple(offers),
    }


def _route_success(text: str) -> dict[str, float]:
    marker = text.find("Performance by provider route")
    if marker < 0:
        return {}
    section = text[marker:]
    success: dict[str, float] = {}
    for match in re.finditer(
        r"\|([^|]{2,40})\|([0-9.]+) s\|([0-9.]+|-) s\|([^|]*)\|([0-9.]+)%\|(\d+)%\|",
        section,
    ):
        name = match.group(1).strip()
        if name.lower() in ("route", "share of traffic"):
            continue
        success[name] = float(match.group(5))
    return success


def parse_catalog(payload: dict) -> dict[str, ModelMarket]:
    """Turn `/v1/models` into catalog entries. Prices there are list prices."""
    data = payload.get("data")
    if not isinstance(data, list):
        raise ProviderError("catalog has no data list")
    models: dict[str, ModelMarket] = {}
    unpriced = 0
    for item in data:
        try:
            pricing = item["pricing"]
            raw_prompt = float(pricing["prompt"])
            raw_completion = float(pricing["completion"])
            raw_cache = (
                float(pricing["input_cache_read"])
                if pricing.get("input_cache_read") is not None
                else None
            )
            # OpenAI-compatible catalogs quote per token. A value at or above
            # 0.01 means the endpoint is quoting per million (or per thousand
            # of something), and multiplying by 1e6 would overstate the price
            # by six orders of magnitude. Fail loudly instead.
            if any(
                value is not None and value >= 0.01
                for value in (raw_prompt, raw_completion, raw_cache)
            ):
                raise ProviderError(
                    f"catalog price for {item.get('id')!r} looks per-million, "
                    "not per-token; refusing to guess"
                )
            list_price = Price(
                input=raw_prompt * 1_000_000,
                output=raw_completion * 1_000_000,
                cache_read=(raw_cache * 1_000_000 if raw_cache is not None else None),
            )
            model_id = str(item["id"])
            models[model_id] = ModelMarket(
                model_id=model_id,
                name=str(item.get("name", model_id)),
                context=int(item.get("context_length", 0)),
                list_price=list_price,
            )
        except (KeyError, TypeError, ValueError):
            unpriced += 1
            continue
    if not models:
        raise ProviderError(
            f"catalog has no priced models ({unpriced} entries had no usable pricing)"
        )
    return models


class Provider(Protocol):
    name: str
    capabilities: dict[str, bool]

    def fetch_catalog(self) -> dict[str, ModelMarket]:
        ...

    def fetch_market(self, model_id: str) -> dict | None:
        ...


class SurplusProvider:
    name = "surplus"
    capabilities = {"discounts": True, "availability": True}

    def __init__(self, base_url: str, http: Http | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or UrllibHttp()
        parsed = urlparse(self.base_url)
        host = parsed.netloc.split(":")[0]
        host = host.removeprefix("api.")
        if not host.startswith("www."):
            host = "www." + host
        self.origin = f"{parsed.scheme}://{host}"
        self._catalog_raw = ""

    def fetch_catalog(self) -> dict[str, ModelMarket]:
        self._catalog_raw = self.http.get(f"{self.base_url}/models")
        return parse_catalog(json.loads(self._catalog_raw))

    def fetch_market(self, model_id: str) -> dict | None:
        markup = self.http.get(f"{self.origin}/markets/{model_id}")
        return parse_market_text(page_text(markup))

    def refresh(self, model_ids: list[str] | None = None, workers: int = 6) -> Snapshot:
        if workers < 1:
            raise ValueError("workers must be at least 1")
        catalog = self.fetch_catalog()
        wanted = model_ids or list(catalog)
        missing = [model for model in wanted if model not in catalog]
        if missing:
            raise ProviderError(f"not in the catalog: {', '.join(missing[:3])}")

        def one(model_id: str) -> tuple[str, dict | None, str]:
            try:
                return model_id, self.fetch_market(model_id), ""
            except ProviderError as exc:
                return model_id, None, str(exc)

        markets = dict(catalog)
        errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for model_id, market, error in pool.map(one, wanted):
                if market is None:
                    errors[model_id] = error
                    continue
                # The page carries live and realised prices; the catalog
                # carries the cache-read price. Merging one over the other
                # would drop the cache term and understate every role.
                catalog_price = markets[model_id].list_price
                merged = dict(market)
                for key in ("list_price", "best"):
                    price = merged.get(key)
                    if isinstance(price, Price) and price.cache_read is None:
                        merged[key] = Price(price.input, price.output, catalog_price.cache_read)
                markets[model_id] = replace(markets[model_id], **merged)
        if not any(model.best for model in markets.values()):
            raise ProviderError(f"no market page parsed; first error: {next(iter(errors.values()), 'none')}")
        hashes = {"catalog": sha256(self._catalog_raw.encode()).hexdigest()[:16]}
        hashes.update(
            {
                model_id: sha256(str(markets[model_id]).encode()).hexdigest()[:16]
                for model_id in wanted
            }
        )
        return Snapshot(
            provider=self.name,
            base_url=self.base_url,
            fetched_at=datetime.now(timezone.utc),
            capabilities=dict(self.capabilities),
            models={key: markets[key] for key in wanted},
            source_hashes=hashes,
        )


class GenericProvider:
    name = "generic-openai"
    capabilities = {"discounts": False, "availability": False}

    def __init__(self, base_url: str, http: Http | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http or UrllibHttp()

    def fetch_catalog(self) -> dict[str, ModelMarket]:
        payload = json.loads(self.http.get(f"{self.base_url}/models"))
        return parse_catalog(payload)

    def fetch_market(self, model_id: str) -> dict | None:
        return None

    def refresh(self, model_ids: list[str] | None = None, workers: int = 6) -> Snapshot:
        catalog = self.fetch_catalog()
        wanted = model_ids or list(catalog)
        return Snapshot(
            provider=self.name,
            base_url=self.base_url,
            fetched_at=datetime.now(timezone.utc),
            capabilities=dict(self.capabilities),
            models={key: catalog[key] for key in wanted if key in catalog},
            source_hashes={},
        )


def provider_for(base_url: str, http: Http | None = None) -> Provider:
    host = urlparse(base_url).netloc.lower()
    if "surplusintelligence.ai" in host:
        return SurplusProvider(base_url, http)
    return GenericProvider(base_url, http)