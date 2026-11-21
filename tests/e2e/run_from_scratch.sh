#!/usr/bin/env bash
# Black-box end-to-end test: clone the skill repo, build a synthetic Hermes
# home, calibrate, then plan through the CLI. No selector code is imported by
# the fixture builder, so this tests the shipped entry point only.
set -eu
ROOT=${ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}
PYTHON=${PYTHON:-$(command -v python3 || command -v python)}
SHA=$(git -C "$ROOT" rev-parse HEAD)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
git clone -q "$ROOT" "$T/repo"
git -C "$T/repo" checkout -q "$SHA"
REPO="$T/repo"
SKILL="$REPO/skills/software-development/model-routing"
export T REPO SKILL

"$PYTHON" - <<'PY'
import json, os, sqlite3
from datetime import datetime, timezone
from pathlib import Path

t = Path(os.environ["T"])
home = t / "home"
home.mkdir()
db = sqlite3.connect(home / "state.db")
db.execute("""
create table session_model_usage (
  session_id text, model text, input_tokens integer, output_tokens integer,
  cache_read_tokens integer, reasoning_tokens integer, api_call_count integer,
  last_seen real
)
""")
db.execute(
    "insert into session_model_usage values (?,?,?,?,?,?,?,?)",
    ("s1", "m1", 1_000_000, 100_000, 0, 0, 10, datetime.now(timezone.utc).timestamp()),
)
db.commit()
db.close()

now = datetime.now(timezone.utc).isoformat(timespec="seconds")
snapshot = {
    "schema": 1,
    "provider": "synthetic",
    "base_url": "https://synthetic.test/v1",
    "fetched_at": now,
    "capabilities": {"discounts": True, "availability": True},
    "models": {
        "m1": {
            "model_id": "m1",
            "name": "M1",
            "context": 1_000_000,
            "list_price": {"input": 1.0, "output": 2.0, "cache_read": 0.1},
            "best": {"input": 0.5, "output": 1.0, "cache_read": 0.05},
            "realised_discount": 50.0,
            "offers": [],
        },
        "m2": {
            "model_id": "m2",
            "name": "M2",
            "context": 1_000_000,
            "list_price": {"input": 5.0, "output": 10.0},
            "best": {"input": 5.0, "output": 10.0},
            "realised_discount": 0.0,
            "offers": [],
        },
    },
}
(t / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
bench = {
    "source": "synthetic",
    "fetched_at": now,
    "models": {"m1": {"coding": 70.0}, "m2": {"coding": 90.0}},
}
(t / "benchmarks.json").write_text(json.dumps(bench), encoding="utf-8")
(t / "config.yaml").write_text('model:\n  default: "m1"\n', encoding="utf-8")
(t / "sources.json").write_text(
    json.dumps([{"title": "Synthetic source", "url": "https://synthetic.test"}])
    , encoding="utf-8"
)
change = t / "change"
change.mkdir()
(change / "tasks.md").write_text(
    "- [ ] 1.1 Add a flag [type: feature] [verify: pytest tests/a.py -q]\n",
    encoding="utf-8",
)
print(t)
PY

"$PYTHON" "$SKILL/scripts/run.py" calibrate \
  --hermes-home "$T/home" --window 30 --out "$T/budget.yaml" >"$T/calibrate.log"
"$PYTHON" "$SKILL/scripts/run.py" plan \
  --change "$T/change" \
  --snapshot "$T/snapshot.json" \
  --budget "$T/budget.yaml" \
  --benchmarks "$T/benchmarks.json" \
  --profile-config "$T/config.yaml" \
  --sources "$T/sources.json" \
  --runner-floor 80 \
  --out "$T/report" >"$T/plan.log"

"$PYTHON" - <<'PY'
import json, os
from pathlib import Path

t = Path(os.environ["T"])
p = json.loads((t / "report" / "report.json").read_text())
roles = {row["role"]: row["model"] for row in p["portfolio"]}
assert roles == {
    "judge": "m2",
    "reviewer": "m1",
    "builder": "m1",
    "runner": "m1",
}, roles
assert p["costs"]["total"] > 0
assert p["policy"]["runner_floor"] == 80.0
assert p["sources"][0]["title"] == "Synthetic source"
assert (t / "report" / "report.html").is_file()
print("e2e ok", roles, p["costs"]["total"])
PY

if "$PYTHON" "$SKILL/scripts/run.py" plan \
  --change "$T/change" \
  --snapshot "$T/snapshot.json" \
  --budget "$T/budget.yaml" \
  --benchmarks "$T/benchmarks.json" \
  --profile-config "$T/config.yaml" \
  --runner-floor 101 \
  --out "$T/bad" >"$T/bad.log" 2>&1
then
  echo "expected invalid policy to fail" >&2
  exit 1
fi
grep -q "runner_floor" "$T/bad.log"
echo "from-scratch e2e passed at $SHA"