#!/usr/bin/env bash
# Generate the Module Index table for AGENTS.md by scanning root .py files.
set -euo pipefail

echo "| Module | Description | Lines |"
echo "|--------|-------------|-------|"
for f in *.py; do
  desc=$(sed -n 's/^"""\(.*\)/\1/p' "$f" | head -1 | sed 's/"""$//; s/``/`/g')
  lines=$(wc -l < "$f")
  echo "| \`$f\` | $desc | $lines |"
done
