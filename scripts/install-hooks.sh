#!/bin/sh
# One-time setup: enable the secret-guard pre-commit hook.
cd "$(git rev-parse --show-toplevel)" && cp scripts/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit && echo "pre-commit hook installed"
