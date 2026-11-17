"""Collection rules for the end-to-end tests.

`test_gate_mutants.py` runs `nix eval` on this repository's own eval-tier assertions:
it proves those assertions can fail. Without Nix it is unmeasurable, not passing.
"""
import shutil

collect_ignore = []
if shutil.which("nix") is None:
    collect_ignore.append("test_gate_mutants.py")
