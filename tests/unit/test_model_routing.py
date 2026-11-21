"""Tests for the selector's pure core: calibration, baseline, routing, snapshot."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "software-development" / "model-routing" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from surplus_select import (  # noqa: E402
    baseline,
    benchmarks as benchmarks_mod,
    calibration,
    cli,
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

    def test_unsupported_yaml_is_refused_not_guessed(self) -> None:
        cases = [
            "tasks: {1.1: {type: feature}}\n",
            "a: &x 1\n",
            "a: *x\n",
            "a: |\n  text\n",
            "a: 1\n<<: *x\n",
        ]
        for text in cases:
            with self.subTest(text=text):
                with self.assertRaises(mini_yaml.YamlError):
                    mini_yaml.loads(text)

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

    def test_month_length_is_user_settable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._db(Path(tmp), [("one", 1_000_000, 0, 1)])
            month = calibration.measure("builder", path, window_days=30)
            half = calibration.measure(
                "builder", path, window_days=30, month_days=15
            )
            self.assertEqual(month.monthly_total.input, 1_000_000)
            self.assertEqual(half.monthly_total.input, 500_000)
            with self.assertRaises(calibration.CalibrationError):
                calibration.measure("builder", path, month_days=0)
            with self.assertRaises(calibration.CalibrationError):
                calibration.measure("builder", path, window_days=0)

    def test_percentile_bundle_total_is_a_real_session_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sessions = [
                ("low", 0, 0, 1),
                ("middle", 100, 100, 1),
                ("high", 1000, 0, 1),
            ]
            path = self._db(Path(tmp), sessions)
            role = calibration.measure("builder", path, window_days=30)
        # The P50 total is 200 from the middle session. Summing per-field
        # percentiles would give input 100 + output 0 = 100, a bundle that no
        # session ever had.
        self.assertEqual(role.per_session.p50.total(), 200)
        self.assertEqual(role.per_session.p50.input, 100)
        self.assertEqual(role.per_session.p50.output, 100)

    def test_missing_table_is_an_error_not_an_empty_month(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.db"
            sqlite3.connect(path).close()
            with self.assertRaises(calibration.CalibrationError):
                calibration.measure("builder", path)

    def test_path_with_hash_and_spaces_is_opened_read_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="a b#c ") as tmp:
            path = self._db(Path(tmp), [("s1", 1000, 200, 10)])
            role = calibration.measure("builder", path)
        self.assertEqual(role.monthly_total.input, 1000)
        self.assertEqual(role.sessions, 1)

    def test_combining_a_calibrated_and_an_illustrative_profile_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._db(Path(tmp), [("s1", 1000, 200, 10)])
            measured = calibration.measure("reviewer", path)
        fallback = calibration._uncalibrated("reviewer", 30, "none")
        combined = cli._combine([measured, fallback])
        self.assertTrue(combined.uncalibrated)
        self.assertIn("mixed", combined.source)
        self.assertEqual(combined.monthly_total.input, measured.monthly_total.input + fallback.monthly_total.input)

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

    def test_hermes_home_uses_the_windows_default_only_on_windows(self) -> None:
        self.assertEqual(
            baseline.hermes_home({"HERMES_HOME": "/x"}, windows=False), Path("/x")
        )
        self.assertEqual(
            baseline.hermes_home(
                {"LOCALAPPDATA": "C:/Users/x/AppData/Local"}, windows=True
            ),
            Path("C:/Users/x/AppData/Local/hermes"),
        )
        self.assertEqual(
            baseline.hermes_home({}, windows=False), Path.home() / ".hermes"
        )


class ClassificationTests(unittest.TestCase):
    def test_representative_titles(self) -> None:
        cases = {
            "Validate repo-root path before the sandbox mount": "security",
            "Decide whether verdicts become a state machine": "architecture",
            "Fix SARIF ruleId mismatch on merged findings": "bugfix",
            "Split proof execution out of run.py": "refactor",
            "Add a regression test for malformed verdict JSON": "test",
            "Add a regression test for the parser bug": "test",
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

    def test_route_names_the_reviewer_only_when_review_is_required(self) -> None:
        bugfix = TaskSpec(
            id="1.2",
            title="Fix the parser",
            type="bugfix",
            verify=("pytest tests/test_parser.py -q",),
        )
        feature = TaskSpec(
            id="1.3",
            title="Add a flag",
            type="feature",
            verify=("pytest tests/test_cli.py -q",),
        )
        reviewed = routing.route(bugfix, "deepseek", reviewer="gpt-6.1-terra")
        plain = routing.route(feature, "deepseek", reviewer="gpt-6.1-terra")
        self.assertEqual(reviewed.reviewer, "gpt-6.1-terra")
        self.assertIsNone(plain.reviewer)

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

    def test_freshness_bounds_are_user_settable(self) -> None:
        snap = self._snapshot(20)
        self.assertEqual(snap.freshness(), "aging")
        self.assertEqual(snap.freshness(fresh_hours=24), "fresh")
        self.assertEqual(snap.freshness(aging_hours=12), "provisional")
        with self.assertRaises(ValueError):
            snap.freshness(fresh_hours=60, aging_hours=48)

    def test_round_trip_and_digest(self) -> None:
        original = self._snapshot(2)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            snapshot.save(original, path)
            loaded = snapshot.load(path)
        self.assertEqual(loaded.models["deepseek-v4.1-flash-1017"].context, 1_048_576)
        self.assertEqual(snapshot.digest(original), snapshot.digest(loaded))

    def test_a_malformed_snapshot_names_the_model(self) -> None:
        data = snapshot.to_dict(self._snapshot(1))
        del data["models"]["deepseek-v4.1-flash-1017"]["list_price"]
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.from_dict(data)

    def test_corrupt_json_is_a_snapshot_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(snapshot.SnapshotError):
                snapshot.load(path)

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

    def test_a_cache_read_without_a_cache_price_bills_as_input(self) -> None:
        price = Price(1.0, 2.0)
        tokens = Tokens(cache_read=1_000_000)
        self.assertAlmostEqual(price.cost(tokens), 1.0)

    def test_reasoning_is_already_inside_output(self) -> None:
        price = Price(1.0, 2.0)
        tokens = Tokens(output=1_000_000, reasoning=500_000)
        self.assertAlmostEqual(price.cost(tokens), 2.0)
        self.assertEqual(tokens.total(), 1_000_000)


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
        # The page has no cache price; the catalog's must survive the merge.
        self.assertAlmostEqual(snap.models["m1"].list_price.cache_read, 0.0063)
        self.assertAlmostEqual(snap.models["m1"].live().cache_read, 0.0063)
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

    def test_catalog_price_quoted_per_million_is_refused(self) -> None:
        payload = {
            "data": [
                {
                    "id": "m1",
                    "pricing": {"prompt": "0.15", "completion": "0.60"},
                }
            ]
        }
        with self.assertRaises(providers.ProviderError):
            providers.parse_catalog(payload)

    def test_catalog_skips_unpriced_entries(self) -> None:
        payload = {
            "data": [
                self.CATALOG["data"][0],
                {"id": "free", "name": "Free", "context_length": 1000},
            ]
        }
        models = providers.parse_catalog(payload)
        self.assertEqual(set(models), {"m1"})

    def test_catalog_with_no_priced_entries_is_an_error(self) -> None:
        with self.assertRaises(providers.ProviderError) as caught:
            providers.parse_catalog({"data": [{"id": "free"}]})
        self.assertIn("no priced models", str(caught.exception))

    def test_provider_factory_matches_the_endpoint(self) -> None:
        self.assertEqual(
            providers.provider_for("https://api.surplusintelligence.ai/v1").name,
            "surplus",
        )
        self.assertEqual(
            providers.provider_for("https://openrouter.ai/api/v1").name,
            "generic-openai",
        )


class BenchmarkTests(unittest.TestCase):
    def test_parse_benchlm_array_keeps_coding_and_overall(self) -> None:
        row = [0] * 25
        row[1] = "Model Name"
        row[2] = "slug"
        row[4] = "Proprietary"
        row[14] = 88.0
        row[22] = 91.0
        markup = "[" + json.dumps(row, separators=(",", ":")) + "]"
        models = benchmarks_mod.parse_benchlm_coding(markup)
        self.assertIn("slug", models)
        self.assertEqual(models["slug"].coding, 91.0)
        self.assertEqual(models["slug"].overall, 88.0)

    def test_refresh_rejects_a_page_with_too_few_rows(self) -> None:
        class FakeHttp:
            def get(self, url: str, timeout: float = 30.0) -> str:
                return "[]"

        cache = benchmarks_mod.BenchmarkCache(
            source="test", fetched_at=datetime.now(timezone.utc), models={}
        )
        with self.assertRaises(providers.ProviderError):
            benchmarks_mod.refresh(cache, FakeHttp())


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
                "qwen4-max": benchmarks_mod.Benchmark(coding=76.0, hle=44.9),
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
            market("qwen4-max", "Qwen4 Max", 1.43, 4.28, 0.1916, 0.5735, 86.6),
            market("gpt-6.2-astra", "Astra", 8.00, 40.00, 2.096, 10.48, 73.8),
            market("claude-fable-5.2", "Fable", 8.00, 40.00, 3.328, 16.64, 58.4),
        ]
        return Snapshot(
            provider="test",
            base_url="https://example.test",
            fetched_at=now,
            models={model.model_id: model for model in models},
        )

    def test_default_portfolio_does_not_buy_a_premium(self) -> None:
        portfolio = choose(self._cache(), self._snapshot(), "deepseek-v4.1-flash-1017")
        roles = {role.name: role.model_id for role in portfolio.roles}
        self.assertEqual(roles["judge"], "claude-fable-5.2")
        self.assertEqual(roles["builder"], "deepseek-v4.1-flash-1017")
        self.assertEqual(roles["reviewer"], "deepseek-v4.1-flash-1017")
        self.assertEqual(roles["runner"], "deepseek-v4.1-flash-1017")
        self.assertIn("qwen4-max", portfolio.rejected or {})
        self.assertEqual(
            portfolio.rejected["qwen4-max"], "deepseek-v4.1-flash-1017"
        )

    def test_dominated_model_is_never_a_role(self) -> None:
        portfolio = choose(self._cache(), self._snapshot(), "deepseek-v4.1-flash-1017")
        self.assertNotIn("qwen4-max", portfolio.model_ids())

    def test_reviewer_upgrade_requires_materiality_and_budget(self) -> None:
        tokens = Tokens(input=75_000_000, output=8_000_000)
        tight = choose(
            self._cache(),
            self._snapshot(),
            "deepseek-v4.1-flash-1017",
            review_budget_usd=200,
            review_tokens=tokens,
        )
        self.assertEqual(tight.get("reviewer").model_id, "gpt-6.2-sol")
        wide = choose(
            self._cache(),
            self._snapshot(),
            "deepseek-v4.1-flash-1017",
            review_budget_usd=1_000_000,
            review_tokens=tokens,
        )
        # A budget is a cap, not a target: the cheapest material upgrade wins.
        self.assertEqual(wide.get("reviewer").model_id, "gpt-6.2-sol")
        strict = choose(
            self._cache(),
            self._snapshot(),
            "deepseek-v4.1-flash-1017",
            review_budget_usd=1_000_000,
            review_tokens=tokens,
            min_gain=0.15,
        )
        self.assertEqual(strict.get("reviewer").model_id, "gpt-6.2-astra")

    def test_a_budget_below_the_cheapest_material_upgrade_keeps_the_builder(self) -> None:
        tokens = Tokens(input=75_000_000, output=8_000_000)
        portfolio = choose(
            self._cache(),
            self._snapshot(),
            "deepseek-v4.1-flash-1017",
            review_budget_usd=10,
            review_tokens=tokens,
        )
        self.assertEqual(portfolio.get("reviewer").model_id, "deepseek-v4.1-flash-1017")
        self.assertIn("no model is both", portfolio.get("reviewer").reason)

    def test_runner_uses_a_cheaper_nondominated_model(self) -> None:
        cache = self._cache()
        cache.models["cheap-coder"] = benchmarks_mod.Benchmark(coding=70.0)
        snap = self._snapshot()
        snap.models["cheap-coder"] = ModelMarket(
            model_id="cheap-coder",
            name="Cheap Coder",
            context=1_000_000,
            list_price=Price(0.01, 0.04),
            best=Price(0.005, 0.02),
            realised_discount=50.0,
        )
        portfolio = choose(cache, snap, "deepseek-v4.1-flash-1017")
        self.assertEqual(portfolio.get("runner").model_id, "cheap-coder")

    def test_a_model_with_no_live_offer_is_not_selectable(self) -> None:
        cache = self._cache()
        cache.models["ghost"] = benchmarks_mod.Benchmark(coding=99.0, hle=99.0, frontier_math=99.0)
        snap = self._snapshot()
        snap.models["ghost"] = ModelMarket(
            model_id="ghost",
            name="Ghost",
            context=1_000_000,
            list_price=Price(0.10, 0.10),
            best=None,
            realised_discount=0.0,
        )
        portfolio = choose(cache, snap, "deepseek-v4.1-flash-1017")
        self.assertNotIn("ghost", portfolio.model_ids())
        self.assertNotEqual(portfolio.get("judge").model_id, "ghost")

    def test_dominated_verdict_is_measured_against_its_dominator(self) -> None:
        cache = self._cache()
        cache.models["weak"] = benchmarks_mod.Benchmark(coding=77.0)
        cache.models["strong"] = benchmarks_mod.Benchmark(coding=88.0)
        snap = self._snapshot()
        snap.models["weak"] = ModelMarket(
            model_id="weak",
            name="Weak",
            context=1_000_000,
            list_price=Price(2.0, 2.0),
            best=Price(2.0, 2.0),
            realised_discount=0.0,
        )
        snap.models["strong"] = ModelMarket(
            model_id="strong",
            name="Strong",
            context=1_000_000,
            list_price=Price(1.0, 1.0),
            best=Price(1.0, 1.0),
            realised_discount=0.0,
        )
        portfolio = choose(cache, snap, "deepseek-v4.1-flash-1017")
        rows = report._frontier_rows(
            snap, cache, portfolio, Tokens(input=75_000_000, output=8_000_000), 0.05
        )
        weak = next(row for row in rows if row["model"] == "weak")
        self.assertEqual(weak["delta"], 0.6)  # +0.6 over the builder
        self.assertIn("vs dominator", weak["verdict"])
        self.assertIn("-11.0 pts", weak["verdict"])  # 77.0 vs 88.0

    def test_the_judge_can_sit_off_the_review_frontier(self) -> None:
        cache = self._cache()
        cache.models["reasoner"] = benchmarks_mod.Benchmark(
            coding=95.0, hle=99.0, frontier_math=99.0
        )
        cache.models["cheap-smart"] = benchmarks_mod.Benchmark(coding=96.0, hle=0.0, frontier_math=0.0)
        snap = self._snapshot()
        snap.models["reasoner"] = ModelMarket(
            model_id="reasoner",
            name="Reasoner",
            context=1_000_000,
            list_price=Price(100.0, 100.0),
            best=Price(100.0, 100.0),
            realised_discount=0.0,
        )
        snap.models["cheap-smart"] = ModelMarket(
            model_id="cheap-smart",
            name="Cheap Smart",
            context=1_000_000,
            list_price=Price(1.0, 1.0),
            best=Price(1.0, 1.0),
            realised_discount=0.0,
        )
        portfolio = choose(cache, snap, "deepseek-v4.1-flash-1017")
        self.assertEqual(portfolio.get("judge").model_id, "reasoner")
        self.assertIn("reasoner", portfolio.rejected or {})

    def test_negative_policy_values_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            choose(self._cache(), self._snapshot(), "deepseek-v4.1-flash-1017", min_gain=-0.01)
        with self.assertRaises(ValueError):
            choose(self._cache(), self._snapshot(), "deepseek-v4.1-flash-1017", min_gain=1.5)
        with self.assertRaises(ValueError):
            choose(
                self._cache(),
                self._snapshot(),
                "deepseek-v4.1-flash-1017",
                review_budget_usd=-1,
            )

    def test_policy_values_are_user_overridable(self) -> None:
        cache = self._cache()
        cache.models["cheap-coder"] = benchmarks_mod.Benchmark(coding=70.0)
        snap = self._snapshot()
        snap.models["cheap-coder"] = ModelMarket(
            model_id="cheap-coder",
            name="Cheap Coder",
            context=1_000_000,
            list_price=Price(0.01, 0.04),
            best=Price(0.005, 0.02),
            realised_discount=50.0,
        )
        self.assertEqual(
            choose(cache, snap, "deepseek-v4.1-flash-1017").get("runner").model_id,
            "cheap-coder",
        )
        self.assertEqual(
            choose(
                cache,
                snap,
                "deepseek-v4.1-flash-1017",
                runner_floor=80,
            ).get("runner").model_id,
            "deepseek-v4.1-flash-1017",
        )
        with self.assertRaises(ValueError):
            choose(cache, snap, "deepseek-v4.1-flash-1017", min_context=2_000_000)
        for kwargs in (
            {"runner_floor": -1},
            {"builder_floor": 101},
            {"judge_coding_weight": 1.1},
            {"hle_weight": -0.1},
            {"blend_output_share": -0.1},
        ):
            with self.assertRaises(ValueError):
                choose(cache, snap, "deepseek-v4.1-flash-1017", **kwargs)

    def test_portfolio_refuses_an_unscored_market(self) -> None:
        empty = benchmarks_mod.BenchmarkCache(
            source="test", fetched_at=datetime.now(timezone.utc), models={}
        )
        with self.assertRaises(ValueError):
            choose(empty, self._snapshot(), "deepseek-v4.1-flash-1017")

    def test_all_offers_missing_is_a_refusal_not_a_list_price_fallback(self) -> None:
        snap = PortfolioTests()._snapshot()
        stripped = Snapshot(
            provider=snap.provider,
            base_url=snap.base_url,
            fetched_at=snap.fetched_at,
            capabilities=snap.capabilities,
            models={key: replace(market, best=None) for key, market in snap.models.items()},
        )
        with self.assertRaises(ValueError):
            choose(self._cache(), stripped, "deepseek-v4.1-flash-1017")

    def test_a_review_budget_without_volume_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            choose(
                self._cache(),
                self._snapshot(),
                "deepseek-v4.1-flash-1017",
                review_budget_usd=10,
            )


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

    def test_stale_benchmark_cache_is_reported_and_policy_is_echoed(self) -> None:
        cache = replace(
            PortfolioTests()._cache(),
            fetched_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        snap = PortfolioTests()._snapshot()
        portfolio = choose(cache, snap, "deepseek-v4.1-flash-1017")
        task = TaskSpec(
            id="1.1",
            title="Add a filter",
            type="feature",
            verify=("pytest tests/test_cli.py -q",),
        )
        payload = report.build(
            snapshot=snap,
            budget=calibration.default_budget(),
            portfolio=portfolio,
            routing=routing.RoutingMap(change="demo", tasks={"1.1": task}),
            decisions=[routing.route(task, "deepseek-v4.1-flash-1017")],
            cache=cache,
            baseline="deepseek-v4.1-flash-1017",
            baseline_source="test",
            runner_floor=80,
            judge_coding_weight=0.25,
            benchmark_max_age_days=30,
        )
        self.assertEqual(payload["policy"]["runner_floor"], 80)
        self.assertEqual(payload["policy"]["judge_coding_weight"], 0.25)
        self.assertIn("0.25*coding + 0.75*", payload["policy"]["judge_score"])
        self.assertGreater(payload["benchmarks"]["age_days"], 30)
        self.assertTrue(
            any("benchmark cache is stale" in item["title"].lower() for item in payload["callouts"])
        )

    def test_html_escapes_task_titles(self) -> None:
        cache = PortfolioTests()._cache()
        snap = PortfolioTests()._snapshot()
        portfolio = choose(cache, snap, "deepseek-v4.1-flash-1017")
        task = TaskSpec(
            id="1.1",
            title="<script>alert(1)</script>",
            type="feature",
            verify=("pytest tests/test_cli.py -q",),
        )
        payload = report.build(
            snapshot=snap,
            budget=calibration.default_budget(),
            portfolio=portfolio,
            routing=routing.RoutingMap(change="demo", tasks={"1.1": task}),
            decisions=[routing.route(task, "deepseek-v4.1-flash-1017")],
            cache=cache,
            baseline="deepseek-v4.1-flash-1017",
            baseline_source="test",
        )
        html_text = report.render_html(payload)
        self.assertNotIn("<script>alert(1)</script>", html_text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_text)

    def test_price_multiple_never_rounds_a_premium_to_one_x(self) -> None:
        self.assertEqual(report._multiple(1.14), "1.1")
        self.assertEqual(report._multiple(9.94), "9.9")
        self.assertEqual(report._multiple(17.4), "17")


class CliPlanTests(unittest.TestCase):
    def _budget(self):
        base = calibration.default_budget()
        reviewer = replace(
            base.role("reviewer"),
            monthly_total=Tokens(input=75_000_000, output=8_000_000, cache_read=0),
            sessions=300,
            uncalibrated=False,
        )
        return calibration.build_budget(
            [base.role("builder"), reviewer, base.role("runner"), base.role("judge")]
        )

    def _fixture(self, directory: Path) -> tuple[Path, Path, Path, Path, Path]:
        cache = PortfolioTests()._cache()
        snap = PortfolioTests()._snapshot()
        snap_path = directory / "snapshot.json"
        bench_path = directory / "benchmarks.json"
        budget_path = directory / "budget.yaml"
        config_path = directory / "config.yaml"
        change = directory / "change"
        change.mkdir()
        snapshot.save(snap, snap_path)
        benchmarks_mod.save(cache, bench_path)
        calibration.save_budget(self._budget(), budget_path)
        config_path.write_text(
            'model:\n  default: "deepseek-v4.1-flash-1017"\n', encoding="utf-8"
        )
        (change / "tasks.md").write_text(
            """- [ ] 1.1 Add a flag [type: feature] [verify: pytest tests/a.py -q]
