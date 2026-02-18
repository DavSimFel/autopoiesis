#!/usr/bin/env bash
# Generate the Module Index table for AGENTS.md by scanning src/autopoiesis.
set -euo pipefail

echo "| Module | Description | Lines |"
echo "|--------|-------------|-------|"
while IFS= read -r f; do
  rel="${f#src/autopoiesis/}"
  desc=$(sed -n 's/^"""\(.*\)/\1/p' "$f" | head -1 | sed 's/"""$//; s/``/`/g')
  lines=$(wc -l < "$f")
  echo "| \`$rel\` | $desc | $lines |"
done < <(find src/autopoiesis -type f -name "*.py" ! -name "__init__.py" | sort)
