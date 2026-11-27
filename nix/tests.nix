# The eval tier: what the tree SAYS, read without building anything. The run tier is
# `nix/checks.nix`; there is no build tier.
#
# An assertion belongs in the cheapest tier that can make it, so nothing here shells out: a
# frontmatter field, a length, a name and a path are all values. Four of these properties moved
# here from `tests/unit/test_repo_skills.py`, where a failure was a traceback instead of the
# skill's name and both values.
{
  lib,
  src,
  pkgs,
}:
let
  L = import ./lib.nix { inherit lib; };

  # The one machine-readable home for a version the repository adopts in more than one place.
  # Every adopted copy is checked against it, so bumping is this file plus the sites it lists.
  pins = import ./pins.nix;

  # The contract is ONE file, read here and by the runtime guard in `plugins/library-guard`;
  # `scripts/skill-contract.py` runs the same rules over a single file. A value that disagreed
  # with the contract would be a failure, not a preference — see the category assertion below.
  # The index truncates at `description_window` + "...", so the trigger must be self-contained
  # there: past that, the only part loaded before a skill opens is cut mid-word.
  contract = builtins.fromJSON (builtins.readFile (src + "/library/contract.json"));

  descMax = contract.description_window;

  required = contract.required_frontmatter;

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

  # The named sites come from `nix/pins.nix`, so the list exists once instead of being restated as
  # three singletons here. Workflows stay discovered: a new workflow that installs the CLI should be
  # checked without anyone remembering to list it.
  literalSiteSpecs = map (p: {
    name = p;
    relPath = p;
    path = src + "/${p}";
  }) pins.openspecCliSites;

  adoptedSpecs = workflowSpecs ++ literalSiteSpecs;

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

  # A runner is declared in a workflow or in the template workflows are made from. AGENTS.md names
  # `-latest` in prose ABOUT this rule and bootstrap.sh's install message is not a runner, so both
  # are excluded — scanning them turns documentation into a false failure. The set comes from
  # `pins.nix` by extension, so the template has one home.
  ymlSiteSpecs = builtins.filter (f: lib.hasSuffix ".yml" f.relPath) literalSiteSpecs;

  runnerSpecs = builtins.filter (f: builtins.pathExists f.path) (workflowSpecs ++ ymlSiteSpecs);

  floatingRunners = lib.concatMap (
    f:
    map (x: "${x.name}: ${stripComment x.line}") (
      lib.filter (x: runnerFloats x.line) (lib.filter (x: !(isComment x.line)) (numberedLines f))
    )
  ) runnerSpecs;

  # A `runs-on:` expression is allowed only where the label it resolves to is visible in the same
  # file. Two conditions, both blunt:
  #
  #   * the expression names a matrix key — `${{ matrix.os }}`, not `${{ inputs.os }}`,
  #     `${{ env.RUNNER }}`, `${{ fromJSON(...) }}`. The matrix values sit in the file the token
  #     scan already reads, so a pinned label there is a pinned label here.
  #   * `include:` appears nowhere, because it can add matrix values the list does not show — which
  #     is the one way an expression can name a label no reader can see.
  #
  # Refusing every expression was the first attempt. It means converting both matrix jobs into
  # explicit per-OS jobs — a CI restructure rather than a gate rule.
  runnerExpressionLines = lib.concatMap (
    f:
    map (x: "${x.name}: ${stripComment x.line}") (
      lib.filter (x: mentions "runs-on:" (stripComment x.line) && mentions "\${{" (stripComment x.line)) (
        lib.filter (x: !(isComment x.line)) (numberedLines f)
      )
    )
  ) runnerSpecs;

  runnerExpressionIsOpaque = line: !(mentions "matrix." line);

  runnerUsesInclude = lib.any (
    f: mentions "include:" (lib.concatStringsSep "\n" (map (x: x.line) (numberedLines f)))
  ) runnerSpecs;

  # --- 1.2 the CLI command ------------------------------------------------
  # The CLI is a dependency of this flake, not something installed at run time: `nix run
  # .#openspec` resolves it through `flake.lock`, so there is no version string in a command to
  # drift. The rule is therefore the form, not a literal:
  #
  #     nix run .#openspec -- validate --all --strict     # the only accepted form
  #     npx -y @fission-ai/openspec@1.15.0 validate       # a network fetch, a second pin
  #
  # `npx` and `npm install -g` resolve outside the lock and leave state outside the store. That
  # is the anti-pattern the nix domain skills name; the gate enforces it here rather than
  # trusting prose to.
  cliApp = ".#openspec";
  cliPackage = "@fission-ai/openspec";
  cliRunForm = "nix run ${cliApp}";

  # A line that invokes the CLI: the flake app, or the package name as an npm form names it, or
  # the bare binary where a command would start. Prose such as "the `openspec` skill" does not
  # start a line and is not scanned.
  runsCli =
    line:
    lib.any (n: mentions n (stripComment line)) [
      cliApp
      cliPackage
    ]
    || builtins.match "[[:space:]]*openspec[[:space:]]+.*" (stripComment line) != null;

  usesCliRunForm = line: mentions cliRunForm (stripComment line);

  cliLines = lib.concatMap (
    f:
    map (x: {
      inherit (x) name;
      inherit (x) line;
    }) (lib.filter (x: runsCli x.line) (lib.filter (x: !(isComment x.line)) (numberedLines f)))
  ) adoptedPresent;

  # `npx` is named wherever it sits: a wrapper that calls it is the same defect as one that
  # writes the package name, and it is the form a contributor reaches for by habit.
  # An INVOCATION, not a mention: prose has to be able to name the thing it forbids, and
  # "`npx` and `npm install -g` are what this replaces" is documentation, not a defect.
  invokesNpx =
    line:
    builtins.match "npx[[:space:]]+[-a-zA-Z@].*" line != null
    || builtins.match ".*[[:space:]`(]npx[[:space:]]+[-a-zA-Z@].*" line != null
    || builtins.match "[[:space:]]*npm[[:space:]]+install.*" line != null;

  npxLines = lib.concatMap (
    f:
    map (x: "${x.name}: ${stripComment x.line}") (
      lib.filter (x: invokesNpx (stripComment x.line)) (
        lib.filter (x: !(isComment x.line)) (numberedLines f)
      )
    )
  ) adoptedPresent;

  cliOutsideTheForm = lib.concatMap (
    f:
    map (x: "${x.name}: ${stripComment x.line}") (
      lib.filter (x: runsCli x.line && !(usesCliRunForm x.line)) (
        lib.filter (x: !(isComment x.line)) (numberedLines f)
      )
    )
  ) adoptedPresent;

  # --- 3.1 one version, checked against the flake --------------------------
  pinnedCli = pins.openspecCli;

  # A fifth site cannot appear silently: every file naming the package must be an adoption
  # site, or be somewhere the name is data rather than a command. Prose quotes the forbidden
  # forms as examples; the gate and its tests construct them as fixtures. That is the opposite
  # of adopting one, and exempting it is what keeps this rule from firing on its own harness.
  exemptPrefixes = [
    "docs/"
    "openspec/"
    "nix/"
    "tests/"
  ];

  # The nix-flake skills teach the pattern this rule enforces; naming the app there is the
  # point. Matched on the skill's own name, not its directory: this was `skills/devops/nix-`
  # and the taxonomy move to `skills/build/` turned the gate red for a reason that had
  # nothing to do with the rule.
  exemptSkillNames = [
    "nix-flake-checks"
    "nix-flake-packaging"
  ];

  # The flake defines the app; it does not invoke it.
  exemptFiles = [ "flake.nix" ];

  adoptedRelPaths = map (a: a.relPath) adoptedSpecs;

  unadoptedMentions = map rel (
    builtins.filter
      (
        p:
        !(lib.elem (rel p) adoptedRelPaths)
        && !(lib.elem (rel p) exemptFiles)
        && !(lib.any (pre: lib.hasPrefix pre (rel p)) exemptPrefixes)
        && !(lib.any (name: lib.hasInfix "/${name}/" (rel p)) exemptSkillNames)
      )
      (
        builtins.filter (
          p:
          lib.any (n: mentions n (builtins.readFile p)) [
            cliApp
            cliPackage
          ]
        ) textFilePaths
      )
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

    test_a_runner_expression_names_a_matrix_key = {
      expr = lib.filter runnerExpressionIsOpaque runnerExpressionLines;
      expected = [ ];
    };

    test_the_expression_rule_rejects_an_opaque_label = {
      expr = map runnerExpressionIsOpaque [
        "    runs-on: \${{ matrix.os }}"
        "    runs-on: \${{ inputs.runner }}"
        "    runs-on: \${{ fromJSON(needs.setup.outputs.runner) }}"
        "    runs-on: ubuntu-24.04"
      ];
      expected = [
        false
        true
        true
        true
      ];
    };

    test_no_matrix_is_assembled_from_include = {
      expr = runnerUsesInclude;
      expected = false;
    };

    test_every_cli_command_is_the_flake_app = {
      expr = cliOutsideTheForm ++ npxLines;
      expected = [ ];
    };

    test_the_cli_rule_rejects_every_other_form = {
      expr = map (line: runsCli line && !(usesCliRunForm line)) [
        "npx -y @fission-ai/openspec@1.15.0 validate --all --strict"
        "npm install -g @fission-ai/openspec@1.15.0"
        "openspec validate --all --strict"
        "nix shell nixpkgs#nodejs_22 -c npx -y @fission-ai/openspec@1.15.0 validate"
        "nix run .#openspec -- validate --all --strict"
        "      nix run .#openspec -- archive x --yes"
      ];
      expected = [
        true
        true
        true
        true
        false
        false
      ];
    };

    test_the_flake_app_is_the_version_in_pins_nix = {
      # A literal in `pins.nix` that disagreed with the flake would be a second, rotting pin.
      expr = pkgs.openspec.version;
      expected = pinnedCli;
    };

    test_the_site_list_is_not_empty = {
      expr = builtins.length pins.openspecCliSites > 0;
      expected = true;
    };

    test_every_adopted_file_is_present = {
      # Fail closed: a renamed template or bootstrap script fails here, naming the path.
      expr = adoptedMissing;
      expected = [ ];
    };

    test_the_scanned_set_is_not_empty = {
      # A scan over nothing passes every assertion above and looks exactly like a real pass.
      expr = builtins.length cliLines >= 4 && builtins.length adoptedPresent >= 4;
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

    test_the_cli_rule_rejects_every_form = {
      expr = map (line: runsCli line && !(usesCliRunForm line)) [
        "npx -y @fission-ai/openspec@1.15.0 validate"
        "npm i -g @fission-ai/openspec@1.15.0"
        "openspec validate --all --strict"
        "  nix run .#openspec -- validate --all --strict"
      ];
      expected = [
        true
        true
        true
        false
      ];
    };
  };

}
