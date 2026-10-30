---
name: oss-forensics
description: "Investigate a compromised dependency or supply chain."
version: 1.1.0
author: Teknium (teknium1), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: security
triggers:
  - "investigate this repository"
  - "check for supply chain compromise"
  - "was this repo compromised"
  - "recover deleted commits"
  - "forensic analysis of [owner/repo]"
metadata:
  hermes:
    tags: [Security, Forensics, GitHub, Supply-Chain]
    related_skills: []
---

# OSS Security Forensics

A 7-phase multi-agent framework for investigating open-source supply-chain attacks:
GitHub Archive, Wayback Machine, GitHub API, local git analysis, IOC extraction,
evidence-backed hypothesis formation and validation, and a final forensic report.

Defensive investigation only. Never run code found inside the target repository.

Resolve `skill_dir` with `skill_view(name='oss-forensics')`; all script, reference
and template paths below are relative to it.

## Anti-hallucination guardrails

Read before every step. Violating them invalidates the report.

1. **Evidence-first.** Every claim in a report, hypothesis or summary cites at least
   one evidence ID (`EV-XXXX`). Assertions without citations are forbidden.
2. **Stay in your lane.** Each investigator has one data source and must not mix
   sources. The GH Archive investigator does not query the GitHub API, and vice
   versa. Role boundaries are hard.
3. **Fact vs hypothesis.** Mark unverified inferences `[HYPOTHESIS]`. Only statements
   verified against original sources may be stated as fact.
4. **No fabricated evidence.** The validator mechanically checks that every cited
   evidence ID exists in the store before accepting a hypothesis.
5. **Proof-required disproval.** A hypothesis cannot be dismissed without a specific,
   evidence-backed counter-argument. "No evidence found" makes it inconclusive, not
   disproven.
6. **Double-verification.** Any commit SHA, URL or external identifier cited as
   evidence must be confirmed from at least two sources before being marked verified.
7. **Suspicious code.** Never run code from the investigated repository locally.
   Analyse statically, or use `execute_code` in a sandbox.
8. **Secret redaction.** Any credential discovered is redacted to `[REDACTED]` in the
   report; log it internally only.

## Prerequisites

- `GITHUB_TOKEN` (or authenticated `gh`) — unauthenticated is 60 req/hour, unusable.
  Check `X-RateLimit-Remaining`; below 100, pause until `X-RateLimit-Reset`.
- Optional: BigQuery credentials (`gcloud auth application-default login`) for the GH
  Archive investigator. If absent, skip that investigator and note it in the report.
  Always `--dry_run` first (10 TiB/day free tier).
- Wayback CDX API has no formal limit; stay at 1–2 req/sec.

If rate-limited mid-investigation, record the partial results in the evidence store
and note the limitation in the report.

## Phase 0 — Initialization

```bash
mkdir investigation_<owner>_<repo> && cd $_
python <skill_dir>/scripts/evidence-store.py --store evidence.json list   # init
cp <skill_dir>/templates/forensic-report.md ./investigation-report.md
```

Create `iocs.md`. Record the start time, target repository and investigation goal.

## Phase 1 — Prompt parsing and IOC extraction

Extract from the user's request: target `owner/repo`; actors (handles, emails); time
window; provided IOCs (commit SHAs, file paths, package names, IPs, domains, tokens,
malicious URLs); linked vendor reports.

Populate `iocs.md` with `type` (COMMIT_SHA, FILE_PATH, API_KEY, SECRET, IP_ADDRESS,
DOMAIN, PACKAGE_NAME, ACTOR_USERNAME, MALICIOUS_URL, OTHER), `value`, `source`.
Taxonomy: `references/evidence-types.md`.

## Phase 2 — Parallel evidence collection

Spawn up to 5 investigators via `delegate_task` (batch mode, max 3 concurrent), each
with a **single data source**. Pass the IOC list and time window in each task's
`context`.

**1. Local git** — local repository only, no external APIs.

```bash
git clone https://github.com/OWNER/REPO.git target_repo && cd target_repo
git log --all --full-history --stat --format="%H|%ae|%an|%ai|%s" > ../git_log.txt
git fsck --lost-found --unreachable 2>&1 | grep commit > ../dangling_commits.txt
git reflog --all > ../reflog.txt
git branch -a -v > ../branches.txt
git log --all --diff-filter=A --name-only --format="%H %ai" -- "*.so" "*.dll" "*.exe" "*.bin" > ../binary_additions.txt
git log --show-signature --format="%H %ai %aN" > ../signature_check.txt 2>&1
```

Collect as evidence: dangling commit SHAs · reflog history-rewrite evidence ·
unsigned commits from verified contributors · suspicious binary additions.
Recovery: `references/recovery-techniques.md`.

**2. GitHub API** — REST API only, no local git.

```bash
for ep in commits pulls?state=all issues?state=all contributors events releases?per_page=100; do
  curl -s "https://api.github.com/repos/OWNER/REPO/${ep}?per_page=100" > "api_${ep%%\?*}.json"
done
curl -s "https://api.github.com/repos/OWNER/REPO/git/commits/SHA" > commit_detail.json
```

