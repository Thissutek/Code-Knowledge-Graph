#!/usr/bin/env bash
# Code-KAG post-rewrite hook
# Triggers full re-index after rebase or amend.
# Arg: $1=command that triggered the rewrite (rebase or amend)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/code-kag-common.sh"

# After rebase or amend, do a full re-index since commit history changed
code_kag_reindex "full"
