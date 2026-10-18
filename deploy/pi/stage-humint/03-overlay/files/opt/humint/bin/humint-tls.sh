#!/usr/bin/env bash
# HTTPS for the field console, with a certificate authority of the box's own.
#
# Why a CA and not just a self-signed certificate: the box's address changes
# (hotspot, a hotel Wi-Fi, a cable), and a certificate is only valid for the
# names and addresses written into it. With a CA, each phone and laptop
# installs ONE certificate once — the CA's — and every server certificate the
# box issues itself afterwards is trusted, warning-free, whatever its address.
# The Android field app already trusts user-installed CAs.
#
# Why that is safe to ask of a team: the CA is NAME-CONSTRAINED. It can only
# vouch for *.local names, this box's own name, and private (RFC 1918) and
# loopback addresses. Installing it cannot let anyone impersonate a bank, a
# mail server or any other public site, even if its key were stolen.
#
# The CA key and the server key live inside the encrypted case store. Only
# the CA's public certificate is copied out (to /var/lib/humint/ca.crt) so it
# can be downloaded from http://<box>/ca.crt before anyone trusts anything.
#
#   humint-tls.sh ensure     make the CA if missing; (re)issue the server
#                            certificate if missing, expiring, or not
#                            covering this box's current names/addresses
#   humint-tls.sh renew      issue a new server certificate now
#   humint-tls.sh fingerprint  the CA's SHA-256 fingerprint
#   humint-tls.sh enabled    exit 0 if TLS is switched on
set -euo pipefail
# shellcheck source=/dev/null
. /opt/humint/lib/humint-common.sh

TLS_DIR="$HUMINT_DATA/tls"
CA_KEY="$TLS_DIR/ca.key"
CA_CRT="$TLS_DIR/ca.crt"
SRV_KEY="$TLS_DIR/server.key"
SRV_CRT="$TLS_DIR/server.crt"
PUBLIC_CA="$HUMINT_STATE/ca.crt"
PUBLIC_FP="$HUMINT_STATE/ca.fingerprint"
# Apple refuses server certificates valid for longer than 825 days.
SRV_DAYS=825
HOTSPOT_IP=10.42.0.1

tls_on() {
    load_config "$HUMINT_ENV"
    [ "${TLS:-on}" = "on" ]
}

# Private, carrier-NAT, link-local and loopback only: the CA's name
# constraints allow nothing else, so a certificate naming a public address
# would be rejected by every client. On such a network, use <name>.local.
permitted_ip() {
    local a b
    IFS=. read -r a b _ _ <<<"$1"
    [ "$a" = 10 ] || [ "$a" = 127 ] ||
        { [ "$a" = 172 ] && [ "$b" -ge 16 ] && [ "$b" -le 31 ]; } ||
        { [ "$a" = 192 ] && [ "$b" = 168 ]; } ||
        { [ "$a" = 100 ] && [ "$b" -ge 64 ] && [ "$b" -le 127 ]; } ||
        { [ "$a" = 169 ] && [ "$b" = 254 ]; }
}

current_ips() {
    # Every IPv4 the box answers on right now, plus the hotspot's fixed one.
    local ip
    { hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' || true
      echo "$HOTSPOT_IP"; echo 127.0.0.1; } | sort -u |
    while read -r ip; do
        if permitted_ip "$ip"; then echo "$ip"; fi
    done
}

host_name() { hostname -s 2>/dev/null || echo humint; }

make_ca() {
    local host; host="$(host_name)"
    log "creating the console's certificate authority"
    install -d -m 750 -o root -g "$APP_USER" "$TLS_DIR"
    local cnf; cnf="$(mktemp)"
    cat >"$cnf" <<EOF
[req]
distinguished_name = dn
prompt = no
x509_extensions = v3_ca
[dn]
CN = HUMINT field console CA ($host)
O = HUMINT field server
[v3_ca]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
nameConstraints = critical, permitted;DNS:local, permitted;DNS:$host, permitted;IP:10.0.0.0/255.0.0.0, permitted;IP:172.16.0.0/255.240.0.0, permitted;IP:192.168.0.0/255.255.0.0, permitted;IP:127.0.0.0/255.0.0.0, permitted;IP:100.64.0.0/255.192.0.0, permitted;IP:169.254.0.0/255.255.0.0
EOF
    (umask 077; openssl ecparam -name prime256v1 -genkey -noout -out "$CA_KEY")
    openssl req -new -x509 -key "$CA_KEY" -sha256 -days 3650 -config "$cnf" -out "$CA_CRT"
    rm -f "$cnf"
    chmod 600 "$CA_KEY"; chmod 644 "$CA_CRT"
    rm -f "$SRV_CRT"           # anything issued by an older CA is now orphaned
}

