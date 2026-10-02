#!/usr/bin/env bash
# Rebuild the EBS MCP backend on a fresh Ubuntu 24.04 VM (private VNet, no public IP).
# Oracle SQLcl's built-in MCP server (`sql -mcp`, stdio) -> mcp-proxy (SSE on 127.0.0.1:8081) -> nginx.
#
# Manual prerequisites (credentials are never stored in this repo):
#   1. Copy the Autonomous/Exadata DB wallet to /mcp/wallet (owner oracle, mode 700).
#   2. After this script, save the read-only DB connection as the oracle user:
#        sudo -u oracle -H /mcp/sqlcl/bin/sql /nolog
#        SQL> conn -save EBSDB_MCP -savepwd MCP_READER@<tns_alias>
#      MCP_READER must be read-only and limited to the curated MCP_VIEWS schema.
#   3. Then: sudo systemctl restart oracle-mcp
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

apt-get update
apt-get install -y openjdk-17-jre-headless python3-venv unzip nginx openssl

id oracle >/dev/null 2>&1 || useradd -m -s /bin/bash oracle
install -d -o oracle -g oracle /mcp /mcp/logs /mcp/config
install -d -o oracle -g oracle -m 700 /mcp/wallet

if [ ! -x /mcp/sqlcl/bin/sql ]; then
  curl -fsSL -o /tmp/sqlcl.zip https://download.oracle.com/otn_software/java/sqldeveloper/sqlcl-latest.zip
  unzip -q /tmp/sqlcl.zip -d /mcp && rm /tmp/sqlcl.zip
  chown -R oracle:oracle /mcp/sqlcl
fi

sudo -u oracle python3 -m venv /mcp/venv
sudo -u oracle /mcp/venv/bin/pip install --quiet "mcp-proxy==0.11.0" mcp

install -o oracle -g oracle -m 644 "$HERE/mcp-connect-primer.py" /mcp/mcp-connect-primer.py
install -m 644 "$HERE/oracle-mcp.service" /etc/systemd/system/oracle-mcp.service
install -d /etc/systemd/system/oracle-mcp.service.d
install -m 644 "$HERE/10-autoconnect.conf" /etc/systemd/system/oracle-mcp.service.d/10-autoconnect.conf

# Bearer token for the authenticated listeners (:8080, :8443). Generated once, never committed.
if [ ! -s /mcp/config/bearer.secret ]; then
  openssl rand -hex 32 > /mcp/config/bearer.secret
  chown oracle:oracle /mcp/config/bearer.secret && chmod 600 /mcp/config/bearer.secret
fi
if [ ! -s /mcp/config/mcp-tls.key ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=$(hostname)" \
    -keyout /mcp/config/mcp-tls.key -out /mcp/config/mcp-tls.crt
  chown oracle:oracle /mcp/config/mcp-tls.*
  chmod 600 /mcp/config/mcp-tls.key
fi

TOKEN="$(cat /mcp/config/bearer.secret)"
sed "s|\${MCP_BACKEND_BEARER_TOKEN}|${TOKEN}|g" "$HERE/nginx-mcp.conf" > /etc/nginx/sites-available/mcp
chmod 640 /etc/nginx/sites-available/mcp
ln -sf /etc/nginx/sites-available/mcp /etc/nginx/sites-enabled/mcp
rm -f /etc/nginx/sites-enabled/default
nginx -t

systemctl daemon-reload
systemctl enable --now oracle-mcp
systemctl reload nginx
echo "Done. Complete manual step 2 (saved DB connection), then: systemctl restart oracle-mcp"
