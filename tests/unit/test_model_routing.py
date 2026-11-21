"""Tests for the selector's pure core: calibration, baseline, routing, snapshot."""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "software-development" / "model-routing" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from surplus_select import (  # noqa: E402
    baseline,
    benchmarks as benchmarks_mod,
    calibration,
    mini_yaml,
    providers,
    report,
    routing,
    snapshot,
)
from surplus_select.model import (  # noqa: E402
    ModelMarket,
    Price,
    Snapshot,
    TaskSpec,
    Tokens,
)
from surplus_select.portfolio import choose  # noqa: E402


class MiniYamlTests(unittest.TestCase):
    def test_round_trip_preserves_task_ids_and_inline_lists(self) -> None:
        text = """
schema: 1
change: add-dimension-filter
tasks:
  "1.1":
    type: feature
    title: Add a filter
    verify: ["pytest tests/a.py -q", "pytest tests/b.py -q"]
  "2.1":
    type: architecture
    verify: ["review: docs/adr/0007.md"]
"""
        data = mini_yaml.loads(text)
        self.assertEqual(data["tasks"]["1.1"]["type"], "feature")
        self.assertEqual(
            data["tasks"]["1.1"]["verify"],
            ["pytest tests/a.py -q", "pytest tests/b.py -q"],
        )
        rendered = mini_yaml.dumps(data)
        again = mini_yaml.loads(rendered)
        self.assertEqual(again["tasks"]["1.1"]["verify"], data["tasks"]["1.1"]["verify"])
        self.assertIn('"1.1"', rendered)

    def test_comments_and_quoted_hashes(self) -> None:
        data = mini_yaml.loads('change: "a#b"  # trailing\nschema: 1\n')
        self.assertEqual(data["change"], "a#b")
        self.assertEqual(data["schema"], 1)


