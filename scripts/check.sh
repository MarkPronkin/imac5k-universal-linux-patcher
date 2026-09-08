#!/usr/bin/env bash
# Offline development checks. Run from a git checkout, not an installed release.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
cd "$REPO_DIR"
[[ -d tests ]] || { echo "Run checks from a repository checkout; release installs omit tests/." >&2; exit 1; }

printf 'Checking Bash syntax...\n'
for script in install.sh scripts/* scripts/lib/*.sh; do
    [[ -f $script ]] || continue
    IFS= read -r shebang < "$script" || continue
    [[ $shebang == '#!/usr/bin/env bash' ]] || continue
    bash -n "$script"
done

printf 'Running offline tests...\n'
python3 -m unittest discover -s tests "$@"
