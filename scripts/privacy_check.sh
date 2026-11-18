#!/usr/bin/env bash
# Fails if any tracked or staged file contains a real Windows user path (C:\Users\<name>), a OneDrive folder path, a tenant domain or a
# personal e-mail address. Placeholders such as C:\Users\<you> and the bare word OneDrive are allowed.
set -euo pipefail
pattern='([A-Za-z]:\\\\Users\\\\[^<\\]|[A-Za-z]:\\Users\\[^<\\]|OneDrive( - [A-Za-z]|[\\/])|onmicrosoft\.com|[A-Za-z0-9._%+-]+@(gmail|outlook|hotmail)\.com)'
hits=$(git grep -nIE "$pattern" -- . ':!scripts/privacy_check.sh' || true)
if [ -n "$hits" ]; then echo "PRIVACY CHECK FAILED:"; echo "$hits"; exit 1; fi
echo "Privacy check passed."
