#!/usr/bin/env bash
# One-time (or repeatable) setup for running Lumen from source.
set -euo pipefail

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$here"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e '.[dev]'

# Put a launcher on PATH without copying it (the launcher resolves its own
# symlink, so edits to the checkout take effect immediately).
mkdir -p "$HOME/.local/bin"
ln -sfn "$PWD/bin/lumen" "$HOME/.local/bin/lumen"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) printf '\nNote: add ~/.local/bin to PATH to run "lumen" by name.\n' ;;
esac

# The desktop entry is what lets the XDG portal resolve the app ID, so install
# it rather than leaving "Open with" to chance.
applications="$HOME/.local/share/applications"
mkdir -p "$applications"
sed "s|@ROOT@|$PWD|g" lumen.desktop > "$applications/lumen.desktop"
update-desktop-database "$applications" 2>/dev/null || true

cat <<'EOF'

Lumen is ready.

  Run it:    lumen [file|folder]
  Or:        ./bin/lumen [file|folder]
  Tests:     .venv/bin/pytest

  Launcher:  ~/.local/bin/lumen
  Entry:     ~/.local/share/applications/lumen.desktop

EOF
