#!/usr/bin/env bash
set -euo pipefail

# Invoked by install_switchboard after Caddy's HTTP ACME route is active.
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
proxy_host="tin-lite-proxy.${TIN_LITE_STATIC_IP//./-}.sslip.io"

install -d -m 755 /usr/local/lib/tin-lite
grant_source="${source_dir}/proxy_grants.py"
if [[ ! -f "${grant_source}" ]]; then
  grant_source="${source_dir}/../src/tin_lite/proxy_grants.py"
fi
install -m 644 "${grant_source}" /usr/local/lib/tin-lite/proxy_grants.py
install -m 644 "${source_dir}/proxy_policy.py" /usr/local/lib/tin-lite/proxy_policy.py
install -d -m 755 /etc/tin-lite-proxy
install -d -m 750 -o root -g proxy /etc/tin-lite-proxy/tls
install -d -m 2750 -o tinlite -g proxy /var/lib/tin-lite-proxy-grants
install -d -m 750 -o proxy -g proxy /var/log/squid

/usr/bin/python3 /usr/local/lib/tin-lite/proxy_policy.py \
  --static-ip "${TIN_LITE_STATIC_IP}" --uid "$(id -u proxy)" --output /etc/tin-lite-proxy
/usr/sbin/nft --check --file /etc/tin-lite-proxy/proxy.nft

cat > /etc/systemd/system/tin-lite-proxy-firewall.service <<'EOF'
[Unit]
Description=Tin forward proxy destination fence
Before=tin-lite-proxy.service
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft --file /etc/tin-lite-proxy/proxy.nft
RemainAfterExit=yes
# No ExecStop: stopping the service must never remove the fence.

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/tin-lite-proxy.service <<'EOF'
[Unit]
Description=Tin TLS forward proxy
Requires=tin-lite-proxy-firewall.service
After=tin-lite-proxy-firewall.service network-online.target

[Service]
Type=simple
User=proxy
Group=proxy
RuntimeDirectory=tin-lite-proxy
ExecStartPre=/usr/sbin/squid -k parse -f /etc/tin-lite-proxy/squid.conf
ExecStart=/usr/sbin/squid -N -f /etc/tin-lite-proxy/squid.conf
ExecReload=/usr/sbin/squid -k reconfigure -f /etc/tin-lite-proxy/squid.conf
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/squid /run/tin-lite-proxy
CapabilityBoundingSet=
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
LimitCORE=0

[Install]
WantedBy=multi-user.target
EOF

install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/tin-lite-proxy <<EOF
#!/usr/bin/env bash
set -euo pipefail
if [[ "\${RENEWED_LINEAGE:-}" != "/etc/letsencrypt/live/${proxy_host}" ]]; then exit 0; fi
install -m 640 -o root -g proxy "\${RENEWED_LINEAGE}/fullchain.pem" /etc/tin-lite-proxy/tls/fullchain.pem
install -m 640 -o root -g proxy "\${RENEWED_LINEAGE}/privkey.pem" /etc/tin-lite-proxy/tls/privkey.pem
if systemctl is-active --quiet tin-lite-proxy.service; then
  systemctl reload tin-lite-proxy.service
fi
EOF
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/tin-lite-proxy
certbot certonly --non-interactive --agree-tos --register-unsafely-without-email \
  --webroot --webroot-path /var/lib/tin-lite-proxy-acme \
  --cert-name "${proxy_host}" --domain "${proxy_host}" --keep-until-expiring
RENEWED_LINEAGE="/etc/letsencrypt/live/${proxy_host}" \
  /etc/letsencrypt/renewal-hooks/deploy/tin-lite-proxy
/usr/sbin/squid -k parse -f /etc/tin-lite-proxy/squid.conf
systemctl daemon-reload
systemctl enable tin-lite-proxy-firewall tin-lite-proxy
systemctl enable --now certbot.timer
systemctl restart tin-lite-proxy-firewall
systemctl restart tin-lite-proxy