class CalibrationTests(unittest.TestCase):
    def _db(self, directory: Path, sessions: list[tuple]) -> Path:
        path = directory / "state.db"
        connection = sqlite3.connect(path)
        connection.execute(
            """
            create table session_model_usage (
                session_id text, model text,
                input_tokens integer, output_tokens integer,
                cache_read_tokens integer, reasoning_tokens integer,
                api_call_count integer, last_seen real
            )
            """
        )
        now = time.time()
        connection.executemany(
            """
            insert into session_model_usage
              (session_id, model, input_tokens, output_tokens,
               cache_read_tokens, reasoning_tokens, api_call_count, last_seen)
            values (?, 'test', ?, ?, 0, 0, ?, ?)
            """,
            [(sid, i, o, c, now - 3600) for sid, i, o, c in sessions],
        )
        connection.commit()
        connection.close()
        return path

    def test_total_is_a_sum_and_median_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = [(f"small-{i}", 10_000, 2_000, 10) for i in range(9)]
            sessions.append(("outlier", 1_000_000, 100_000, 100))
            path = self._db(Path(tmp), sessions)
            role = calibration.measure("builder", path, window_days=30)
            self.assertEqual(role.monthly_total.input, 1_090_000)
            self.assertEqual(role.monthly_total.output, 118_000)
            self.assertEqual(role.per_session.p50.input, 10_000)
            self.assertEqual(role.per_session.p90.input, 109_000)
            self.assertLess(role.per_session.p90.input, 1_000_000)
            self.assertGreater(role.monthly_total.input, role.per_session.p50.input * 10)
            self.assertEqual(role.per_call.p50.input, 1_000)
            self.assertFalse(role.uncalibrated)

    def test_missing_table_is_an_error_not_an_empty_month(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            sqlite3.connect(path).close()
            with self.assertRaises(calibration.CalibrationError):
                calibration.measure("builder", path)

    def test_budget_round_trip_marks_uncalibrated_roles(self) -> None:
        budget = calibration.default_budget()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "budget.yaml"
            calibration.save_budget(budget, path)
            loaded = calibration.load_budget(path)
        self.assertTrue(loaded.role("builder").uncalibrated)
        self.assertEqual(loaded.role("builder").monthly_total.input, 150_000_000)


class BaselineTests(unittest.TestCase):
    def test_flag_beats_environment_beats_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "config.yaml"
            config.write_text('model:\n  default: "from-profile"\n', encoding="utf-8")
            self.assertEqual(baseline.resolve("from-flag", "from-env", config).source, "flag")
            self.assertEqual(baseline.resolve(None, "from-env", config).source, "environment")
            resolved = baseline.resolve(None, "", config)
            self.assertEqual(resolved.model, "from-profile")
            self.assertTrue(resolved.source.startswith("profile:"))

    def test_missing_baseline_raises(self) -> None:
        with self.assertRaises(baseline.BaselineError):
            baseline.resolve(None, "", None)


class ClassificationTests(unittest.TestCase):
    def test_representative_titles(self) -> None:
        cases = {
            "Validate repo-root path before the sandbox mount": "security",
            "Decide whether verdicts become a state machine": "architecture",
            "Fix SARIF ruleId mismatch on merged findings": "bugfix",
            "Split proof execution out of run.py": "refactor",
            "Add a regression test for malformed verdict JSON": "test",
            "Rename Finding.dimension to category": "mechanical",
            "Update docs/AGENTS.md with the adapter contract": "docs",
            "Add --dimension filter to council review": "feature",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(routing.classify(title)[0].value, expected)


class RoutingMapTests(unittest.TestCase):
    def test_draft_reads_tags_and_infers_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            change = Path(tmp) / "add-dimension-filter"
            change.mkdir()
            (change / "tasks.md").write_text(
                """
- [ ] 1.1 Validate repo-root path [type: security] [verify: pytest tests/test_paths.py -q]
- [ ] 1.2 Add a regression test [verify: pytest tests/test_json.py -q]
- [ ] 2.1 Decide verdict model [type: architecture] [verify: review: docs/adr/0007.md]
""",
                encoding="utf-8",
            )
            drafted = routing.draft_routing(change)
        self.assertEqual(drafted.tasks["1.1"].type, "security")
        self.assertEqual(drafted.tasks["1.2"].type, "test")
        self.assertEqual(drafted.tasks["2.1"].type, "architecture")
        self.assertEqual(drafted.tasks["2.1"].verify, ("review: docs/adr/0007.md",))

    def test_route_refuses_a_task_without_a_predicate(self) -> None:
        task = TaskSpec(id="1.1", title="Do a thing", type="feature")
        decision = routing.route(task, "deepseek-v4.1-flash-1017")
        self.assertTrue(decision.needs_scoping)
        self.assertEqual(decision.model, "deepseek-v4.1-flash-1017")

    def test_architecture_gets_a_decider_but_keeps_the_baseline_implementer(self) -> None:
        task = TaskSpec(
            id="2.1",
            title="Decide the verdict model",
            type="architecture",
            verify=("review: docs/adr/0007.md",),
        )
        decision = routing.route(task, "deepseek", judge="claude-fable-5.2")
        self.assertEqual(decision.model, "deepseek")
        self.assertEqual(decision.decider, "claude-fable-5.2")
        self.assertTrue(decision.requires_review)
        self.assertEqual(decision.tier, "judge")

    def test_next_tier_moves_up_and_stops(self) -> None:
        ladder = ["a", "b", "c"]
        self.assertEqual(routing.next_tier("a", ladder), "b")
        self.assertEqual(routing.next_tier("c", ladder), None)
        self.assertEqual(routing.next_tier("unknown", ladder), "a")


class SnapshotTests(unittest.TestCase):
    def _snapshot(self, age_hours: float) -> Snapshot:
        fetched = datetime.now(timezone.utc) - timedelta(hours=age_hours)
        market = ModelMarket(
            model_id="deepseek-v4.1-flash-1017",
            name="DeepSeek V4.1 Flash 1017",
            context=1_048_576,
            list_price=Price(0.147, 0.60, 0.005),
            best=Price(0.0045, 0.02, 0.0002),
            best_discount=96.9,
            median_discount=48.7,
            realised_discount=93.4,
            requests_24h=3_335_864,
        )
        return Snapshot(
            provider="surplus",
            base_url="https://api.surplusintelligence.ai/v1",
            fetched_at=fetched,
            capabilities={"discounts": True, "availability": True},
            models={market.model_id: market},
            source_hashes={"catalog": "abc"},
        )

    def test_freshness_ladder(self) -> None:
        self.assertEqual(self._snapshot(1).freshness(), "fresh")
        self.assertEqual(self._snapshot(24).freshness(), "aging")
        self.assertEqual(self._snapshot(72).freshness(), "provisional")
        self.assertEqual(self._snapshot(24 * 8).freshness(), "expired")
        self.assertTrue(self._snapshot(24).allows_profile_writes())
        self.assertFalse(self._snapshot(72).allows_profile_writes())
        self.assertFalse(self._snapshot(24 * 8).allows_ranking())

    def test_round_trip_and_digest(self) -> None:
        original = self._snapshot(2)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            snapshot.save(original, path)
            loaded = snapshot.load(path)
        self.assertEqual(loaded.models["deepseek-v4.1-flash-1017"].context, 1_048_576)
        self.assertEqual(snapshot.digest(original), snapshot.digest(loaded))

    def test_realised_price_uses_the_average_not_the_sticker(self) -> None:
        market = self._snapshot(1).models["deepseek-v4.1-flash-1017"]
        realised = market.realised()
        self.assertAlmostEqual(realised.input, 0.147 * 0.066, places=6)
        self.assertAlmostEqual(realised.output, 0.60 * 0.066, places=6)
        self.assertLess(realised.input, market.list_price.input)
        self.assertGreater(realised.input, market.best.input)

    def test_cost_includes_cache_reads(self) -> None:
        price = Price(1.0, 2.0, 0.1)
        tokens = Tokens(input=1_000_000, output=200_000, cache_read=500_000)
        self.assertAlmostEqual(price.cost(tokens), 1.0 + 0.4 + 0.05)


class ProviderTests(unittest.TestCase):
    MARKET = """
|DeepSeek V4.1 Flash 1017|DeepSeek| · |1.0M context|deepseek-v4.1-flash-1017|
Benchmark price · $0.147 input / $0.60 output per 1M tokens|
Best discount now|96.9%|off|You pay 3.1% of reference.|
Median discount|48.7%|off|Across 78 live offers.|
Realized · 7 days|93.4%|avg|Request-weighted average.|
Requests · 24h|3,335,864|78 offers from 40 sellers.|
Current offers|78 of 120 offers|
Provider|Discount|Price|Latency|Uptime|Cache|Sold|
|InferHub|96%|$0.00450| in|$0.0200| out|4.1s|98.9%|76.9%|$984|
|Dolphin|96%|$0.00780| in|$0.0300| out|33.6s|48.8%|49.5%|$0.208|
Show more (76)|
Performance by provider route · 24h|Measured on Surplus traffic|
Route|p50 latency|p95 latency|Throughput|Success rate|Share|
|Alibaba DashScope — China|7.49 s|45.32 s|243 tok/s|99.9%|93%|
|InferHub|5.55 s|33.57 s|40 tok/s|98.9%|5%|
|Dolphin|45.32 s|150.53 s|54 tok/s|48.8%|1%|
"""

    CATALOG = {
        "data": [
            {
                "id": "m1",
                "name": "M1",
                "context_length": 128000,
                "pricing": {
                    "prompt": "0.000000195",
                    "completion": "0.00000075",
                    "input_cache_read": "0.0000000063",
                },
            }
        ]
    }

    def test_page_text_strips_markup(self) -> None:
        text = providers.page_text("<div>Price</div><script>x</script><b>$1</b>")
        self.assertIn("Price", text)
        self.assertIn("$1", text)
        self.assertNotIn("script", text)

    def test_parse_market_keeps_the_four_bases_apart(self) -> None:
        parsed = providers.parse_market_text(self.MARKET)
        self.assertEqual(parsed["list_price"].input, 0.147)
        self.assertEqual(parsed["best"].input, 0.0045)
        self.assertEqual(parsed["realised_discount"], 93.4)
        self.assertEqual(parsed["median_discount"], 48.7)
        self.assertEqual(parsed["requests_24h"], 3_335_864)
        self.assertEqual(len(parsed["offers"]), 2)
        self.assertEqual(parsed["offers"][0].provider, "InferHub")
        self.assertEqual(parsed["offers"][0].success, 98.9)
        self.assertEqual(parsed["offers"][1].success, 48.8)

    def test_parse_catalog_reads_per_token_prices_as_per_million(self) -> None:
        models = providers.parse_catalog(self.CATALOG)
        price = models["m1"].list_price
        self.assertAlmostEqual(price.input, 0.195)
        self.assertAlmostEqual(price.output, 0.75)
        self.assertAlmostEqual(price.cache_read or 0, 0.0063)

    def test_surplus_refresh_merges_catalog_and_market(self) -> None:
        class FakeHttp:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def get(self, url: str, timeout: float = 30.0) -> str:
                self.calls.append(url)
                if url.endswith("/models"):
                    return json.dumps(self_catalog)
                return self_market

        self_catalog = self.CATALOG
        self_market = self.MARKET
        http = FakeHttp()
        provider = providers.SurplusProvider("https://api.surplusintelligence.ai/v1", http)
        snap = provider.refresh(["m1"])
        self.assertEqual(snap.provider, "surplus")
        self.assertTrue(snap.capabilities["discounts"])
        self.assertAlmostEqual(snap.models["m1"].best.input, 0.0045)
        self.assertAlmostEqual(snap.models["m1"].list_price.input, 0.147)
        self.assertEqual(len(http.calls), 2)

    def test_generic_provider_records_the_discount_gap(self) -> None:
        class FakeHttp:
            def get(self, url: str, timeout: float = 30.0) -> str:
                return json.dumps(self_catalog)

        self_catalog = self.CATALOG
        provider = providers.GenericProvider("https://example.test/v1", FakeHttp())
        snap = provider.refresh(["m1"])
        self.assertEqual(snap.provider, "generic-openai")
        self.assertFalse(snap.capabilities["discounts"])
        self.assertIsNone(snap.models["m1"].best)

    def test_provider_factory_matches_the_endpoint(self) -> None:
        self.assertEqual(
            providers.provider_for("https://api.surplusintelligence.ai/v1").name,
            "surplus",
        )
        self.assertEqual(
            providers.provider_for("https://openrouter.ai/api/v1").name,
            "generic-openai",
        )


class PortfolioTests(unittest.TestCase):
    def _cache(self) -> benchmarks_mod.BenchmarkCache:
        now = datetime.now(timezone.utc)
        return benchmarks_mod.BenchmarkCache(
            source="test",
            fetched_at=now,
            models={
                "deepseek-v4.1-flash-1017": benchmarks_mod.Benchmark(
                    coding=76.4, hle=25.3, frontier_math=71.2
                ),
                "gpt-6.1-terra": benchmarks_mod.Benchmark(
                    coding=80.0, hle=47.3, frontier_math=90.9
                ),
                "gpt-6.2-sol": benchmarks_mod.Benchmark(coding=83.3, hle=64.0),
                "gpt-6.2-astra": benchmarks_mod.Benchmark(
                    coding=91.8, hle=72.2, frontier_math=92.6
                ),
                "claude-fable-5.2": benchmarks_mod.Benchmark(
                    coding=92.3, hle=80.2, frontier_math=95.1
                ),
            },
        )

    def _snapshot(self) -> Snapshot:
        now = datetime.now(timezone.utc)

        def market(model_id, name, list_in, list_out, best_in, best_out, realised):
            return ModelMarket(
                model_id=model_id,
                name=name,
                context=1_000_000,
                list_price=Price(list_in, list_out),
                best=Price(best_in, best_out),
                realised_discount=realised,
            )

        models = [
            market("deepseek-v4.1-flash-1017", "DeepSeek", 0.147, 0.60, 0.0097, 0.0396, 93.4),
            market("gpt-6.1-terra", "Terra", 1.00, 5.00, 0.226, 1.13, 77.4),
            market("gpt-6.2-sol", "Sol", 2.00, 10.00, 0.548, 2.74, 72.6),
            market("gpt-6.2-astra", "Astra", 8.00, 40.00, 2.096, 10.48, 73.8),
            market("claude-fable-5.2", "Fable", 8.00, 40.00, 3.328, 16.64, 58.4),
        ]
        return Snapshot(
            provider="test",
            base_url="https://example.test",
            fetched_at=now,
            models={model.model_id: model for model in models},
        )

    def test_portfolio_has_four_distinct_roles(self) -> None:
        portfolio = choose(self._cache(), self._snapshot(), "deepseek-v4.1-flash-1017")
        roles = {role.name: role.model_id for role in portfolio.roles}
        self.assertEqual(roles["judge"], "claude-fable-5.2")
        self.assertEqual(roles["builder"], "deepseek-v4.1-flash-1017")
        self.assertEqual(roles["reviewer"], "gpt-6.1-terra")
        self.assertEqual(roles["runner"], "gpt-6.2-sol")
        self.assertEqual(len(set(roles.values())), 4)

    def test_portfolio_refuses_an_unscored_market(self) -> None:
        empty = benchmarks_mod.BenchmarkCache(
            source="test", fetched_at=datetime.now(timezone.utc), models={}
        )
        with self.assertRaises(ValueError):
            choose(empty, self._snapshot(), "deepseek-v4.1-flash-1017")


class ReportTests(unittest.TestCase):
    def test_payload_carries_time_basis_and_costs(self) -> None:
        cache = PortfolioTests()._cache()
        snap = PortfolioTests()._snapshot()
        portfolio = choose(cache, snap, "deepseek-v4.1-flash-1017")
        task = TaskSpec(
            id="1.1",
            title="Add a filter",
            type="feature",
            verify=("pytest tests/test_cli.py -q",),
        )
        routing_map = routing.RoutingMap(change="demo", tasks={"1.1": task})
        decision = routing.route(task, "deepseek-v4.1-flash-1017", judge="claude-fable-5.2")
        payload = report.build(
            snapshot=snap,
            budget=calibration.default_budget(),
            portfolio=portfolio,
            routing=routing_map,
            decisions=[decision],
            cache=cache,
            baseline="deepseek-v4.1-flash-1017",
            baseline_source="test",
            sources=[{"title": "Example", "url": "https://example.test"}],
        )
        self.assertIn("generated_at", payload)
        self.assertIn("live best offer", payload["pricing_basis"]["headline"])
        self.assertGreater(payload["costs"]["total"], 0)
        self.assertEqual(len(payload["tasks"]), 1)
        self.assertEqual(payload["tasks"][0]["predicate"], ["pytest tests/test_cli.py -q"])
        html_text = report.render_html(payload)
        self.assertIn("Generated", html_text)
        self.assertIn("The portfolio", html_text)
        self.assertIn("Monthly $", html_text)


if __name__ == "__main__":
    unittest.main()