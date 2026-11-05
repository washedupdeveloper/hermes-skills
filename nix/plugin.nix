# nix/plugin.nix — one plugin directory as an installable Python distribution.
#
# `pname`, `version` and `description` come from the plugin's own `pyproject.toml`: one home per
# fact, so a bump there cannot disagree with the package that ships. The same directory is also a
# drop-in plugin (`plugin.yaml` + `__init__.py`), so the code exists once; this is the entry-point
# path, which Hermes discovers through `importlib.metadata`. Built with Hermes' own interpreter,
# so the module lands where the wrapper's `PYTHONPATH` suffix reaches.
{
  lib,
  python3,
  src,
  module,
}:
let
  project = (builtins.fromTOML (builtins.readFile (src + "/pyproject.toml"))).project;
in
python3.pkgs.buildPythonPackage {
  pname = project.name;
  version = project.version;

  # `pyproject = true` and `format` are mutually exclusive: setting both is an assertion
  # failure in nixpkgs.
  pyproject = true;

  # setuptools packages only what `pyproject.toml` lists, so `plugin.yaml` and the
  # directory-drop `__init__.py` stay out of the wheel without an exclusion list.
  inherit src;

  build-system = [ python3.pkgs.setuptools ];

  # No dependencies beyond the standard library and no tests of its own: each plugin is
  # exercised against a real agent session and by `tests/unit/`, not in isolation here.
  doCheck = false;
  pythonImportsCheck = [ module ];

  meta = {
    inherit (project) description;
    homepage = "https://github.com/washedupdeveloper/hermes-skills";
    license = lib.licenses.mit;
    platforms = lib.platforms.unix;
  };
}
