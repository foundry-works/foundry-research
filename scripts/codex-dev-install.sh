#!/usr/bin/env bash
set -euo pipefail

MARKETPLACE_NAME="foundry-local-test"
SKILLS=(
  "deep-research"
  "deep-research-revision"
  "reflect"
  "improve"
)

usage() {
  cat <<USAGE
Usage: $0 install|status|uninstall|cleanup

Actions:
  install    Symlink Foundry Research skills into CODEX_HOME/skills.
  status     Show current symlink and temporary marketplace state.
  uninstall  Remove only symlinks created by install.
  cleanup    Run uninstall and remove the temporary local marketplace entry.

Environment:
  CODEX_HOME  Defaults to ~/.codex.
USAGE
}

repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

codex_home() {
  if [[ -n "${CODEX_HOME:-}" ]]; then
    printf '%s\n' "$CODEX_HOME"
  elif [[ -n "${HOME:-}" ]]; then
    printf '%s\n' "$HOME/.codex"
  else
    echo "ERROR: CODEX_HOME is unset and HOME is unavailable." >&2
    exit 1
  fi
}

skill_target() {
  local skill="$1"
  printf '%s/skills/%s\n' "$(repo_root)" "$skill"
}

skill_link() {
  local skill="$1"
  printf '%s/skills/%s\n' "$(codex_home)" "$skill"
}

install_skills() {
  local home_dir
  home_dir="$(codex_home)"
  mkdir -p "$home_dir/skills"

  for skill in "${SKILLS[@]}"; do
    local target link current
    target="$(skill_target "$skill")"
    link="$(skill_link "$skill")"

    if [[ ! -d "$target" ]]; then
      echo "ERROR: Missing skill directory: $target" >&2
      exit 1
    fi

    if [[ -L "$link" ]]; then
      current="$(readlink "$link")"
      if [[ "$current" == "$target" ]]; then
        echo "ok: $skill -> $target"
      else
        echo "ERROR: $link already points to $current" >&2
        exit 1
      fi
    elif [[ -e "$link" ]]; then
      echo "ERROR: $link exists and is not a symlink." >&2
      exit 1
    else
      ln -s "$target" "$link"
      echo "linked: $skill -> $target"
    fi
  done
}

uninstall_skills() {
  for skill in "${SKILLS[@]}"; do
    local target link current
    target="$(skill_target "$skill")"
    link="$(skill_link "$skill")"

    if [[ -L "$link" ]]; then
      current="$(readlink "$link")"
      if [[ "$current" == "$target" ]]; then
        rm "$link"
        echo "removed: $link"
      else
        echo "skip: $link points to $current"
      fi
    elif [[ -e "$link" ]]; then
      echo "skip: $link exists and is not a symlink"
    else
      echo "ok: $link absent"
    fi
  done
}

marketplace_configured() {
  local config
  config="$(codex_home)/config.toml"
  [[ -f "$config" ]] && grep -q "^\[marketplaces\.${MARKETPLACE_NAME}\]" "$config"
}

cleanup_marketplace() {
  if marketplace_configured; then
    if command -v codex >/dev/null 2>&1; then
      codex plugin marketplace remove "$MARKETPLACE_NAME"
    else
      echo "WARN: codex CLI not found; remove marketplace $MARKETPLACE_NAME manually." >&2
    fi
  else
    echo "ok: marketplace $MARKETPLACE_NAME not configured"
  fi
}

status() {
  echo "repo: $(repo_root)"
  echo "codex_home: $(codex_home)"
  for skill in "${SKILLS[@]}"; do
    local target link
    target="$(skill_target "$skill")"
    link="$(skill_link "$skill")"
    if [[ -L "$link" ]]; then
      echo "skill: $skill -> $(readlink "$link")"
    elif [[ -e "$link" ]]; then
      echo "skill: $skill exists but is not a symlink"
    else
      echo "skill: $skill absent (target: $target)"
    fi
  done

  if marketplace_configured; then
    echo "marketplace: $MARKETPLACE_NAME configured"
  else
    echo "marketplace: $MARKETPLACE_NAME not configured"
  fi
}

main() {
  local action="${1:-}"
  case "$action" in
    install)
      install_skills
      ;;
    status)
      status
      ;;
    uninstall)
      uninstall_skills
      ;;
    cleanup)
      uninstall_skills
      cleanup_marketplace
      ;;
    -h|--help|help)
      usage
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
}

main "$@"
