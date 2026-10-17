# Tree and frontmatter helpers, as pure functions.
#
# Everything here answers a question about a file without running anything: a
# field's value, its length, the directory a SKILL.md sits in. That is what lets
# the tier above it be evaluation rather than execution.
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

  # The directories that belong to a skill. A SKILL.md under one of these is a
  # file inside a skill, not a skill: the rubrics live under `assets/rubrics/`.
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

  # YAML frontmatter as a flat string map, plus the body.
  #
  # Deliberately not a YAML parser: every SKILL.md in this repo opens with
  # `---`, carries flat `key: value` lines, and closes with `---`. A real parser
  # would be a dependency the repo does not otherwise have.
  parse =
    path:
    let
      lines = lib.splitString "\n" (builtins.readFile path);
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
    in
    {
      inherit startsWithFence;
      closed = closing != [ ] && isFence (builtins.head closing);
      fields = lib.listToAttrs (lib.filter (x: x != null) (map field inner));
      # +2: past the closing fence and its newline.
      body = lib.concatStringsSep "\n" (lib.drop (builtins.length inner + 2) lines);
    };
}
