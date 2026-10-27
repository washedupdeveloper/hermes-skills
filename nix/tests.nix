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

  # The one machine-readable home for a version the repository adopts in more than one place.
  # Every adopted copy is checked against it, so bumping is this file plus the four sites.
  pins = import ./pins.nix;

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
    ".nix"
    ".toml"
    ".txt"
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
      lib.filter (n: lib.hasSuffix ".yml" n || lib.hasSuffix ".yaml" n) (
        builtins.attrNames (builtins.readDir workflowDir)
      )
    else
      [ ];

  # --- one scanner, one comment rule --------------------------------------
  # `scanLines` is the only place a file is split into numbered, non-comment lines, so the
  # comment-skip rule and the `file:line` format have one owner. There used to be two
  # scanners; the second drifted, because it skipped comments but over a narrower file set.
  isComment = line: lib.hasPrefix "#" (lib.trim line);

  numberedLines =
    f:
    lib.imap1 (i: line: {
      name = "${f.name}:${toString i}";
      inherit line;
    }) (lib.splitString "\n" (builtins.readFile f.path));

  scanLines =
    f: pattern:
    let
      pick =
        x:
        let
          m = builtins.match pattern x.line;
        in
        if m == null then
          null
        else
          {
            inherit (x) name line;
            value = builtins.head m;
          };
    in
    lib.filter (x: x != null) (map pick (lib.filter (x: !(isComment x.line)) (numberedLines f)));

  # A trailing comment is not part of a command, and shell punctuation can sit beside one:
  # `bootstrap.sh` ends a message with `>&2`, which would otherwise become the last token.
  shellNoise = [
    "\""
    "'"
    ">"
    "&"
    ";"
    "("
    ")"
  ];

  # A `#` inside a token is not a comment: `nixpkgs#nodejs_22` is half of every command in
  # AGENTS.md, and splitting on it truncated the line before the package was reached.
  stripComment = line: lib.trim (builtins.head (lib.splitString " #" line));

  cleanLine =
    line: lib.foldl' (acc: c: builtins.replaceStrings [ c ] [ " " ] acc) (stripComment line) shellNoise;

  tokens = line: lib.filter (t: t != "") (lib.splitString " " (cleanLine line));

  # Containment without a regex. `lib.hasInfix` is `builtins.match ".*x.*"`, whose engine
  # recurses per character: on a 100 KB file it exhausts the evaluator stack and reports
  # "possible infinite recursion" instead of an answer. `replaceStrings` is a C++ loop with
  # constant stack.
  mentions =
    needle: text:
    builtins.stringLength text
    != builtins.stringLength (builtins.replaceStrings [ needle ] [ "" ] text);

  # --- reference pins (ADR 0005) ------------------------------------------
  hex40 = lib.concatStrings (lib.genList (_: "[0-9a-f]") 40);

  # A local action is a directory in this repository: it moves with the commit.
  isLocal = ref: lib.hasPrefix "./" ref;
  isPinned = ref: builtins.match (".*@" + hex40) ref != null;
  isRevPinned = ref: builtins.match ("github:[^/]+/[^/]+/" + hex40 + "(#.*)?") ref != null;

  # The same line scanner, over the workflow files only: the action pins do not apply to
  # AGENTS.md, which is prose that quotes refs.
  scanWorkflows = pattern: lib.concatMap (f: scanLines f pattern) workflowSpecs;
  usesRefs = scanWorkflows ".*uses:[[:space:]]*([^[:space:]]+).*";
  githubRefs = scanWorkflows ".*(github:[^[:space:]]+).*";

  # --- what a pin can live in ----------------------------------------------
  # An adoption site EXECUTES the CLI or instructs an agent to. Prose is not one, and docs are
  # excluded by directory rather than by guesswork.
  workflowSpecs = map (n: {
    name = n;
    relPath = ".github/workflows/${n}";
    path = workflowDir + "/${n}";
  }) workflowFiles;

  agentsSpec = {
    name = "AGENTS.md";
    relPath = "AGENTS.md";
    path = src + "/AGENTS.md";
  };

  templateSpec = {
    name = "openspec/templates/ci-job.yml";
    relPath = "skills/software-development/openspec/templates/ci-job.yml";
    path = src + "/skills/software-development/openspec/templates/ci-job.yml";
  };

  bootstrapSpec = {
    name = "openspec/scripts/bootstrap.sh";
    relPath = "skills/software-development/openspec/scripts/bootstrap.sh";
    path = src + "/skills/software-development/openspec/scripts/bootstrap.sh";
  };

  adoptedSpecs = workflowSpecs ++ [
    agentsSpec
    templateSpec
    bootstrapSpec
  ];

  # Fail closed. `builtins.pathExists` used to guard the template, so renaming it left the scan
  # empty and the gate green. Presence is an ASSERTION now, and every read below uses the set
  # that passed it.
  adoptedMissing = map (f: f.relPath) (
    builtins.filter (f: !(builtins.pathExists f.path)) adoptedSpecs
  );
  adoptedPresent = builtins.filter (f: builtins.pathExists f.path) adoptedSpecs;

  # Every text file in the tree, by extension, walked once and reused by the CRLF assertion.
  textFilePaths = lib.filter (p: lib.any (e: lib.hasSuffix e (toString p)) textExts) (
    lib.filesystem.listFilesRecursive src
  );

  # --- 1.1 the runner label ------------------------------------------------
  # The label is the defect wherever it sits: `runs-on: ubuntu-latest`, a quoted value, a
  # bracketed list, a block list under `runs-on:`, and `os: [ubuntu-latest]` behind
  # `runs-on: ${{ matrix.os }}` all carry the same token on some line. Matching the token is
  # deliberately wider than parsing the YAML: a parser would only narrow the surface.
  runnerFloats = line: mentions "-latest" (stripComment line);

  # A runner is declared in a workflow or in the template workflows are made from. AGENTS.md
  # mentions `-latest` in prose ABOUT this rule, and a shell script's install message is not a
  # runner either — scanning those turns documentation into a false failure.
  runnerSpecs = builtins.filter (f: builtins.pathExists f.path) (workflowSpecs ++ [ templateSpec ]);

  floatingRunners = lib.concatMap (
    f:
    map (x: "${x.name}: ${stripComment x.line}") (
      lib.filter (x: runnerFloats x.line) (lib.filter (x: !(isComment x.line)) (numberedLines f))
    )
  ) runnerSpecs;

  # --- 1.2 the installed package -------------------------------------------
  # An exact version is three dot-separated numbers and nothing else. `@1`, `@1.15`, `@latest`,
  # `@^1.15.0`, `@~1.15.0` and a missing version all fail this, which is the point: a range
  # resolves to code nobody reviewed.
  isExactSpec =
    spec: spec != null && builtins.match "(@?[^@[:space:]]+)@([0-9]+\\.[0-9]+\\.[0-9]+)" spec != null;

  # Flags whose VALUE is not the package. Without this `--prefix ~/.local/npm` reads as a
  # package named `~/.local/npm`.
  valueFlags = [
    "--prefix"
    "-p"
    "--registry"
    "--cache"
    "--userconfig"
  ];

  dropFlagsAndValues =
    ts:
    if ts == [ ] then
      [ ]
    else if lib.hasPrefix "-" (builtins.head ts) then
      (
        if lib.elem (builtins.head ts) valueFlags && builtins.length ts > 1 then
          dropFlagsAndValues (builtins.tail (builtins.tail ts))
        else
          dropFlagsAndValues (builtins.tail ts)
      )
    else
      ts;

  afterWord =
    w: ts:
    if ts == [ ] then
      [ ]
    else if builtins.head ts == w then
      builtins.tail ts
    else
      afterWord w (builtins.tail ts);

  npmSubcommands = [
    "install"
    "i"
    "add"
  ];

  # `npx [-y] <spec>`: the first non-flag after `npx`.
  # `npm install|i|add -g|--global <spec>`: the first non-flag after the subcommand, with
  # value-taking flags and their values skipped.
  installSpecsIn =
    line:
    let
      ts = tokens line;
      npxRest = afterWord "npx" ts;
      npxCandidate = dropFlagsAndValues npxRest;
      npmRest = afterWord "npm" ts;
      npmAfterSub =
        if npmRest == [ ] || !(lib.elem (builtins.head npmRest) npmSubcommands) then
          npmRest
        else
          builtins.tail npmRest;
      npmCandidate = dropFlagsAndValues npmAfterSub;
      npmGlobal =
        npmRest != [ ]
        && lib.elem (builtins.head npmRest) npmSubcommands
        && (lib.elem "-g" ts || lib.elem "--global" ts);
    in
    lib.optional (npxRest != [ ]) (if npxCandidate == [ ] then null else builtins.head npxCandidate)
    ++ lib.optional npmGlobal (if npmCandidate == [ ] then null else builtins.head npmCandidate);

  installSpecs = lib.concatMap (
    f:
    lib.concatMap (
      x:
      map (spec: {
        inherit (x) name;
        inherit spec;
      }) (installSpecsIn x.line)
    ) (lib.filter (x: !(isComment x.line)) (numberedLines f))
  ) adoptedPresent;

  # --- 3.1 one version, checked at every site ------------------------------
  pinnedCli = pins.openspecCli;

  notPinnedVersion = builtins.filter (
    x: x.spec != null && !(lib.hasSuffix "@${pinnedCli}" x.spec)
  ) installSpecs;

  # A fifth site cannot appear silently: every file naming the package must be an adoption
  # site or prose. Prose legitimately quotes the forbidden forms as examples.
  prosePrefixes = [
    "docs/"
    "openspec/"
    # The gate quotes every forbidden spelling as test data; that is the opposite of adopting one.
    "nix/"
  ];

  adoptedRelPaths = map (a: a.relPath) adoptedSpecs;

  unadoptedMentions = map rel (
    builtins.filter (
      p: !(lib.elem (rel p) adoptedRelPaths) && !(lib.any (pre: lib.hasPrefix pre (rel p)) prosePrefixes)
    ) (builtins.filter (p: mentions "@fission-ai/openspec" (builtins.readFile p)) textFilePaths)
  );
  # --- plugins ------------------------------------------------------------
  # A plugin directory is discovered by its `plugin.yaml`, and the registry key is the
  # `name:` field: a mismatch installs one plugin under another's key.
  pluginDir = src + "/plugins";

  pluginNames =
    if builtins.pathExists pluginDir then
      lib.filter (n: builtins.readFileType (pluginDir + "/${n}") == "directory") (
        builtins.attrNames (builtins.readDir pluginDir)
      )
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
    ++ (
      if declared != null && declared != name then [ "${name}: plugin.yaml name is ${declared}" ] else [ ]
    )
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
      (
        if declaresGroup then [ ] else [ "${name}: pyproject.toml has no hermes_agent.plugins entry point" ]
      )
      ++ (
        if declaresKey then [ ] else [ "${name}: pyproject.toml declares no entry point named ${name}" ]
      )
  ) pluginNames;

  # Line-based, because `builtins.match` anchors `^` to the start of the whole string:
  # `.*^name` can never match — which made the first version report a correct pyproject
  # as broken.
  entrypointDeclares =
    name: text:
    lib.hasInfix "hermes_agent.plugins" text
    && lib.any (line: lib.hasPrefix "${name} =" (lib.trim line)) (lib.splitString "\n" text);

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
      expr = map (x: "${x.name}: ${x.value}") (builtins.filter (x: !(isRevPinned x.value)) githubRefs);
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
    # the package install. Both were unpinned until a council review named them, and the first
    # repair was evadable: `os: [ubuntu-latest]`, `@1  # comment`, `@^1.15.0` and a template
    # hidden behind `builtins.pathExists` all survived it.
    test_no_adopted_file_pins_a_floating_runner = {
      expr = floatingRunners;
      expected = [ ];
    };

    test_every_install_pins_an_exact_version = {
      expr = map (x: "${x.name}: ${if x.spec == null then "(no version at all)" else x.spec}") (
        builtins.filter (x: !(isExactSpec x.spec)) installSpecs
      );
      expected = [ ];
    };

    test_every_install_carries_the_version_in_pins_nix = {
      expr = map (x: "${x.name}: ${x.spec} (pins.nix: ${pinnedCli})") notPinnedVersion;
      expected = [ ];
    };

    test_every_adopted_file_is_present = {
      # Fail closed: a renamed template or bootstrap script fails here, naming the path.
      expr = adoptedMissing;
      expected = [ ];
    };

    test_the_scanned_set_is_not_empty = {
      # A scan over nothing passes every assertion above and looks exactly like a real pass.
      expr = builtins.length adoptedPresent >= 4 && builtins.length installSpecs >= 4;
      expected = true;
    };

    test_no_file_outside_the_adopted_set_names_the_cli = {
      expr = unadoptedMentions;
      expected = [ ];
    };

    # --- negative controls, one per rule, on the rule's own input -----------
    # Each case is a literal line, so the assertion exercises the predicate the check calls
    # rather than a copy of it. A predicate that accepted everything would pass the positive
    # checks above on any tree at all.
    test_the_runner_rule_rejects_every_form = {
      expr = map runnerFloats [
        "    runs-on: ubuntu-latest"
        "    runs-on: \"ubuntu-latest\""
        "    runs-on: [ubuntu-latest]"
        "    runs-on:"
        "      - ubuntu-latest"
        "        os: [ubuntu-latest]"
        "          - ubuntu-latest"
        "    runs-on: ubuntu-24.04"
        "    # runs-on: ubuntu-latest"
      ];
      expected = [
        true
        true
        true
        false
        true
        true
        true
        false
        false
      ];
    };

    test_the_install_rule_rejects_every_non_exact_form = {
      expr = map (line: map isExactSpec (installSpecsIn line)) [
        "npx -y @fission-ai/openspec@latest"
        "npx -y @fission-ai/openspec@^1.15.0"
        "npx -y @fission-ai/openspec@~1.15.0"
        "npx -y @fission-ai/openspec@1.15"
        "npx -y @fission-ai/openspec"
        "npx -y @fission-ai/openspec@1   # a comment after the version"
        "npm i -g @fission-ai/openspec@1"
        "npm install --global @fission-ai/openspec@1"
        "npm install -g --prefix ~/.local/npm @fission-ai/openspec@1.15.0"
        "nix shell nixpkgs#nodejs_22 -c npx -y @fission-ai/openspec@1.15.0 <verb>"
      ];
      expected = [
        [ false ]
        [ false ]
        [ false ]
        [ false ]
        [ false ]
        [ false ]
        [ false ]
        [ false ]
        [ true ]
        [ true ]
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
      expr = map (x: rel x.path) (builtins.filter (x: (x.fields.description or "") == "") catalog);
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
      expr = builtins.filter (d: !(builtins.pathExists (src + "/skills/${d}/SKILL.md"))) skillDirs;
      expected = [ ];
    };

    # --- encoding -----------------------------------------------------------
    # A CRLF shebang fails on Linux, and a CRLF/LF pair reports drift that is not there.
    test_no_text_file_carries_crlf = {
      expr = map rel (builtins.filter (p: L.hasCrlf (builtins.readFile p)) textFilePaths);
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
      expr = L.hasCrlf (
        builtins.readFile (src + "/skills/autonomous-ai-agents/council/scripts/council_loop.py")
      );
      expected = false;
    };

    test_the_frontmatter_gate_rejects_a_missing_fence = {
      expr = [
        (L.parseText "name: x\n---\n").startsWithFence
        (L.parseText "---\nname: x\n---\n").startsWithFence
      ];
      expected = [
        false
        true
      ];
    };

    test_the_frontmatter_gate_rejects_an_unclosed_fence = {
      expr = [
        (L.parseText "---\nname: x\n").closed
        (L.parseText "---\nname: x\n---\n").closed
      ];
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
        (L.duplicates [
          "a"
          "a"
          "b"
        ])
        (L.duplicates [
          "a"
          "b"
        ])
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
