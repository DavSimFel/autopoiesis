#!/usr/bin/env bash
# Generate the Module Index table for AGENTS.md by scanning root .py files.
set -euo pipefail

echo "| Module | Description | Lines |"
echo "|--------|-------------|-------|"
for f in *.py; do
  desc=$(head -5 "$f" | grep -oP '"""\K[^"]*' | head -1 || true)
  lines=$(wc -l < "$f")
  echo "| \`$f\` | $desc | $lines |"
done
