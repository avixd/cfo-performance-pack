#!/usr/bin/env bash
# Fails if any tracked or staged file contains a Windows user path, OneDrive path or e-mail address.
set -euo pipefail
pattern='([A-Za-z]:\\\\Users\\\\|[A-Za-z]:\\Users\\|OneDrive|onmicrosoft\.com|[A-Za-z0-9._%+-]+@(gmail|outlook|hotmail)\.com)'
hits=$(git grep -nIE "$pattern" -- . ':!scripts/privacy_check.sh' || true)
if [ -n "$hits" ]; then echo "PRIVACY CHECK FAILED:"; echo "$hits"; exit 1; fi
echo "Privacy check passed."
