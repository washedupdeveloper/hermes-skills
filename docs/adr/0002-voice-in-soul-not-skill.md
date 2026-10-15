# The communication voice lives in `SOUL.md`, not in a skill

The caveman voice is a **standing contract**, so it is the agent's identity
(`SOUL.md`, slot #1 of the system prompt, injected on every turn) rather than a
skill. A skill is chosen per task and **may not be chosen** — a voice that lives only
in a skill is a suggestion, not a voice, and "used when relevant" is not a standard a
communication contract can meet.

The trade is real and is the reason this needed recording: the identity slot costs
**~500 tokens on every turn**, including turns where brevity does not matter, and it
cannot be made conditional. The skill form would cost nothing until loaded and would
therefore almost never apply.

`caveman` is kept as the **on-demand long form** of the same voice — the condensed
contract in `SOUL.md`, the full rules and worked examples in the skill.

Three consumers, one contract, because a council profile is its own `HERMES_HOME`:
the global agent (`$HERMES_HOME/SOUL.md`), the council reviewer and the council
orchestrator (each ships its own under `bots/<member>/SOUL.md`). A global `SOUL.md`
does **not** reach a council bot, which is why the voice is version-controlled in
both repos rather than only applied to the machine.
