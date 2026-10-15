# Reference the repo through `skills.external_dirs`, never a copy or a symlink

Hermes loads this repo's skills by **reference** — `skills.external_dirs` points at
`skills/` and nothing is derived from it. The obvious alternatives were a **symlink**
(`$HERMES_HOME/skills/<name>` → here) and a **copy script**, and both are wrong for
the same reason.

A symlink does not *prevent* a write, it **redirects** it. Hermes patches an existing
skill in place, wherever it is found, and that includes skills under `external_dirs`
— so a background write aimed at "the live library" would land *through* the link,
into this repo. That is the original problem, now disguised as a normal library
write. Nix uses a symlink for the live profile path, but its protection is that the
**store is read-only**, not that the link is a link; copying the symlink without the
read-only target copies the appearance and none of the property.

A copy script is the anti-pattern this repo already deleted once: imperative, so it
drifts; and it re-creates shadowing, because a real directory in the local skills root
**outranks** `external_dirs` silently.

The consequence, which is the part worth remembering: **the mount is not a
permission boundary.** `external_dirs` makes this tree *readable*, not *protected*.
The gate is git — the repo is tracked, so any unattended write is visible in
`git status` and reverts with `git checkout`.
