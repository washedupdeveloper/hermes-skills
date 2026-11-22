# OpenSpec-driven agent delivery

## When to Use

Use when one OpenSpec change is executed by several Hermes profiles: route the
roles, create one profile per role, run one role at a time, and close tasks only
from evidence. This is the execution layer; `openspec` owns the artifacts and
`model-routing` owns the selection.

## 1. Make the change executable

- The change has `proposal.md`, `design.md`, `specs/<capability>/spec.md`, and a
  `tasks.md` checklist. Every task carries `[type: ...]` and `[verify: ...]`;
  task IDs are stable and never renumbered.
- Each task has one independently scoped outcome. Do not schedule two writers on
  the same file; run tests after implementation, then review, then docs.
- Validate before any agent runs: `openspec validate <change> --strict`.
- Add `AGENTS.md` at the project root and `collab/protocol.md` with the contract:
  read the change first; claim one task; write `collab/<task>.md` with files,
  predicate, observed output and deviations; never edit `tasks.md`; never edit
  another task's evidence.

## 2. Route the work

- Run `model-routing plan --change <change> --min-discount <key-floor>` and read
  the role cards. Add `--review-budget <cap>` only when an independent reviewer
  is actually wanted; the default is the builder reviewing under a second rubric.
- A provider key's minimum-discount floor applies to the **best live offer**.
  Smoke-test every selected model before creating its profile:

  ```bash
  HERMES_HOME=<scratch-home> hermes -p <role> chat \
    -q 'Reply with exactly OK' --oneshot -Q --in <project>
  ```

  If it returns `minimum_discount_not_met`, change the model or the policy; do not
  create a profile whose model cannot execute.
- A review budget is a cap, not a target. The cheapest model that clears the
  materiality gate wins, and with no budget the builder reviews.

## 3. Create the profile fleet

Use an isolated home for a demo or test run; do not mutate the live default
profile. At minimum:

```bash
H=/tmp/<run>-hermes
mkdir -p "$H"
cp "$HOME/.hermes/config.yaml" "$H/config.yaml"
cp "$HOME/.hermes/.env" "$H/.env"
export HERMES_HOME="$H"

hermes profile create <role> --no-skills --no-alias
cp "$H/.env" "$H/profiles/<role>/.env"
hermes -p <role> config set model.default <model>
hermes -p <role> config set model.provider 'custom:<alias>'
hermes -p <role> config set model.base_url '<provider-base-url>/v1'
```

- `--clone --no-skills` is rejected; use `--no-skills` and copy `.env` yourself,
  or use `--clone` and accept the full skill set.
- `hermes profile list` shows the profile label, not proof of its model. Read
  `hermes -p <role> config get model.default` for every role.
- `--no-skills` is enough when the agents only need file and shell tools; the
  task prompt carries the workflow.

## 4. Run one role per task

Put each prompt under `collab/prompts/<task>.txt`. It names the change and task
ID, lists the files to read, states the exact scope and predicate, names the
evidence path, and forbids editing `tasks.md` or another task's evidence.

```bash
HERMES_HOME=<scratch-home> hermes -p <role> chat \
  --query-file <project>/openspec/changes/<change>/collab/prompts/<task>.txt \
  --oneshot -Q --in <project> --yolo --max-turns 30 --run-budget 600
```

Use `--yolo` only inside a disposable project and cap turns and budget. Run in
dependency order: architecture judge, builder implementation, tests, reviewer,
docs. Capture the log; an agent's "complete" is a claim, not proof.

## 5. Close from evidence

- Check that `collab/<task>.md` exists and its predicate passes independently.
  Only then tick the task in `tasks.md`; the orchestrator owns the checkboxes.
- Write `collab/milestone.md` with the executed profiles and models, task-to-
  evidence map, acceptance results, and the cost/trade-off record.
- Final gate: unit tests, OpenSpec `validate --strict`, the CLI's exit-code cases,
  all checkboxes, and a clean git tree. `validate --strict` checks shape, not
  completion; grep the checkboxes separately.
- Commit the project and report the commit. If `--emit-profiles` is not
  implemented, say the profiles were created manually rather than implying the
  selector emitted them.

## Pitfalls

- **The selector does not read the key's minimum discount.** Pass it explicitly
  and smoke-test the model; selection success is not execution success.
- **Do not let an agent overwrite evidence blindly.** Hermes' file guard may
  refuse an existing file without a current full read; append an execution note
  or deliberately remove and rewrite it. Never claim a write succeeded without
  checking.
- **Tasks without a pass/fail predicate are not runnable.** Stop and scope them;
  do not mark them done.
- **Do not run parallel writers on one file.** Sequence the roles; use parallel
  runs only for independent tasks with disjoint file scopes.
- **Use foreground commands.** A one-shot `hermes chat` returns; do not add sleep
  polling or long blocking waits.
