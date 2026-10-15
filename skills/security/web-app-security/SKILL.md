---
name: web-app-security
description: Use when hardening a web app. OWASP checklist.
version: 1.0.0
author: user, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
category: security
metadata:
  hermes:
    tags: [security, web, owasp, review, hardening, ssrf, llm]
    related_skills: [reviewer-security, oss-forensics]
    source: https://github.com/addyosmani/agent-skills (security-and-hardening, MIT)
---

# web-app-security

On-demand. Load it when the work touches a web project — HTTP handlers, auth,
sessions, uploads, database access, external APIs, PII, or LLM features. For a Nix
or NixOS diff, `reviewer-security` covers it and this skill is not needed.

**Trust follows who WROTE a value, not which channel delivered it.** A form field,
another process's command line, a filename on a shared volume, a job payload, and
**model output** are all untrusted. Every one is attack surface.

## Never — each of these is a finding, not a nit

- Committing a secret.
- Logging sensitive data (passwords, tokens, full card numbers).
- Trusting client-side validation as a security boundary.
- `eval()` or `innerHTML` with user-provided data.
- Auth tokens in `localStorage` / `sessionStorage`.
- Stack traces or internal error details in a response.
- A `*` CORS origin together with credentials.

## Checklist

**Injection, XSS, access control**
- [ ] No query built from an input string (SQL, NoSQL, shell).
- [ ] Output encoded by the framework's auto-escaping; raw HTML sanitized with an
      allowlist.
- [ ] **Authorization** checked per request, not just authentication — the actor
      must own or be permitted on *that* resource (A01, IDOR).

**Auth and sessions**
- [ ] Session secret from the environment, never from code.
- [ ] Cookies `httpOnly`, `secure`, and `sameSite` **not** `none` (that is the CSRF
      defense), with a bounded `maxAge`.
- [ ] Passwords hashed with bcrypt (≥12 rounds), scrypt, or argon2.

**Headers, CORS, responses**
- [ ] CSP starts at `default-src 'self'` and is tightened, not loosened.
- [ ] CORS is an explicit origin list from config.
- [ ] Sensitive fields (`passwordHash`, reset tokens) stripped before the response;
      error bodies generic, internals to logs only.

**Validation and uploads**
- [ ] Schema allowlist at the boundary (shape, length, enum, format); reject 422;
      downstream uses only the parsed value.
- [ ] Uploads: MIME allowlist, size cap, magic-byte check — the extension proves
      nothing.

**Server-side fetches (SSRF)**
- [ ] Any user-influenced URL (webhook, import-from-URL, image proxy, link preview)
      allowlisted by scheme and host; **all** resolved addresses rejected if
      loopback, link-local (`169.254.169.254`), private, or unique-local, for IPv4
      **and** IPv6; redirects forbidden. A DNS-rebinding TOCTOU gap remains — pin
      the resolved IP on high-risk surfaces.

**Destructive operations on derived paths**
- [ ] A delete/move/overwrite whose target came from a payload, a config value, or
      another process requires **all three**: the resolved target (symlinks
      resolved) sits under an allowlisted root; it is at least one level **below**
      that root; and ownership evidence was read before the operation. A shape
      check proves well-formedness, **not** authorization. On refusal, log the
      rejected target and stop — never fall back to a broader default path.

**Rate limiting**
- [ ] Auth endpoints limited strictly (~10 per 15 min). Once more than one instance
      serves traffic an in-memory counter silently becomes `max × instances`, or
      never fires on serverless: it needs a shared store.

**Secrets**
- [ ] `.env.example` committed with placeholders; real `.env*` gitignored.
- [ ] **A secret that reached a remote is compromised: rotate first, then purge
      history.** Rewriting history alone does not un-leak it.

**Dependencies and supply chain**
- [ ] One installation boundary, one lockfile; stop on competing lockfiles.
- [ ] Dependency scripts blocked before first execution, approved minimally in a
      committed policy, verified by a frozen/immutable install.
- [ ] Native audit run against the committed lockfile; critical/high triaged by
      **reachability** (runtime, build, test, deploy); forced remediation never
      applied automatically.
- [ ] **Audits match known advisories only** — they do not catch a newly malicious
      or typosquatted package (`cross-env` vs `crossenv`). Review new dependencies,
      lockfile diffs and script-policy changes together.

**Personal data**
- [ ] Fields classified as they are added (non-personal / PII / sensitive).
- [ ] Collection tied to a stated purpose — "might be useful later" is breach
      scope, not a purpose.
- [ ] A retention TTL and a working deletion path **including backups, caches,
      search indexes and analytics copies**.

**AI / LLM features** — map to the [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/):
- [ ] Model output treated as untrusted input: never into `eval`, SQL, a shell,
      `innerHTML`, or a file path (LLM05).
- [ ] The system prompt is **not** a security boundary; permissions enforced in
      code (LLM01).
- [ ] No secrets, other tenants' data, or the full system prompt in the context
      window (LLM02, LLM07); tool permissions scoped, arguments validated,
      destructive actions confirmed (LLM06); tokens, rate and recursion capped
      (LLM10); RAG embeddings partitioned per tenant (LLM08).

## Commands

```bash
rg -n 'innerHTML|dangerouslySetInnerHTML|v-html|eval\(' -g '!*test*'        # XSS sink
rg -n 'Access-Control-Allow-Origin' | rg '\*'                              # wildcard CORS
rg -n '(localStorage|sessionStorage)\..*(token|jwt)'                       # token in JS storage
rg -n '(requests|fetch|axios|http)\.\w+\(.*(req\.|request\.|params\[)'      # SSRF candidate
rg -n 'query\(|execute\(|raw\(' -g '*.{py,js,ts,go,rb}' | rg '\+|\$\{|%s'   # string-built SQL
npm audit --audit-level=high 2>/dev/null || pnpm audit || pip-audit || cargo audit
gitleaks detect --no-banner --redact                                       # history
```

## Escalation gates (for a review, not averaged)

- Committed secret, or `*` CORS with credentials → the security score is **≤ 30**.
- String-built SQL on user input, or a user-supplied URL fetched without an
  allowlist → security **× 0.5**.

## Rationalizations, and the reality

| Rationalization | Reality |
|---|---|
| "Internal tool, security doesn't matter" | Internal tools get compromised; attackers target the weakest link. |
| "We'll add security later" | Retrofitting is an order of magnitude harder. |
| "No one would exploit this" | Scanners find it. Obscurity is not security. |
| "The framework handles it" | Frameworks provide tools, not guarantees. |
| "It's just a prototype" | Prototypes become production. |
| "It's just LLM output, it's only text" | That text can be a SQL statement, a script tag, or a shell command. |
| "The audit passed, so the dependency is safe" | Audits match known advisories only. |
| "Collect it now, might need it later" | Data you don't hold can't be breached. That is breach scope, not a purpose. |

Adapted and condensed from `addyosmani/agent-skills` (`security-and-hardening`,
MIT). The review-side gates are stated for a reviewer; when building rather than
reviewing, treat them as the bar to clear before shipping.
