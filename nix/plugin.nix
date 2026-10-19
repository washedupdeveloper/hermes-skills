# nix/plugin.nix — harness-audit as an installable Python distribution. The same directory
# is also a drop-in plugin (`plugin.yaml` + `__init__.py`), so the code exists once; this is
# the entry-point path, which Hermes discovers through `importlib.metadata`. Built with
# Hermes' own interpreter, so the module lands where the `PYTHONPATH` suffix reaches.
{
  lib,
  python3,
}:
python3.pkgs.buildPythonPackage {
  pname = "hermes-harness-audit";
  version = "1.1.0";
  # `pyproject = true` and `format` are mutually exclusive: setting both is an assertion
  # failure in nixpkgs.
  pyproject = true;

  # setuptools packages only `py-modules`, so `plugin.yaml` and the directory-drop
  # `__init__.py` stay out of the wheel without an exclusion list.
  src = ../plugins/harness-audit;

  build-system = [ python3.pkgs.setuptools ];

  # No dependencies beyond the standard library and no tests of its own: it is exercised
  # end-to-end against a real agent session, not in isolation.
  doCheck = false;
  pythonImportsCheck = [ "harness_audit" ];

  meta = {
    description = "Durable tool-call and model-request audit, plus catalog-completeness reporting, for Hermes Agent";
    homepage = "https://github.com/washedupdeveloper/hermes-skills";
    license = lib.licenses.mit;
    platforms = lib.platforms.unix;
  };
}
