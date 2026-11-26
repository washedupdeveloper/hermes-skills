#!/bin/sh
# install.sh — link every skill in this library into an agent's skills directory.
#
#   ./install.sh ~/.claude/skills              # flat: <target>/<skill>
#   ./install.sh ~/.hermes/skills --nested     # nested: <target>/<category>/<skill>
#   ./install.sh /tmp/skills --copy            # copy instead of symlink
#   ./install.sh /tmp/skills --dry-run         # print the plan, change nothing
#   ./install.sh ~/.hermes/skills --check      # verify an install, change nothing
#
# A symlink keeps one home for the text: edit the repository and every agent sees it.
# `--copy` is for hosts that will not follow a link out of their own tree.
set -eu

target=""
layout="flat"
mode="link"
dry=""
check=""

usage() {
  cat <<'EOF'
usage: ./install.sh <target-dir> [--nested] [--copy] [--dry-run] [--check] [--list]

  <target-dir>  the directory an agent reads skills from
  --nested      recreate <category>/<skill> instead of a flat <skill>
  --copy        copy the skill directories instead of symlinking them
  --dry-run     print what would happen, change nothing
  --check       verify an existing install and exit 1 if it does not match
  --list        print the skills this library ships, then exit
EOF
}

src=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
skills_root="$src/skills"

if [ ! -d "$skills_root" ]; then
  echo "install.sh: no skills/ beside this script — is this the library root?" >&2
  exit 2
fi

for arg in "$@"; do
  case "$arg" in
    --nested) layout="nested" ;;
    --copy) mode="copy" ;;
    --dry-run) dry="yes" ;;
    --check) check="yes" ;;
    --list)
      for f in "$skills_root"/*/*/SKILL.md; do
        printf '%s/%s\n' "$(basename "$(dirname "$(dirname "$f")")")" "$(basename "$(dirname "$f")")"
      done
      exit 0
      ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "install.sh: unknown option $arg" >&2; usage >&2; exit 2 ;;
    *) target="$arg" ;;
  esac
done

if [ -z "$target" ]; then
  usage >&2
  exit 2
fi

if [ -n "$check" ]; then
  # Verify, do not install: every shipped skill must be present in the target and
  # resolve to this library. An entry that points elsewhere is the failure this exists
  # for -- a link to an old checkout looks installed and is not.
  ok=0
  problems=0
  for file in "$skills_root"/*/*/SKILL.md; do
    [ -f "$file" ] || continue
    skill_dir=$(dirname "$file")
    name=$(basename "$skill_dir")
    category=$(basename "$(dirname "$skill_dir")")
    if [ "$layout" = "nested" ]; then
      dest="$target/$category/$name"
    else
      dest="$target/$name"
    fi
    want=$(CDPATH= cd -- "$skill_dir" && pwd -P)
    if [ -L "$dest" ]; then
      got=$(CDPATH= cd -- "$dest" 2>/dev/null && pwd -P) || got=""
      if [ "$got" = "$want" ]; then
        ok=$((ok + 1))
      else
        echo "  foreign  $dest -> $(readlink "$dest")"
        problems=$((problems + 1))
      fi
    elif [ -d "$dest" ]; then
      # A copy is a valid install too: MSYS `ln -s` falls back to copying, and a host
      # that will not follow links out of its tree uses --copy deliberately. What
      # matters is that the target reads this library, not how it got there.
      if diff -r -q -- "$skill_dir" "$dest" >/dev/null 2>&1; then
        ok=$((ok + 1))
      else
        echo "  stale    $dest (a copy that no longer matches this library)"
        problems=$((problems + 1))
      fi
    elif [ -e "$dest" ]; then
      echo "  foreign  $dest (not a skill directory)"
      problems=$((problems + 1))
    else
      echo "  missing  $dest"
      problems=$((problems + 1))
    fi
  done
  echo
  echo "install.sh: $ok ok, $problems problem(s), target $target"
  [ "$problems" -eq 0 ] || exit 1
  exit 0
fi

created=0
skipped=0
for file in "$skills_root"/*/*/SKILL.md; do
  [ -f "$file" ] || continue
  skill_dir=$(dirname "$file")
  name=$(basename "$skill_dir")
  category=$(basename "$(dirname "$skill_dir")")
  if [ "$layout" = "nested" ]; then
    dest="$target/$category/$name"
  else
    dest="$target/$name"
  fi

  if [ -e "$dest" ] || [ -L "$dest" ]; then
    echo "  keep    $dest (already there)"
    skipped=$((skipped + 1))
    continue
  fi

  if [ -n "$dry" ]; then
    echo "  would   $mode $dest"
    created=$((created + 1))
    continue
  fi

  mkdir -p "$(dirname "$dest")"
  if [ "$mode" = "copy" ]; then
    cp -R "$skill_dir" "$dest"
  else
    ln -s "$skill_dir" "$dest"
  fi
  echo "  $mode   $dest"
  created=$((created + 1))
done

echo
echo "install.sh: $created installed, $skipped left alone, target $target"
if [ "$layout" = "flat" ]; then
  echo "A host with a flat directory is served; use --nested for one that groups by category."
fi