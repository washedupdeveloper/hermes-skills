# nix/plugin.nix — harness-audit as an installable Python distribution.
#
# The same directory is also a drop-in plugin (`plugin.yaml` + `__init__.py`), so the code
# exists once. This derivation is the *other* install path: a distribution carrying the
# `hermes_agent.plugins` entry point, which Hermes discovers through
# `importlib.metadata` — no file is copied into a profile, and the source tree is never
# modified.
#
# Built with the interpreter Hermes itself runs on, so the module lands in a
# `site-packages` layout the agent's `PYTHONPATH` suffix can reach.
{
  lib,
  python3,
}:
python3.pkgs.buildPythonPackage {
  pname = "hermes-harness-audit";
  version = "1.0.0";
  # `pyproject = true` selects the pyproject build path; setting `format` as well is an
  # assertion failure in nixpkgs (the two are mutually exclusive).
  pyproject = true;

  # `plugins/harness-audit` holds pyproject.toml, harness_audit.py, plugin.yaml and the
  # directory-drop `__init__.py`. setuptools packages only `py-modules`, so the manifest
  # and the shim stay out of the wheel without needing an exclusion list.
  src = ../plugins/harness-audit;

  build-system = [ python3.pkgs.setuptools ];

  # The plugin has no dependencies beyond the standard library, and no tests of its own:
  # it is exercised end-to-end against a real agent session rather than in isolation.
  doCheck = false;
  pythonImportsCheck = [ "harness_audit" ];

  meta = {
    description = "Durable tool-call audit and catalog-completeness reporting for Hermes Agent";
    homepage = "https://github.com/washedupdeveloper/hermes-skills";
    license = lib.licenses.mit;
    platforms = lib.platforms.unix;
  };
}
