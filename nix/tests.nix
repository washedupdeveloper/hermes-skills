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

  # --- workflow pins ------------------------------------------------------
  # `uses: owner/action@vN` is a mutable reference: whoever can move the tag runs
  # code in this repository's CI, with no change to this repo. A branch name in
  # `nix profile install github:owner/repo#attr` is the same hazard. A commit SHA is
  # the only form that cannot be moved, so it is a property of the source file and
  # is asserted here rather than left to review.
  workflowDir = src + "/.github/workflows";

  workflowFiles =
    if builtins.pathExists workflowDir then
      lib.filter
        (n: lib.hasSuffix ".yml" n || lib.hasSuffix ".yaml" n)
        (builtins.attrNames (builtins.readDir workflowDir))
    else
      [ ];

  # Every match of *pattern* in every workflow, as `file:line:value`. Comment lines
  # are skipped: a comment may name a ref without being one ("`uses:` must be a SHA"),
  # and scanning prose turns a documentation line into a false failure.
  scan =
    pattern:
    let
      one =
        file:
        let
          lines = lib.splitString "\n" (builtins.readFile (workflowDir + "/${file}"));
          numbered = lib.imap1 (i: line: { inherit i line; }) lines;
          isComment = x: lib.hasPrefix "#" (lib.trim x.line);
          pick =
            x:
            let
              m = builtins.match pattern x.line;
            in
            if m == null then null else { name = "${file}:${toString x.i}"; value = builtins.head m; };
        in
        lib.filter (x: x != null) (map pick (builtins.filter (x: !isComment x) numbered));
    in
    lib.concatMap one workflowFiles;

  usesRefs = scan ".*uses:[[:space:]]*([^[:space:]]+).*";
  githubRefs = scan ".*(github:[^[:space:]]+).*";

  hex40 = lib.concatStrings (lib.genList (_: "[0-9a-f]") 40);

  # A local action is a directory in this repository: it moves with the commit.
  isLocal = ref: lib.hasPrefix "./" ref;
  isPinned = ref: builtins.match (".*@" + hex40) ref != null;
  isRevPinned = ref: builtins.match ("github:[^/]+/[^/]+/" + hex40 + "(#.*)?") ref != null;
  # --- plugins ------------------------------------------------------------
  # A plugin directory is discovered by its `plugin.yaml`, and the registry key is the
  # `name:` field — a mismatch installs one plugin under another's key, and the manifest
  # is the only thing telling a reader what the code is for.
  pluginDir = src + "/plugins";

  pluginNames =
    if builtins.pathExists pluginDir then
      lib.filter
        (n: builtins.readFileType (pluginDir + "/${n}") == "directory")
        (builtins.attrNames (builtins.readDir pluginDir))
    else
      [ ];

  # `plugin.yaml` has no `---` fence, so the frontmatter parser does not apply: the
  # manifest is plain YAML and `name:` is a top-level key.
  pluginName =
    name:
    let
      path = pluginDir + "/${name}/plugin.yaml";
      m =
        if builtins.pathExists path then
          builtins.match ".*name:[[:space:]]*([^[:space:]]+).*" (builtins.readFile path)
        else
          null;
    in
    if m == null then null else builtins.head m;

  pluginIssues = lib.concatMap (
    name:
    let
      declared = pluginName name;
      hasInit = builtins.pathExists (pluginDir + "/${name}/__init__.py");
    in
    (if declared == null then [ "${name}: no plugin.yaml, or it declares no name" ] else [ ])
    ++ (if declared != null && declared != name then [ "${name}: plugin.yaml name is ${declared}" ] else [ ])
    ++ (if hasInit then [ ] else [ "${name}: no __init__.py" ])
  ) pluginNames;

  pluginNameMatches = dir: name: name == dir;

  # A plugin that ships a `pyproject.toml` claims to be installable, and the only thing
  # making it installable is the entry point Hermes scans. `hermes_agent.plugins` with a
  # key equal to the plugin name is what `plugins.enabled` matches, so a wrong key is a
  # plugin that builds, installs, and never loads — silently.
  pluginEntrypointIssues = lib.concatMap (
    name:
    let
      pyproject = pluginDir + "/${name}/pyproject.toml";
    in
    if !builtins.pathExists pyproject then
      [ ]
    else
      let
        text = builtins.readFile pyproject;
        declaresGroup = lib.hasInfix "hermes_agent.plugins" text;
        declaresKey = entrypointDeclares name text;
      in
      (if declaresGroup then [ ] else [ "${name}: pyproject.toml has no hermes_agent.plugins entry point" ])
      ++ (if declaresKey then [ ] else [ "${name}: pyproject.toml declares no entry point named ${name}" ])
  ) pluginNames;

  # Line-based, because `builtins.match` anchors `^` to the start of the whole string:
  # `.*^name` can never match, which is how the first version of this predicate reported
  # a correct pyproject as broken.
  entrypointDeclares = name: text:
    lib.hasInfix "hermes_agent.plugins" text
    && lib.any
      (line: lib.hasPrefix "${name} =" (lib.trim line))
      (lib.splitString "\n" text);

  # --- build output -------------------------------------------------------
  # `nix build` leaves a `result` symlink at the repo root. Committing it is worse than
  # noise: it is a path into one machine's /nix/store, so every other checkout gets a
  # dangling link, and `git add -A` sweeps it in without a word. This happened once here.
  isBuildOutput = name: lib.hasPrefix "result" name;

  committedBuildOutputs = lib.filter isBuildOutput (builtins.attrNames (builtins.readDir src));
