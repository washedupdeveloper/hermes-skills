# The eval tier: what the tree SAYS, read without building anything. The run tier is
# `nix/checks.nix`, and there is no build tier (see its header).
#
# The rule encoded here: an assertion belongs in the cheapest tier that can make it.
# Nothing here shells out — a frontmatter field, a length, a name and a path are all values.
#
# Four of these properties used to live in `tests/unit/test_repo_skills.py`; they are here
# because they are pure functions of the tree, and here they fail with the skill's name and
# both values rather than a Python traceback. What stayed in Python needs a real regex
# engine or a subprocess; that file says which of its tests moved.
{ lib, src }:
let
  L = import ./lib.nix { inherit lib; };

  # The index truncates at 57 chars + "...", so the trigger must be self-contained there:
  # past that, the only part loaded before a skill opens is cut mid-word.
  descMax = 57;

  required = [
    "name"
    "description"
    "version"
    "author"
    "license"
    "platforms"
  ];

  # Extensions the repo treats as text. A `.pyc` would make `readFile` return whatever
  # bytes it happens to contain, so it is not scanned.
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

  # Every directory two levels down under `skills/` is a skill, so it must hold a SKILL.md:
  # a directory holding only references is a skill whose entry point was never written.
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
  # `uses: owner/action@vN` is a mutable reference: whoever can move the tag runs code in
  # this CI, with no change here. A branch in `github:owner/repo#attr` is the same hazard.
  # See docs/adr/0005-pin-workflow-actions-to-commits.md.
  workflowDir = src + "/.github/workflows";

  workflowFiles =
    if builtins.pathExists workflowDir then
      lib.filter
        (n: lib.hasSuffix ".yml" n || lib.hasSuffix ".yaml" n)
        (builtins.attrNames (builtins.readDir workflowDir))
    else
      [ ];

  # Every match of *pattern* in every workflow, as `file:line:value`. Comment lines are
  # skipped: a comment may name a ref without being one, and scanning prose turns a
  # documentation line into a false failure.
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

  # --- floating references -------------------------------------------------
  # `ubuntu-latest` is the runner analogue of a moved tag, and `@1` is an npm range that
  # resolves to whatever 1.x is current: both run code nobody reviewed, with no commit here.
  # A council review found each of them in this repository, which is why the rule is asserted
  # rather than stated in prose. The shipped template is scanned too: it is the workflow this
  # skill tells other repositories to adopt.
  templateCiJob = src + "/skills/software-development/openspec/templates/ci-job.yml";

  pinnedTextFiles =
    map (n: {
      name = n;
      path = workflowDir + "/${n}";
    }) workflowFiles
    ++ lib.optional (builtins.pathExists templateCiJob) {
      name = "openspec/templates/ci-job.yml";
      path = templateCiJob;
    };

  scanPinned =
    pattern:
    lib.concatMap (
      f:
      let
        lines = lib.splitString "\n" (builtins.readFile f.path);
        numbered = lib.imap1 (i: line: { inherit i line; }) lines;
        isComment = x: lib.hasPrefix "#" (lib.trim x.line);
        pick =
          x:
          let
            m = builtins.match pattern x.line;
          in
          if m == null then
            null
          else
            {
              name = "${f.name}:${toString x.i}";
              value = builtins.head m;
            };
      in
      lib.filter (x: x != null) (map pick (builtins.filter (x: !isComment x) numbered))
    ) pinnedTextFiles;

  floatingRunners = scanPinned ".*runs-on:[[:space:]]*([a-z0-9._-]+-latest).*";
  npmMajorPins = scanPinned ".*npm install -g[[:space:]]+[^[:space:]]+@([0-9]+)[[:space:]]*$";

  isFloatingRunner = runner: builtins.match ".+-latest" runner != null;
  isMajorOnlyPin = v: builtins.match "[0-9]+" v != null;
  # --- plugins ------------------------------------------------------------
  # A plugin directory is discovered by its `plugin.yaml`, and the registry key is the
  # `name:` field: a mismatch installs one plugin under another's key.
  pluginDir = src + "/plugins";

  pluginNames =
    if builtins.pathExists pluginDir then
      lib.filter
        (n: builtins.readFileType (pluginDir + "/${n}") == "directory")
        (builtins.attrNames (builtins.readDir pluginDir))
    else
      [ ];

  # `plugin.yaml` has no `---` fence, so the frontmatter parser does not apply: `name:` is
  # a top-level key.
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

  # A `pyproject.toml` claims installability, and the entry point is the only thing making
  # it so: `hermes_agent.plugins` with a key equal to the plugin name is what
  # `plugins.enabled` matches, so a wrong key builds, installs, and never loads — silently.
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
  # `.*^name` can never match — which made the first version report a correct pyproject
  # as broken.
  entrypointDeclares = name: text:
    lib.hasInfix "hermes_agent.plugins" text
    && lib.any
      (line: lib.hasPrefix "${name} =" (lib.trim line))
      (lib.splitString "\n" text);

  # --- build output -------------------------------------------------------
  # `nix build` leaves a `result` symlink at the repo root. Committing it is a path into
  # one machine's /nix/store — dangling for every other checkout, and swept in by
  # `git add -A`. This happened once here.
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
    # correct pair accepted, or the check above is vacuous.
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

    # Negative controls. A predicate that accepts everything passes the checks above on any
    # workflow at all, and the pass looks identical to a real one.
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

    # ADR 0005's rule, extended to the two references it does not scan: the runner label and
    # the npm install. Both were unpinned until a council review of this repository named them.
    test_no_workflow_runs_on_a_floating_runner = {
      expr = map (x: "${x.name}: ${x.value}") floatingRunners;
      expected = [ ];
    };

    test_every_spec_cli_install_pins_an_exact_version = {
      expr = map (x: "${x.name}: @${x.value}") npmMajorPins;
      expected = [ ];
    };

    # Negative controls. A predicate that accepts everything passes both checks above on any
    # workflow at all, and the pass is indistinguishable from a real one.
    test_the_runner_gate_rejects_a_latest_label = {
      expr = [
        (isFloatingRunner "ubuntu-latest")
        (isFloatingRunner "ubuntu-24.04")
      ];
      expected = [
        true
        false
      ];
    };

    test_the_npm_gate_rejects_a_major_range = {
      expr = [
        (isMajorOnlyPin "1")
        (isMajorOnlyPin "1.15.0")
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
    # The skill registers as /<name>, and the installer copies by directory name, so a
    # mismatch installs one skill under another's slug.
    test_the_name_matches_its_directory = {
      expr = map (x: "${rel x.path}: ${x.fields.name or "(none)"}") (
        builtins.filter (x: !(L.nameMatches x.dir (x.fields.name or ""))) parsed
      );
      expected = [ ];
    };

    # Two catalog skills with one name: the second silently shadows the first in the index.
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

    # The boundary itself, not just "over it". The check above rejects a description LONGER
    # than `descMax`; a rule written `>=` would reject the last character that fits, and
    # nothing in the tree would notice, because no skill sits on the boundary. So the
    # predicate is exercised at 57 and at 58 rather than inferred.
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

    # A frontmatter line the field regex cannot parse would vanish silently, so every
    # column-0 key must be in the parsed map: this is what makes the parser's completeness
    # observable rather than assumed.
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
    # A CRLF shebang fails on Linux, and a CRLF/LF pair reports drift that is not there.
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
    # One per predicate the checks above depend on. The invalid case must be REJECTED
    # through the same code the check calls: a predicate that accepts everything passes
    # every positive test above and fails exactly here. Each pair also carries the valid
    # case, so a predicate stuck on `false` fails too.
    # The regex form of this check overflowed the evaluator on THIS file in CI, and the
    # message named "possible infinite recursion" rather than the file. Pinned so a
    # future hasCrlf cannot quietly become stack-bound again.
    test_the_crlf_check_answers_on_the_largest_text_file = {
      expr = L.hasCrlf (builtins.readFile (
        src + "/skills/autonomous-ai-agents/council/scripts/council_loop.py"
      ));
      expected = false;
    };

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

    # The completeness check is only meaningful while the parser has a real blind spot: a
    # key the field regex cannot read must still be counted in `keys`, or the check would
    # agree with the parser and prove nothing.
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
