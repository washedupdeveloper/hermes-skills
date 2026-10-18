# The eval tier: what the tree SAYS, read without building anything.
#
# Three tiers, and the tier is chosen by what the assertion needs:
#
#   eval  -- a property of the source files. Here. Milliseconds, and a failure
#            names the skill, the field and both values.
#   build -- a property of the SHIPPED artifact, which is not the source tree.
#            `nix/checks.nix`, seconds.
#   run   -- behaviour: a script doing something to a stubbed `hermes`, or the
#            prose claims checked against the tree. `nix/checks.nix`, and the
#            only tier that needs an interpreter.
#
# The rule this encodes: an assertion belongs in the cheapest tier that can make
# it. Nothing here shells out, and nothing here is a script -- a frontmatter
# field, a length, a name and a path are all values.
#
# These four properties used to live in tests/unit/test_repo_skills.py. They are
# asserted here instead because they are pure functions of the tree, and here
# they fail with the skill's name and both values rather than a Python traceback.
# What stayed in Python is what needs a real regex engine or a subprocess: the
# prose claims and the reference heuristics. `tests/unit/test_repo_skills.py`
# says which of its tests moved.
{ lib, src }:
let
  L = import ./lib.nix { inherit lib; };

  # The index truncates at 57 chars + "...", so the trigger must be
  # self-contained there. Past that, the only part loaded before a skill opens is
  # cut mid-word.
  descMax = 57;

  required = [
    "name"
    "description"
    "version"
    "author"
    "license"
    "platforms"
  ];

  # Extensions the repo treats as text. A `.pyc` would make `readFile` return
  # whatever bytes it happens to contain, so it is not scanned.
  textExts = [
    ".md"
    ".sh"
    ".py"
    ".yaml"
    ".yml"
    ".json"
  ];

  rel = p: lib.removePrefix (toString src + "/") (toString p);

  # The window predicate, named so the boundary can be exercised directly.
  fitsWindow = s: builtins.stringLength s <= descMax;

  repeatChar = n: lib.concatMapStrings (_: "x") (lib.range 1 n);

  files = L.skillFiles src;

  parsed = map (
    p:
    L.parse p
    // {
      path = p;
      dir = baseNameOf (dirOf p);
    }
  ) files;

  catalog = lib.filter (x: !L.isSupport x.path) parsed;

  # Every directory two levels down under `skills/` is a skill, so it must hold a
  # SKILL.md. A directory holding only references is a skill whose entry point was
  # never written.
  skillDirs = lib.concatMap (
    category:
    let
      dir = src + "/skills/${category}";
      entries = builtins.readDir dir;
    in
    map (name: "${category}/${name}") (
      lib.filter (name: entries.${name} == "directory") (builtins.attrNames entries)
    )
  ) (builtins.attrNames (builtins.readDir (src + "/skills")));
