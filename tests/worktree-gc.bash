#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
python3 -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' bin/worktree-gc
python3 -m unittest tests.worktree_gc_test "$@"
echo 'worktree-gc: PASS'
