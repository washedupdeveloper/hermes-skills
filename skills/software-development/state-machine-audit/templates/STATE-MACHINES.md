# State machines

> One file for the whole system. Replace the placeholders; keep the tables.

Status: <commit/audit scope>.

## Inventory

| machine | owner | persisted? |
|---|---|---|
| M1 <name> | `<module.function>` | no / file / db |

## M1 — <name>

**States:** `<START>`, `<RUNNING>`, `<DONE>`, `<FAILED>`, `<CLEANED>`.

**Invariants**

- <falsifiable statement>.
- <falsifiable statement>.

**Transitions**

| from | event | guard | to | side effect |
|---|---|---|---|---|
| START | <event> | <guard> | RUNNING | <write/spawn> |

**Invalid transitions found**

- <state/transition>; evidence: `<test or live probe>`; issue `SM-01`.

## Confirmed issues

| id | pri | invalid transition | impact | fix / evidence | status |
|---|---|---|---|---|---|
| SM-01 | P0 | <...> | <...> | <fix + test> | fixed / residual |

## Residual risks

| id | race/limit | why not fixed | missing primitive |
|---|---|---|---|
| SM-02 | <...> | <...> | <...> |

## Verification

```sh
python -m pytest -q
```

## Update rule

A state, guard, invariant or transition change updates this file in the same
commit as the code and regression.
