# Four harness rules from DeepSeek Harness, and its framework refused

**Decision.** Adopted as practice and as skills: a registration returns a disposer and
teardown unwinds it; model-visible means logged; every invariant gets a gate with a
negative control; one home per fact, with a record of what was given up. The framework is
not adopted.

**Why.** This repo can already fail a gate on each rule, so each is an extension of the
existing gate rather than a new one. The transferable sentence: an assertion belongs in
the cheapest tier that can make it.

**Rejected, each for a cost this repo would pay.** *Cordis as a dependency* — every rule
above is a discipline, not a framework. *Per-file 100% coverage* — it was green through a
bridge that could not open a session. *Bilingual documentation pairs* — two files per fact
drift, and a pairing hash proves nothing about translation. *Branded ids at every
boundary* — worth it across 342 packages, overhead across Markdown files. *A second
decision-record lifecycle* — `docs/adr/` is the same object at this size.
