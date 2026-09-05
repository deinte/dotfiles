#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home" AGENT_WORKSTATION_ROOT="$TMP/ws"; mkdir -p "$HOME"
unset DOTFILES_ROOT
snapshot() { find "$TMP" \( -type f -o -type l \) -print0 | sort -z | xargs -0 -r sha256sum; }
"$ROOT/bin/install-linux-devstation" --dry-run >/dev/null
[[ ! -e "$TMP/ws" && ! -e "$HOME/.local/bin" ]]
mkdir -p "$TMP/ws/repos" "$TMP/ws/worktrees" "$TMP/ws/artifacts"; echo keep >"$TMP/ws/repos/keep"; echo keep >"$TMP/ws/worktrees/keep"; echo keep >"$TMP/ws/artifacts/keep"
"$ROOT/bin/install-linux-devstation"
for d in repos worktrees artifacts runs locks scripts; do [[ -d "$TMP/ws/$d" ]]; done
for f in agent-task workstation-doctor worktree-gc; do [[ -f "$TMP/ws/scripts/$f" && -x "$TMP/ws/scripts/$f" && "$(stat -c %a "$TMP/ws/scripts/$f")" == 700 ]]; [[ -L "$HOME/.local/bin/$f" && "$(readlink "$HOME/.local/bin/$f")" == "$TMP/ws/scripts/$f" ]]; done
[[ -L "$HOME/.local/bin/workstation-sync" && "$(readlink "$HOME/.local/bin/workstation-sync")" == "$ROOT/bin/workstation-sync" ]]
baseline="$(snapshot)"; "$ROOT/bin/install-linux-devstation" >/dev/null; [[ "$baseline" == "$(snapshot)" ]]
echo changed >>"$TMP/ws/scripts/agent-task"; "$ROOT/bin/install-linux-devstation" >/dev/null
[[ "$(find "$TMP/ws/scripts" -maxdepth 1 -name 'agent-task.backup-*' | wc -l)" -eq 1 ]]; cmp "$ROOT/bin/agent-task" "$TMP/ws/scripts/agent-task"
[[ "$(cat "$TMP/ws/repos/keep")" == keep && "$(cat "$TMP/ws/worktrees/keep")" == keep && "$(cat "$TMP/ws/artifacts/keep")" == keep ]]

git init -q "$TMP/dotfiles"; git -C "$TMP/dotfiles" config user.email test@example.com; git -C "$TMP/dotfiles" config user.name test; cp -a "$ROOT/bin" "$TMP/dotfiles/"; git -C "$TMP/dotfiles" add .; git -C "$TMP/dotfiles" commit -qm base; git -C "$TMP/dotfiles" branch -M main
git init -q --bare "$TMP/origin.git"; git -C "$TMP/dotfiles" remote add origin "$TMP/origin.git"; git -C "$TMP/dotfiles" push -q -u origin main
DOTFILES_ROOT="$TMP/dotfiles"; export DOTFILES_ROOT; echo dirty >>"$TMP/dotfiles/dirty"; ! "$TMP/dotfiles/bin/workstation-sync" >/dev/null 2>&1
rm -f "$TMP/dotfiles/dirty"; GIT_BIN="$(command -v git)"; mkdir "$TMP/git-bin"; cat >"$TMP/git-bin/git" <<EOF
#!/usr/bin/env bash
printf '%s\\n' "\$*" >>"$TMP/git-commands"
exec "$GIT_BIN" "\$@"
EOF
chmod +x "$TMP/git-bin/git"; PATH="$TMP/git-bin:$PATH" "$TMP/dotfiles/bin/workstation-sync" >/dev/null
grep -Fxq 'fetch origin main' "$TMP/git-commands"; grep -Fxq 'merge --ff-only origin/main' "$TMP/git-commands"; unset DOTFILES_ROOT
baseline="$(snapshot)"; "$HOME/.local/bin/workstation-sync" --local-current-tree >/dev/null; [[ "$baseline" == "$(snapshot)" ]]
baseline="$(snapshot)"; "$HOME/.local/bin/workstation-sync" --local-current-tree --dry-run >/dev/null; [[ "$baseline" == "$(snapshot)" ]]
echo 'linux-devstation: PASS'