- [ ] 1.2 Fix a bug [type: bugfix] [verify: pytest tests/b.py -q]
""",
            encoding="utf-8",
        )
        return snap_path, budget_path, bench_path, config_path, change

    def _run(self, directory: Path, *extra: str) -> dict:
        snap, budget, bench, config, change = self._fixture(directory)
        out = directory / "report"
        argv = [
            "plan",
            "--change",
            str(change),
            "--snapshot",
            str(snap),
            "--budget",
            str(budget),
            "--benchmarks",
            str(bench),
            "--profile-config",
            str(config),
            "--out",
            str(out),
            *extra,
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(argv)
        self.assertEqual(code, 0)
        return json.loads((out / "report.json").read_text(encoding="utf-8"))

    def test_without_a_budget_the_reviewer_is_the_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._run(Path(tmp))
        roles = {row["role"]: row["model"] for row in payload["portfolio"]}
        self.assertEqual(roles["reviewer"], "deepseek-v4.1-flash-1017")
        self.assertEqual(roles["runner"], "deepseek-v4.1-flash-1017")
        bugfix = next(task for task in payload["tasks"] if task["id"] == "1.2")
        feature = next(task for task in payload["tasks"] if task["id"] == "1.1")
        self.assertEqual(bugfix["reviewer"], "deepseek-v4.1-flash-1017")
        self.assertIsNone(feature["reviewer"])

    def test_the_review_budget_flag_reaches_the_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._run(Path(tmp), "--review-budget", "80")
        roles = {row["role"]: row["model"] for row in payload["portfolio"]}
        self.assertEqual(roles["reviewer"], "gpt-6.2-sol")
        self.assertEqual(payload["policy"]["review_budget_usd"], 80.0)

    def test_new_policy_flags_reach_the_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._run(
                Path(tmp),
                "--runner-floor", "80",
                "--builder-floor", "60",
                "--min-context", "500000",
                "--judge-coding-weight", "0.25",
                "--hle-weight", "0.75",
                "--blend-output-share", "0.4",
                "--callout-multiple", "4",
                "--judge-share-alert", "0.3",
                "--review-share-alert", "0.6",
                "--benchmark-max-age-days", "60",
                "--fresh-hours", "6",
                "--aging-hours", "24",
                "--expired-hours", "72",
            )
        policy = payload["policy"]
        self.assertEqual(policy["runner_floor"], 80.0)
        self.assertEqual(policy["builder_floor"], 60.0)
        self.assertEqual(policy["min_context"], 500000)
        self.assertEqual(policy["judge_coding_weight"], 0.25)
        self.assertEqual(policy["hle_weight"], 0.75)
        self.assertEqual(policy["blend_output_share"], 0.4)
        self.assertEqual(policy["callout_multiple"], 4.0)
        self.assertEqual(policy["judge_share_alert"], 0.3)
        self.assertEqual(policy["review_share_alert"], 0.6)
        self.assertEqual(policy["benchmark_max_age_days"], 60.0)
        self.assertEqual(policy["fresh_hours"], 6.0)
        self.assertEqual(policy["aging_hours"], 24.0)
        self.assertEqual(policy["provisional_hours"], 72.0)

    def test_help_lists_every_policy_override(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "run.py"), "plan", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in (
            "--runner-floor",
            "--builder-floor",
            "--min-context",
            "--judge-coding-weight",
            "--hle-weight",
            "--blend-output-share",
            "--callout-multiple",
            "--judge-share-alert",
            "--review-share-alert",
            "--benchmark-max-age-days",
            "--fresh-hours",
            "--aging-hours",
            "--expired-hours",
        ):
            self.assertIn(flag, result.stdout)

    def test_network_and_calibration_flags_are_documented(self) -> None:
        for command, flags in (
            ("refresh", ("--timeout", "--retries", "--workers")),
            ("refresh-benchmarks", ("--url", "--timeout", "--retries")),
            ("calibrate", ("--window", "--month-days")),
        ):
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "run.py"), command, "--help"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            for flag in flags:
                self.assertIn(flag, result.stdout, f"{command} is missing {flag}")

    def test_plan_runs_end_to_end_as_a_subprocess(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            snap, budget, bench, config, change = self._fixture(directory)
            out = directory / "report"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "run.py"),
                    "plan",
                    "--change", str(change),
                    "--snapshot", str(snap),
                    "--budget", str(budget),
                    "--benchmarks", str(bench),
                    "--profile-config", str(config),
                    "--out", str(out),
                    "--runner-floor", "80",
                    "--judge-coding-weight", "0.25",
                    "--hle-weight", "0.75",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((out / "report.json").read_text(encoding="utf-8"))
            self.assertTrue((out / "report.html").is_file())
        roles = {row["role"]: row["model"] for row in payload["portfolio"]}
        self.assertEqual(roles["builder"], "deepseek-v4.1-flash-1017")
        self.assertEqual(payload["policy"]["runner_floor"], 80.0)
        self.assertEqual(payload["policy"]["judge_coding_weight"], 0.25)
        self.assertEqual(roles["reviewer"], "deepseek-v4.1-flash-1017")
        self.assertAlmostEqual(payload["costs"]["total"], 7.10, places=2)
        self.assertIn("costs", payload)

    def test_subprocess_rejects_an_invalid_policy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            snap, budget, bench, config, change = self._fixture(directory)
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "run.py"),
                    "plan",
                    "--change", str(change),
                    "--snapshot", str(snap),
                    "--budget", str(budget),
                    "--benchmarks", str(bench),
                    "--profile-config", str(config),
                    "--out", str(directory / "report"),
                    "--runner-floor", "101",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("runner_floor", result.stderr)

    def test_invalid_policy_flags_exit_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            snap, budget, bench, config, change = self._fixture(directory)
            base = [
                "plan",
                "--change", str(change),
                "--snapshot", str(snap),
                "--budget", str(budget),
                "--benchmarks", str(bench),
                "--profile-config", str(config),
                "--out", str(directory / "report"),
            ]
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(base + ["--min-gain", "2"]), 1)
                self.assertEqual(cli.main(base + ["--review-budget", "-1"]), 1)
                self.assertEqual(cli.main(base + ["--runner-floor", "101"]), 1)
                self.assertEqual(cli.main(base + ["--judge-coding-weight", "1.1"]), 1)
                self.assertEqual(cli.main(base + ["--callout-multiple", "0"]), 1)
                self.assertEqual(cli.main(base + ["--review-share-alert", "1.1"]), 1)
                self.assertEqual(
                    cli.main(base + ["--fresh-hours", "60", "--aging-hours", "48"]), 1
                )

    def test_an_expired_snapshot_is_refused_unless_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            snap_path, budget, bench, config, change = self._fixture(directory)
            snap = snapshot.load(snap_path)
            stale = Snapshot(
                provider=snap.provider,
                base_url=snap.base_url,
                fetched_at=datetime.now(timezone.utc) - timedelta(days=8),
                capabilities=snap.capabilities,
                models=snap.models,
            )
            snapshot.save(stale, snap_path)
            argv = [
                "plan",
                "--change",
                str(change),
                "--snapshot",
                str(snap_path),
                "--budget",
                str(budget),
                "--benchmarks",
                str(bench),
                "--profile-config",
                str(config),
                "--out",
                str(directory / "report"),
            ]
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(argv), 1)
                self.assertEqual(cli.main(argv + ["--accept-stale"]), 0)


if __name__ == "__main__":
    unittest.main()