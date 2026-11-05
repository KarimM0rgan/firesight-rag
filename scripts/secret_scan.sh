#!/usr/bin/env bash
# Working-tree secret scan that CANNOT read the live credential file.
#
# Written after an ad-hoc `grep -rIn 'sk-ant-...' .` read .env and printed the
# live key to a terminal. A scan whose failure mode is exposing the secret it
# looks for is worse than no scan. Exclusions are explicit, and matches are
# reported by location only -- never with the matched text.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PATTERN='sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|AKIA[0-9A-Z]{16}'

hits=$(grep -rIlE "$PATTERN" . \
  --exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules \
  --exclude=.env --exclude=.env.local --exclude='*.pyc' 2>/dev/null \
  | grep -v '^\./\.env' || true)

# .env.example must contain only placeholders.
if grep -qE 'sk-ant-[A-Za-z0-9_-]{20,}' .env.example 2>/dev/null; then
  if ! grep -qE 'x{8,}' .env.example; then
    echo "FAIL: .env.example may hold a real key"; exit 1
  fi
  hits=$(echo "$hits" | grep -v '^\./\.env\.example$' || true)
fi

if [ -n "$hits" ]; then
  echo "FAIL: credential-shaped strings found in:"
  echo "$hits" | sed 's/^/  /'
  echo "(locations only; matched text deliberately not printed)"
  exit 1
fi
echo "PASS: no credential-shaped strings in the working tree (.env excluded by design)"
