# Tree and frontmatter helpers, pure: each answers a question about a file without
# running anything, which is what lets the tier above be evaluation rather than execution.
{ lib }:
let
  # `lib.takeWhile` does not exist, and this is the whole of it.
  takeUntil =
    pred: xs:
    let
      go =
        acc: rest:
        if rest == [ ] then
          acc
        else if pred (builtins.head rest) then
          acc
        else
          go (acc ++ [ (builtins.head rest) ]) (builtins.tail rest);
    in
    go [ ] xs;

  unquote =
    s:
    let
      t = lib.trim s;
    in
    if lib.hasPrefix "\"" t && lib.hasSuffix "\"" t then
      lib.removeSuffix "\"" (lib.removePrefix "\"" t)
    else
      t;

  # A SKILL.md under one of these is a file inside a skill, not a skill: the rubrics
  # live under `assets/rubrics/`.
  supportDirs = [
    "references"
    "templates"
    "assets"
    "scripts"
  ];
in
rec {
  # Every SKILL.md in the tree, catalog entries and support files alike.
  skillFiles =
    root: lib.filter (p: baseNameOf p == "SKILL.md") (lib.filesystem.listFilesRecursive root);

  isSupport = p: lib.any (d: lib.hasInfix "/${d}/" (toString p)) supportDirs;

  # YAML frontmatter as a flat string map, plus the body. Deliberately not a YAML
  # parser: every SKILL.md here is `---`, flat `key: value`, `---`, and a parser would
  # be a dependency the repo does not otherwise have.
  #
  # `parse` only reads the file, so a negative control drives the SAME `parseText` code
  # with a synthetic document: a predicate tested through a copy of itself proves nothing.
  parseText =
    text:
    let
      lines = lib.splitString "\n" text;
      isFence = l: lib.trim l == "---";
      startsWithFence = lines != [ ] && isFence (builtins.head lines);
      afterOpen = if lines == [ ] then [ ] else builtins.tail lines;
      inner = takeUntil isFence afterOpen;
      # The line the closing fence would be on.
      closing = lib.drop (builtins.length inner) afterOpen;
      field =
        line:
        let
          m = builtins.match "[[:space:]]*([A-Za-z_][A-Za-z0-9_]*):[[:space:]]*(.*)" line;
        in
        if m == null then
          null
        else
          {
            name = builtins.elemAt m 0;
            value = unquote (builtins.elemAt m 1);
          };
      # Column-0 keys only: a nested key under `metadata:` is indented, and counting it
      # would make the completeness test below vacuous. The charset is deliberately WIDER
      # than the field regex's, so a key the field parser cannot read (`x-tag:`) is still
      # counted — otherwise the test would agree with the parser's own blind spot.
      topLevel =
        line:
        let
          m = builtins.match "([^:[:space:]]+):.*" line;
        in
        if m == null then null else builtins.elemAt m 0;
    in
    {
      inherit startsWithFence;
      closed = closing != [ ] && isFence (builtins.head closing);
      fields = lib.listToAttrs (lib.filter (x: x != null) (map field inner));
      # Every column-0 key. Compared against `fields` by the completeness test, so a
      # line the field regex cannot parse fails loudly instead of vanishing.
      keys = lib.filter (x: x != null) (map topLevel inner);
      # +2: past the closing fence and its newline.
      body = lib.concatStringsSep "\n" (lib.drop (builtins.length inner + 2) lines);
    };

  parse = path: parseText (builtins.readFile path);

  # A skill registers as /<name> and installs by directory name, so a mismatch installs
  # one skill under another's slug.
  nameMatches = dir: name: name == dir;

  # Values occurring more than once, in first-seen order: a second catalog entry with one
  # name silently shadows the first in the index.
  duplicates = xs: lib.unique (lib.filter (x: lib.count (y: y == x) xs > 1) xs);

  # A CRLF shebang fails on Linux, and a CRLF/LF pair reports drift that is not there.
  hasCrlf = text: lib.hasInfix "\r" text;
}
