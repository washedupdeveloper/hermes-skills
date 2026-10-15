# <Project> — Milestone Plan

**Goal.** <one paragraph: what is being built and the single outcome that defines done.>

**Status.** <research complete / planning / building>. <one line on what exists so far.>

**How to read.** Each milestone has a Goal, the Research inputs it applies, concrete Deliverables,
and Acceptance criteria checkable by a command or an observable artifact. `Size` is relative effort
(S/M/L); `Depends` lists prerequisites.

---

## 0. Design pillars (fixed by research + the kickoff interview)

| Pillar | Decision | Source |
|---|---|---|
| Foundation | <...> | interview |
| Platform | <...> | interview |
| ... | | |

### 0.1 Reconciliations the research forced

1. **<tension>.** <how it was resolved and why.>

---

## M0 — <name>
**Goal.** <outcome.>

**Research inputs.** <report §, or "none (enabling)".>

**Deliverables**
- <artifact>

**Acceptance criteria**
- <checkable by a command or observable artifact>

**Size** S · **Depends** —

---

## M1 — <name>
**Goal.** <outcome.>
**Research inputs.** <...>
**Deliverables**
- <...>
**Acceptance criteria**
- <...>
**Size** M · **Depends** M0

---

<!-- repeat M2..Mn -->

---

## 1. Dependency graph

```
M0 ─▶ M1 ─▶ M2 ─┐
                ├─▶ M4 ─▶ M5 ─▶ M6
        M1 ─▶ M3 ┘
```

## 2. Research → decision traceability

| Finding (source) | Applied in |
|---|---|
| <finding> | <milestone> |

## 3. Open decisions (confirm before/at the relevant milestone)

1. **<topic>** — <working default>.
