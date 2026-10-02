#!/usr/bin/env bash
# Fails if the repo contains secret-looking strings or any real value from .env.
set -uo pipefail
cd "$(dirname "$0")/.."
FILES=$(git ls-files -co --exclude-standard 2>/dev/null || find . -type f -not -path './.git/*')
FILES=$(echo "$FILES" | grep -v -E '^(\./)?\.env$' | grep -v -E '\.txt$')   # .txt = public Census data
fail=0
check() {
  local label="$1" pattern="$2"
  local hits; hits=$(echo "$FILES" | xargs grep -n -I -E "$pattern" 2>/dev/null | grep -v 'check_secrets.sh')
  if [ -n "$hits" ]; then echo "FAIL [$label]"; echo "$hits" | cut -c1-160; fail=1; fi
}
check "private key"        '-----BEGIN [A-Z ]*PRIVATE KEY-----'
check "conn string key"    '(AccountKey|SharedAccessKey|InstrumentationKey)=[^;"<$ ]+'
check "SAS signature"      '[?&]sig=[A-Za-z0-9%/+=]{20,}'
check "bearer literal"     'Bearer [A-Za-z0-9._~+/=-]{20,}'
check "64-hex token"       '\b[0-9a-f]{64}\b'
check "Azure Maps key"     '\b[A-Za-z0-9]{84}\b'
check "subscription-key"   'subscription-key=[A-Za-z0-9]{20,}'
check "password assign"    '(password|passwd|pwd)[[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"'$<{]{4,}'
if [ -f .env ]; then
  while IFS='=' read -r k v; do
    [[ -z "$k" || "$k" == \#* || ${#v} -lt 8 || "$k" == MCP_CONNECTION_NAME ]] && continue
    hits=$(echo "$FILES" | xargs grep -n -I -F "$v" 2>/dev/null | grep -v '^\.env')
    [ -n "$hits" ] && { echo "FAIL [.env value $k not templated]"; echo "$hits" | cut -c1-160; fail=1; }
  done < .env
fi
[ $fail -eq 0 ] && echo "secret scan: clean" || echo "secret scan: FAILED"
exit $fail