in
{
  plugins = {
    test_every_plugin_directory_declares_itself = {
      expr = pluginIssues;
      expected = [ ];
    };

    # Negative control: a manifest naming a different plugin must be rejected, and the
    # predicate must accept the correct pair — otherwise the check above is vacuous.
    test_the_plugin_name_gate_rejects_a_mismatch = {
      expr = [
        (pluginNameMatches "harness-audit" "harness-audit")
        (pluginNameMatches "harness-audit" "audit")
      ];
      expected = [
        true
        false
      ];
    };

    test_every_installable_plugin_declares_its_entry_point = {
      expr = pluginEntrypointIssues;
      expected = [ ];
    };

    # Negative control for the entry-point gate: the right key under the wrong group, and
    # the right group with the wrong key, must both be rejected.
    test_the_entrypoint_gate_rejects_a_wrong_group_or_key = {
      expr = [
        (entrypointDeclares "harness-audit" "[project.entry-points.\"hermes_agent.plugins\"]\nharness-audit = \"harness_audit:register\"\n")
        (entrypointDeclares "harness-audit" "[project.entry-points.\"console_scripts\"]\nharness-audit = \"harness_audit:main\"\n")
        (entrypointDeclares "harness-audit" "[project.entry-points.\"hermes_agent.plugins\"]\naudit = \"harness_audit:register\"\n")
      ];
      expected = [
        true
        false
        false
      ];
    };
  };

  buildOutput = {
    test_no_build_output_is_committed = {
      expr = committedBuildOutputs;
      expected = [ ];
    };

    # Negative control: the predicate must accept `result` and `result-*` and reject an
    # ordinary file, or the check above is satisfied by a tree it never inspects.
    test_the_build_output_gate_rejects_a_result_link = {
      expr = [
        (isBuildOutput "result")
        (isBuildOutput "result-harness-audit")
        (isBuildOutput "README.md")
      ];
      expected = [
        true
        true
        false
      ];
    };
  };

  workflows = {
    test_every_workflow_action_is_pinned_to_a_commit = {
      expr = map (x: "${x.name}: ${x.value}") (
        builtins.filter (x: !(isLocal x.value) && !(isPinned x.value)) usesRefs
      );
      expected = [ ];
    };

    test_every_github_install_is_pinned_to_a_rev = {
      expr = map (x: "${x.name}: ${x.value}") (
        builtins.filter (x: !(isRevPinned x.value)) githubRefs
      );
      expected = [ ];
    };

    # Negative controls. A predicate that accepts everything passes the checks
    # above on any workflow at all, and the pass looks identical to a real one.
    test_the_action_pin_gate_rejects_a_mutable_tag = {
      expr = [
        (isPinned "actions/checkout@v7")
        (isPinned "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
      ];
      expected = [
        false
        true
      ];
    };

    test_the_rev_pin_gate_rejects_a_branch = {
      expr = [
        (isRevPinned "github:NousResearch/hermes-agent#minimal")
        (isRevPinned "github:NousResearch/hermes-agent/main#minimal")
        (isRevPinned "github:NousResearch/hermes-agent/548091836760a67e331b8f5643be8e5c08fae1e6#minimal")
      ];
      expected = [
        false
        false
        true
      ];
    };

    test_a_local_action_needs_no_pin = {
      expr = [
        (isLocal "./.github/actions/build")
        (isLocal "actions/checkout@v7")
      ];
      expected = [
        true
        false
      ];
    };
  };

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