publish_ca() {
    install -m 644 "$CA_CRT" "$PUBLIC_CA"
    fingerprint >"$PUBLIC_FP"
    # Windows shows a certificate's SHA-1 "Thumbprint", not its SHA-256
    # fingerprint, so the trust page offers that too for checking.
    openssl x509 -in "$CA_CRT" -noout -fingerprint -sha1 | sed 's/^.*=//' >"$PUBLIC_FP.sha1"
    chmod 644 "$PUBLIC_FP.sha1"
    chmod 644 "$PUBLIC_FP"
}

fingerprint() {
    local f="$CA_CRT"
    [ -f "$f" ] || f="$PUBLIC_CA"
    [ -f "$f" ] || { echo "no CA yet" >&2; return 1; }
    openssl x509 -in "$f" -noout -fingerprint -sha256 | sed 's/^.*=//'
}

# Does the server certificate cover every name and address we need, and
# have more than 30 days left?
srv_is_current() {
    [ -f "$SRV_CRT" ] && [ -f "$SRV_KEY" ] || return 1
    openssl x509 -in "$SRV_CRT" -noout -checkend $((30 * 86400)) >/dev/null || return 1
    # Issued while the clock ran fast, and the clock has since been put right
    # (humint-clock): not valid yet, so every browser would refuse it.
    local nb; nb="$(openssl x509 -in "$SRV_CRT" -noout -startdate | cut -d= -f2)"
    [ "$(date -d "$nb" +%s 2>/dev/null || echo 0)" -le "$(date +%s)" ] || return 1
    openssl verify -CAfile "$CA_CRT" "$SRV_CRT" >/dev/null 2>&1 || return 1
    local sans; sans="$(openssl x509 -in "$SRV_CRT" -noout -ext subjectAltName 2>/dev/null)"
    local host ip; host="$(host_name)"
    grep -q "DNS:${host}.local" <<<"$sans" || return 1
    while read -r ip; do
        [ -n "$ip" ] || continue
        grep -qE "IP Address:${ip//./\\.}(,|$)" <<<"$sans" || return 1
    done < <(current_ips)
    return 0
}

issue_server() {
    local host; host="$(host_name)"
    local san="DNS:${host}.local, DNS:${host}"
    local ip
    while read -r ip; do
        [ -n "$ip" ] && san="$san, IP:$ip"
    done < <(current_ips)
    log "issuing server certificate for: $san"
    local cnf csr; cnf="$(mktemp)"; csr="$(mktemp)"
    cat >"$cnf" <<EOF
[req]
distinguished_name = dn
prompt = no
[dn]
CN = ${host}.local
[srv]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = $san
authorityKeyIdentifier = keyid
subjectKeyIdentifier = hash
EOF
    (umask 027; openssl ecparam -name prime256v1 -genkey -noout -out "$SRV_KEY.new")
    openssl req -new -key "$SRV_KEY.new" -config "$cnf" -out "$csr"
    openssl x509 -req -in "$csr" -CA "$CA_CRT" -CAkey "$CA_KEY" -CAcreateserial \
        -days "$SRV_DAYS" -sha256 -extfile "$cnf" -extensions srv -out "$SRV_CRT.new" 2>/dev/null
    rm -f "$cnf" "$csr"
    chown root:"$APP_USER" "$SRV_KEY.new" "$SRV_CRT.new"
    chmod 640 "$SRV_KEY.new"; chmod 644 "$SRV_CRT.new"
    mv -f "$SRV_KEY.new" "$SRV_KEY"; mv -f "$SRV_CRT.new" "$SRV_CRT"
}

cmd_ensure() {
    data_ready || die "case store is not open"
    [ -f "$CA_KEY" ] && [ -f "$CA_CRT" ] || make_ca
    publish_ca
    if srv_is_current; then
        return 0
    fi
    issue_server
    # Tell a running console about it; the units call this before starting,
    # so on a cold start there is nothing to restart.
    if [ "${1:-}" = "--restart" ] && systemctl -q is-active humint-api.service; then
        systemctl restart humint-api.service
    fi
}

case "${1:-}" in
    ensure)      shift; cmd_ensure "$@" ;;
    renew)       data_ready || die "case store is not open"; issue_server
                 systemctl -q is-active humint-api.service && systemctl restart humint-api.service || true ;;
    fingerprint) fingerprint ;;
    enabled)     tls_on ;;
    *) echo "usage: humint-tls.sh {ensure [--restart]|renew|fingerprint|enabled}" >&2; exit 2 ;;
esac
