# Configuration plumbing

A settings file that looks authoritative and is read by nothing. The defect is not a
wrong value — it is an absent read, so every value is wrong and the validator still passes.

## Detect, cheapest proof first

- **A dry run that prints resolved values.** Run it with no config and again with a config
  that differs in every field. Identical output on both runs means nothing read the file.
  This needs no model call and no run directory, so it is the first check, not the last.
- **Grep for the reader, not the key.** `grep -rn '<key>' scripts/` returns the validator and
  the renderer; if the module that performs the work never imports the config module, none of
  its keys are read. A validator importing it does not count.
- **Diff the two layers' defaults.** Config says `advisory`/`3`, the CLI says `full`/`8` — a
  disagreeing pair is the tell that one layer was written and never wired. Whichever layer the
  tests assert against is the contract; the other is the one that moved.

## Repair

1. **Flags default to `None`**, so "unset" is distinguishable from "set to the default" by the
   value the user actually typed.
2. **One pure resolver at the entry point**: `resolve(mode, samples, max_rounds, threshold, cfg)`
   returning the effective tuple. Flag wins, else `[section]`, else the shipped default. Pure
   means it is unit-testable without a subprocess or a config file on disk.
3. **Keep derived fallbacks after the config.** A threshold that defaults from a calibration
   manifest stays last in the chain, and the precedence is stated once: flag > config > derived.
4. **Move parser-level contract tests to the resolved value.** A test asserting
   `args.mode == "full"` on the parser now asserts an implementation detail; assert what a bare
   run resolves to instead. Do this only where the parser default was an internal default — a
   contract that genuinely promises the parser surface stays as it was.
5. **Fix the layer the evidence names.** When a tested contract says `full`/`8` and the config
   ships `advisory`/`3`, the config is wrong. Do not rewrite the contract to match the file.
6. **Print the resolved values and the config path the run read** in the plan. That line is the
   proof, and it also tells a user which file a stale value came from.

## Proof: four runs, no model call

| run | expected |
|---|---|
| no config | shipped defaults |
| config differing in every field | the config's values |
| same config + explicit flags | the flags' values |
| no config, compared to the pre-fix build | **unchanged** |

The last row is the one that keeps the fix honest: making the file work must not silently
change what a bare run does. If the defaults themselves were out of step with a tested
contract, move the defaults and say so; do not let a plumbing fix ship a behaviour change.

## Pitfalls

- **A writer that emits what its own reader cannot parse.** Render the file through the same
  parser before it lands; a first-run path that writes an unreadable config fails exactly once
  per machine and looks like a user error.
- **Creating the file to "fix" its absence.** If the defaults are already the calibrated values
  and a test asserts the product works with no file, a written config only freezes today's
  numbers against future calibration. Leave it absent and point at the setup verb.
- **A key that exists only in the renderer's comments.** Comment text describing a default is
  not a read; the comment and the behaviour drift apart silently.