in
{
  skills = {
    # --- frontmatter --------------------------------------------------------
    test_every_skill_opens_with_frontmatter = {
      expr = map (x: rel x.path) (builtins.filter (x: !x.startsWithFence) parsed);
      expected = [ ];
    };

    test_every_skill_closes_its_frontmatter = {
      expr = map (x: rel x.path) (builtins.filter (x: !x.closed) parsed);
      expected = [ ];
    };

    test_every_skill_declares_the_required_fields = {
      expr = lib.concatMap (
        x: map (f: "${rel x.path}: ${f}") (builtins.filter (f: !(x.fields ? ${f})) required)
      ) parsed;
      expected = [ ];
    };

    # --- identity -----------------------------------------------------------
    # The skill registers as /<name>, and the installer copies by directory name,
    # so a mismatch installs one skill under another's slug.
    test_the_name_matches_its_directory = {
      expr = map (x: "${rel x.path}: ${x.fields.name or "(none)"}") (
        builtins.filter (x: !(L.nameMatches x.dir (x.fields.name or ""))) parsed
      );
      expected = [ ];
    };

    # Two catalog skills with one name: the second silently shadows the first in
    # the index, and nothing says so.
    test_every_catalog_name_is_unique = {
      expr = lib.filter (n: n != "") (L.duplicates (map (x: x.fields.name or "") catalog));
      expected = [ ];
    };

    # --- the index window ---------------------------------------------------
    # The description is the ONLY part in the index, so every session pays it.
    test_every_description_fits_the_index_window = {
      expr = map (x: "${x.dir}: ${toString (builtins.stringLength (x.fields.description or ""))} chars") (
        builtins.filter (x: builtins.stringLength (x.fields.description or "") > descMax) catalog
      );
      expected = [ ];
    };

    # The boundary itself, not just "over it". The window check above rejects a
    # description LONGER than `descMax`; a rule written as `>=` would reject the
    # last character that fits, and nothing in the tree would notice because no
    # skill sits exactly on the boundary. So the predicate is exercised at 57 and
    # at 58 rather than inferred.
    test_the_window_boundary_is_inclusive = {
      expr = [
        (fitsWindow (repeatChar descMax))
        (fitsWindow (repeatChar (descMax + 1)))
      ];
      expected = [
        true
        false
      ];
    };

    test_no_description_is_empty = {
      expr = map (x: rel x.path) (
        builtins.filter (x: (x.fields.description or "") == "") catalog
      );
      expected = [ ];
    };

    # A frontmatter line the field regex cannot parse would vanish silently, so
    # every column-0 key must be present in the parsed map. This is the test that
    # makes the parser's completeness observable rather than assumed.
    test_every_frontmatter_key_is_parsed = {
      expr = lib.concatMap (
        x: map (k: "${rel x.path}: ${k}") (builtins.filter (k: !(x.fields ? ${k})) x.keys)
      ) parsed;
      expected = [ ];
    };

    # --- layout -------------------------------------------------------------
    test_every_skill_directory_holds_a_skill_md = {
      expr = builtins.filter (
        d: !(builtins.pathExists (src + "/skills/${d}/SKILL.md"))
      ) skillDirs;
      expected = [ ];
    };

    # --- encoding -----------------------------------------------------------
    # A CRLF shebang fails on Linux, and a CRLF/LF pair makes a sync report
    # drift that is not there.
    test_no_text_file_carries_crlf = {
      expr = map rel (
        builtins.filter (
          p:
          lib.any (e: lib.hasSuffix e (toString p)) textExts
          && L.hasCrlf (builtins.readFile p)
        ) (lib.filesystem.listFilesRecursive src)
      );
      expected = [ ];
    };

    # --- negative controls --------------------------------------------------
    # One per predicate the checks above depend on. The invalid case must be
    # REJECTED through the same code the check calls: a predicate that accepts
    # everything passes every positive test above and fails exactly here. Each
    # pair also carries the valid case, so a predicate stuck on `false` fails too.
    test_the_frontmatter_gate_rejects_a_missing_fence = {
      expr = [ (L.parseText "name: x\n---\n").startsWithFence (L.parseText "---\nname: x\n---\n").startsWithFence ];
      expected = [
        false
        true
      ];
    };

    test_the_frontmatter_gate_rejects_an_unclosed_fence = {
      expr = [ (L.parseText "---\nname: x\n").closed (L.parseText "---\nname: x\n---\n").closed ];
      expected = [
        false
        true
      ];
    };

    # The completeness check is only meaningful while the parser has a real blind
    # spot: a key the field regex cannot read must still be counted in `keys`, or
    # the check would agree with the parser and prove nothing.
    test_the_completeness_gate_rejects_a_key_the_parser_cannot_read = {
      expr =
        let
          p = L.parseText "---\nx-tag: 1\n---\nbody\n";
        in
        [
          (builtins.length p.keys)
          (builtins.hasAttr "x-tag" p.fields)
          (builtins.hasAttr "x_tag" (L.parseText "---\nx_tag: 1\n---\nbody\n").fields)
        ];
      expected = [
        1
        false
        true
      ];
    };

    test_the_identity_gate_rejects_a_name_mismatch = {
      expr = [
        (L.nameMatches "alpha" "alpha")
        (L.nameMatches "alpha" "beta")
      ];
      expected = [
        true
        false
      ];
    };

    test_the_uniqueness_gate_rejects_a_duplicate = {
      expr = [
        (L.duplicates [ "a" "a" "b" ])
        (L.duplicates [ "a" "b" ])
      ];
      expected = [
        [ "a" ]
        [ ]
      ];
    };

    test_the_encoding_gate_rejects_a_crlf = {
      expr = [
        (L.hasCrlf "a\nb")
        (L.hasCrlf "a\r\nb")
      ];
      expected = [
        false
        true
      ];
    };
  };
}
