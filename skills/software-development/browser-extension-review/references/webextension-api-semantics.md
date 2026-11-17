# WebExtension API semantics these checks depend on

Platform behaviour, not file behaviour. Each entry states the mechanism and what it does to
a review.

## alarms

`alarms.create(name, info)` **replaces** an existing alarm with the same name and restarts
its schedule from now. Code that calls it on every service-worker wake therefore keeps
pushing the next fire out; with a frequently woken MV3 worker the alarm can starve.
Guard with `alarms.get(name)`.

Periodic alarms persist across worker restarts, not necessarily across browser restarts, so
re-creating them in `onStartup`/`onInstalled` is still correct.

## Tab and window ids

Ids are unique **within a browser run** and the numbering restarts afterwards, so any map
persisted to `storage.local` keyed by them is a collision waiting to happen: a restored tab
can inherit the previous run's `createdAt`. Persist a run id with the map, or re-key on
restore.

## MV3 service-worker lifetime

The worker terminates after roughly 30 s idle and its top-level code runs again on every
wake. Anything at module scope — storage writes, `alarms.create`, a full `tabs.query`
reconcile — therefore runs per wake, and a cached promise does not survive it.

`onStartup` and `onInstalled` do not fire on every wake; a top-level `init()` call is the
only cover for wake-ups that skip them.

## Messaging

`return true` from an `onMessage` listener keeps the channel open until `sendResponse` is
called. If the handler rejects before responding, the sender's promise stays pending until
the page goes away, and the rejection surfaces only as an unhandled promise rejection.

`sender` carries `id`, `url`, `origin`, `tab` and `frameId`; `sender.id` is the extension's
own id even for a content script, so an origin check needs `sender.url` as well. A listener
that never reads `sender` is reachable by every content script it injects and by every
origin in `externally_connectable`.

## Unpermitted namespaces

A namespace for a permission the manifest did not request is **undefined**, not a throwing
stub. So `api.bookmarks.search(...)` inside a `try/catch` fails silently and the feature
disappears with no error — check the manifest for the permission before reading the code as
if it can run.

## storage.local

Writes are a full serialisation of the value, so cost scales with the size of the object
being written: a map covering every open tab is rewritten per event. There is no per-minute
write cap (unlike `storage.sync`), but concurrent async contexts interleave —
read-modify-write across an `await` is not atomic.

## windows

`windows.getLastFocused()` can return a non-normal window (devtools, popup) unless
`windowTypes: ['normal']` is passed; creating a tab into a devtools window fails. A reset
routine that keeps one tab in "the last focused window" and closes everything else can
empty the other windows it never looked at.

## bookmarks

`bookmarks.search({title})` matches loosely on the title, so reusing a folder by name can
adopt an unrelated folder; folders are distinguishable from bookmarks by the absence of
`url`. Creating bookmarks for `chrome://` / `about:` pages and other internal URLs throws
and is best skipped by scheme.

## Promises vs callbacks

Firefox's `browser.*` returns promises; Firefox's `chrome.*` is callback-based. Chrome's
`chrome.*` returns promises only when no callback is passed (MV3). Feature-detect the
namespace (`typeof browser !== 'undefined' ? browser : chrome`) rather than the callback
style, and never mix `await` with a callback argument.