Flag as evidence: a PR in the archive but missing from the API (deletion) · a
contributor in archive events but not in the contributor list (revocation) · a commit
in archive PushEvents but not in the API list (force-push).

**3. Wayback Machine** — CDX API only.

```bash
curl -s "https://web.archive.org/cdx/search/cdx?url=github.com/OWNER/REPO&output=json&limit=100&from=YYYYMMDD&to=YYYYMMDD" > wayback_main.json
curl -s "https://web.archive.org/cdx/search/cdx?url=github.com/OWNER/REPO/issues/NUM&output=json&limit=50" > wayback_issue.json
curl -s "https://web.archive.org/cdx/search/cdx?url=github.com/OWNER/REPO/releases/tag/*&output=json" > wayback_tags.json
```

Recovers deleted READMEs, issues, PRs, releases and wiki pages.
Parameters: `references/github-archive-guide.md`.

**4. GH Archive / BigQuery** — tamper-proof record of all public GitHub events.

```bash
bq query --use_legacy_sql=false --dry_run "
SELECT created_at, actor.login, payload.commits, payload.before, payload.head,
       payload.size, payload.distinct_size
FROM \`githubarchive.month.*\`
WHERE _TABLE_SUFFIX BETWEEN 'YYYYMM' AND 'YYYYMM'
  AND type = 'PushEvent' AND repo.name = 'OWNER/REPO'
LIMIT 1000"
```

Always `--dry_run` first; filter with `_TABLE_SUFFIX`; select only needed columns;
add `LIMIT` unless aggregating. `payload.size > 0 AND payload.distinct_size = 0` is a
force-push indicator. Also collect `DeleteEvent`s and `WorkflowRunEvent`s.

**5. IOC enrichment** — passive public sources only.

Per commit SHA, try `github.com/OWNER/REPO/commit/SHA.patch` · per domain/IP, passive
DNS and WHOIS via `web_extract` · per package name, check npm/PyPI for malicious-
package reports · per actor, profile, contribution history and account age.

## Phase 3 — Evidence consolidation

1. `python <skill_dir>/scripts/evidence-store.py --store evidence.json list`
2. Verify each `content_sha256` against its original source.
3. Group by timeline, actor, and IOC.
4. Identify **discrepancies** — items in one source but absent from another are the
   key deletion indicators.
5. Flag `[VERIFIED]` (2+ independent sources) or `[UNVERIFIED]` (single source).

## Phase 4 — Hypothesis formation

A hypothesis states a specific claim ("Actor X force-pushed to BRANCH on DATE to
erase commit SHA"), cites at least 2 supporting evidence IDs, identifies what would
disprove it, and stays `[HYPOTHESIS]` until validated. Spawn a `delegate_task`
sub-agent per hypothesis to hunt for **disconfirming** evidence first.

Templates per attack type (maintainer compromise, dependency confusion, CI/CD
injection, typosquatting, credential leak): `references/investigation-templates.md`.

## Phase 5 — Hypothesis validation

The validator mechanically checks: every cited ID exists in `evidence.json` (a missing
ID rejects the hypothesis as potentially fabricated) · every `[VERIFIED]` item was
confirmed from 2+ sources · the timeline supports the claim · a benign explanation
cannot produce the same pattern.

- `VALIDATED` — evidence cited, verified, consistent, no plausible alternative.
- `INCONCLUSIVE` — supported, but alternatives exist or evidence is insufficient.
- `REJECTED` — missing IDs, unverified evidence cited as fact, or inconsistency.

Rejected hypotheses feed back to Phase 4, max 3 iterations.

## Phase 6 — Final report

Populate `investigation-report.md` from `templates/forensic-report.md`. Mandatory
sections: executive summary (one paragraph, verdict + confidence) · timeline with
citations · validated hypotheses with status and evidence IDs · evidence registry
(`EV-XXXX`, source, type, verification status) · IOC list · chain of custody ·
recommendations.

Every factual claim carries at least one `[EV-XXXX]`. The summary states confidence
(High/Medium/Low). All secrets are `[REDACTED]`.

## Phase 7 — Completion

Archive the investigation directory. If compromise is confirmed, list immediate
mitigations (rotate credentials, pin dependency hashes, notify affected users),
identify affected versions, and note disclosure obligations. Present the report.

## Ethics and disclosure

Defensive security only. Not for harassment or stalking, doxxing, competitive
intelligence on unauthorized repositories, or publishing unvalidated accusations.
Minimal intrusion: collect only what validates or refutes the hypothesis.

On a genuine compromise: notify maintainers privately first, allow reasonable
remediation time (typically 90 days), coordinate with package registries if published
packages are affected, and file a CVE if appropriate.

## References

- `references/github-archive-guide.md` — BigQuery queries, CDX API, the 12 event types
- `references/evidence-types.md` — IOC taxonomy, evidence source types, observation types
- `references/recovery-techniques.md` — recovering deleted commits, PRs, issues
- `references/investigation-templates.md` — hypothesis templates per attack type
- `scripts/evidence-store.py` — CLI for the evidence JSON store
- `templates/forensic-report.md`, `templates/malicious-package-report.md` — report shapes
