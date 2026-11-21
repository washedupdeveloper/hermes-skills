# Council integration

The selected stack is executed by review-council v2 through a reviewer
adapter. `hermes` boots one profile per sample; `direct` sends one Chat
Completions request per sample and is the low-latency path.

## Direct adapter configuration

| variable | default | meaning |
|---|---|---|
| `COUNCIL_DIRECT_BASE_URL` | `https://api.surplusintelligence.ai/v1` | endpoint root; `/chat/completions` appended |
| `COUNCIL_DIRECT_MODEL` | required | model id sent in the request |
| `COUNCIL_DIRECT_API_KEY` | required | bearer token; never recorded |
| `COUNCIL_DIRECT_MAX_TOKENS` | `8192` | response cap |

`council review --agent direct`. The identity is
`sha256(model|base_url|prompt_version|temperature)`; the key is excluded. A
missing config is `ReviewerMissing`; an HTTP error, malformed body or empty
answer is `OSError`. It never falls back to another model.

## Working-tree checks

`council` inside `nix develop` resolves to the installed binary, not the
working tree. To see the adapter you just added:

```bash
PYTHONPATH=src python -m council agents
```

Run the gates from the repo root:

```bash
nix develop --command python -m pytest -q -p no:cacheprovider
nix develop --command mypy src
nix develop --command ./bin/council-verify
```

`pytest -q | tail` reports the pipe's status, not pytest's. Run the command
without a pipe or capture its exit status explicitly.

## Gates a new adapter trips

- `tests/test_architecture.py` keeps an explicit `ADAPTERS` set. A new effectful
  module under `agents/` must be added there, or both architecture tests fail.
- `tests/test_size.py` is a deliberate ratchet. Raise `SOURCE_LIMIT` in the same
  diff that needs the room, with a comment; never let it drift.
- `tests/test_files.py` requires every shipped text file to end with a newline.
- `tests/test_agents.py` asserts the `BUILTIN` order. Adding an adapter updates
  that assertion.
- `claims.toml` and `docs/CLAIMS.md` are a ledger. A claim whose text names the
  builtin set moves with the registry; `./bin/council-verify` runs the check.

## Cost shape

The judge is small volume and expensive per token. The reviewer is the volume
role; when no review budget is set it shares the builder model, and the judge
can dominate a small bill. Report spend and token shares together, because they
are different numbers; never call a share "small" without measuring it.
