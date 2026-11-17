---
name: browser-extension-review
description: "Use when reviewing a WebExtension background script."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: software-development
metadata:
  hermes:
    tags: [code-review, webextension, mv3, chrome, firefox, background-script, extension]
    related_skills: [council, defensive-patterns, critical-verdict, web-app-security]
---

# browser-extension-review

Background scripts fail silently. There is no UI to throw into, the event that would have
closed the bad tab never fires twice, and a rejected promise looks exactly like a feature
nobody uses. A general review of the same file grades the message validation and misses
that the headline feature is a no-op — so read it as state machines first, code second.

Applies to MV3 service workers and MV2 persistent pages. The lifecycle rules are stricter
under MV3 (the worker is recycled); the message rules are identical for both.

## When to Use

- A background script, service worker, or extension package is handed over for review —
  from a user, a PR, or another agent's output.
- A reviewer round (the council, a specialist profile) is about to grade extension code and
  needs the lifecycle and message-boundary checks the five rubrics do not carry.
- Not for server-side hardening of a web application — that is `web-app-security`.

## Procedure

1. **Inventory the package.** `manifest.json` (manifest version, `permissions`,
   `host_permissions`, `externally_connectable`, `content_scripts`), then every entry point
   the background references and whether it exists. Missing pieces are findings about the
   *package*: they change what can be verified, not just what is wrong, so label them apart
   from logic defects.
2. **List the entry points** — `onInstalled`, `onStartup`, top-level module code, every
   `onX` listener, every alarm — and note for each what state it reads and what it writes.
   Bugs live in the gap between those two sets.
3. **Trace five paths**, applying the checks below to each: enforcement on create/update,
   aging on a timer, reset on settings change, message dispatch, init and worker restart.
4. **Verify each candidate with one grep** before writing it down (`grep -n 'tabs.remove'`,
   `grep -c '\.catch'`, `grep -n 'sender'`). A claim about a missing call is one command
   from being a fact; without it an unread line range becomes a wrong finding.
5. **Order by blast radius**: silent no-op, then destructive action, then unbounded growth,
   then cost, then style. A dead feature outranks a naming opinion no matter what a scoring
   rubric rewards.

## Lifecycle checks

- **A cached init promise caches its rejection.** One transient storage error then disables
  every feature until the worker is recycled, invisibly. Clear the memo in a `catch` so the
  next event retries.
- **Re-creating an alarm of the same name restarts its countdown.** A worker that wakes
  often re-arms the only timer faster than its period and starves it. Create only when
  `alarms.get` reports nothing.
- **Persisted maps keyed by browser-assigned ids are wrong after a restart.** Tab and window
  ids are scoped to the browser run, so a stored map keyed by them mis-ages fresh tabs
  (mass closure) or shields stale ones. Store a run id beside the map and discard it when
  the run id differs.
- **Every `get → mutate → set` on `storage.local` is a lost-update window.** Concurrent
  listeners read the same snapshot and the last write wins; an entity whose record is lost
  that way becomes invisible to every later pass. Serialise the read-modify-write behind
  one promise queue.
- **`Date.now()` deltas include suspend.** A machine asleep for hours wakes with everything
  expired at once, and "protect the active one" saves exactly one. Say so; prefer elapsed
  active time or a suspend hook.
- **A timer-driven pass needs a re-entrancy guard.** Overlap duplicates every side effect
  (bookmarks, appended records); a promise flag is the whole fix.
- **Handle `tabs.onReplaced`**, or metadata for the surviving id is orphaned on prerender
  and instant-page swaps.
- **Diff a "backup and close" function against any commented-out sibling.** A live version
  that lost the close, sitting under a dead copy that still has it, is the signature of a
  deleted step — and it is the difference between a working feature and a no-op.

## Message-boundary checks

- **A declared-but-unread `sender` is the finding, not a style nit.** Any content script, and
  any origin in `externally_connectable`, then reaches the handlers. Compare `sender.id`
  with `runtime.id` before dispatch; keep one schema per message type.
- **Never accept a URL from a message.** Accept an index and resolve it against stored
  state: a message-supplied URL turns "reopen" into a privileged opener for `file:` and
  `data:` (whether a scheme is blocked differs by browser and version, so the check is
  membership in the stored list, not a scheme blocklist).
- **Never splice on a message-supplied index.** `splice("abc")` and `splice(NaN)` both hit
  element 0 and `-1` hits the end, each answering success to the caller. Require
  `Number.isInteger` plus bounds.
- **A `.then(sendResponse)` with no `.catch` leaves the caller pending forever** and holds
  the port open. Wrap the handler so every path responds, including the invalid one.
- **Validate the payload at the boundary, not at use.** A spread-merge persists whatever
  arrives (`maxTabs: 0`, `customDomainLimits: null`), survives restarts, and later throws
  inside enforcement — where the throw is swallowed and the feature silently stops.

## Enforcement checks

- **Select the victim from the set that was counted.** Counting a filtered list and removing
  an unfiltered id closes the pinned tab the setting promised to protect.
- **Normalise the host once and use that value for both the lookup and the counter.** Two
  normalisations (rule lookup strips `www.`, counter does not) silently double every cap.
- **Per-host is not per-site.** Bare, `www.` and subdomains are separate buckets unless the
  code says otherwise; state which semantic the review assumes.
- **Settings persistence must never be the trigger for a destructive operation.** A settings
  write that closes every tab gives the smallest user action the largest blast radius; a
  reset belongs to an explicit, confirmed command.

## Reporting

Lead with "does the declared feature work at all", then destructive paths, then growth,
cost, style. Name artifact findings (missing manifest, absent popup) as package gaps rather
than code defects. Give `file:line` for every claim, and say which claims you reproduced and
which are structural.

`references/webextension-api-semantics.md` holds the platform behaviour these rules rest on
(alarm replacement, id scope, `sendResponse` lifetime, unpermitted namespaces) — read it
when a finding turns on how the API behaves rather than on the file.
