# Decision matrix template

Copy into the analysis and fill. Keep only rows that discriminate between the
candidates — a row where every candidate scores the same is noise.

## Capability (hard gates — eliminate here first)

| Requirement | Candidate A | Candidate B | Candidate C |
|---|---|---|---|
| Required protocol / spec version | | | |
| Supported hardware list | | | |
| Required device role (coordinator / router / end device / controller) | | | |
| Low-power mode needed by the project | | | |
| Licensing / auditability | | | |

## Maturity (objective signals, all from the repo or tracker)

| Signal | Candidate A | Candidate B | Candidate C |
|---|---|---|---|
| Last commit | | | |
| Release count / latest release | | | |
| Stars / forks | | | |
| Open issues on the feature we need | | | |
| Maintainer count | | | |
| Vendor's own stability wording | | | |

## Tradeoff axes (ordered scales, not adjectives)

Score 1-5 and say what each number means, so the reader can disagree with the
scoring rather than with a vibe.

| Axis | Candidate A | Candidate B | Candidate C |
|---|---|---|---|
| Development speed | | | |
| Runtime safety | | | |
| Toolchain weight | | | |
| Ecosystem depth | | | |
| Fit for the stated priority (power / safety / reach / speed) | | | |

## Output skeleton

1. Bottom line — pick + driving constraint + what would change it.
2. Reality check — architecture facts that constrain the choice.
3. Per candidate — Benefits / Drawbacks / Toolchain / one-line verdict.
4. Direct comparison — the matrices above.
5. The limit that overrides preference.
6. Server-side options, same treatment.
7. Recommended architectures — numbered paths, each a concrete stack.
8. Pitfalls checklist.
9. Sources.
