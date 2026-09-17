"""Runs inside the offline proxy fixture; all credentials here are synthetic."""

# All subprocess inputs and temporary paths belong to this disposable fixture.
# ruff: noqa: S108, S603, S607
import base64
import http.client
import json
import os
import signal
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, "/usr/local/lib/tin-lite")
from proxy_grants import proxy_grant

CERT = "/etc/tin-lite-proxy/tls/fullchain.pem"
DIRECTORY = Path("/var/lib/tin-lite-proxy-grants")
checks = 0


def curl(target, proxy=None, extra=()):
    args = [
        "curl",
        "--silent",
        "--show-error",
        "--max-time",
        "4",
        "--output",
        "/dev/null",
        "--write-out",
        "%{http_code}",
        "--noproxy",
        "",
        "--cacert",
        CERT,
        "--proxy-cacert",
        CERT,
        "--resolve",
        "proxy.test:8888:127.0.0.1",
    ]
    if proxy:
        args += ["--proxy", proxy]
    else:
        args += ["--noproxy", "*"]
    return subprocess.run(args + list(extra) + [target], capture_output=True, text=True)


def expect(target, proxy, status, extra=()):
    global checks
    result = curl(target, proxy, extra)
    assert result.stdout == str(status), (target, result.stdout, result.stderr)
    checks += 1


blocked = [
    "127.0.0.1",
    "127.1",
    "2130706433",
    "0x7f000001",
    "10.23.0.3",
    "169.254.169.254",
    "100.64.0.3",
    "192.0.2.3",
    "11.231.0.9",
    "11.231.0.2",
    "[::1]",
    "[fd00::3]",
    "[::ffff:169.254.169.254]",
    "[64:ff9b::a17:3]",
    "[2002:a17:3::1]",
    "private.test",
    "metadata.google.internal",
]
# Prove controlled internal services are reachable without the proxy fence.
for address in (
    "127.0.0.1",
    "10.23.0.3",
    "169.254.169.254",
    "100.64.0.3",
    "192.0.2.3",
    "11.231.0.9",
    "11.231.0.2",
    "[::1]",
    "[fd00::3]",
):
    expect(f"http://{address}/baseline", None, 200)

with proxy_grant(
    directory=DIRECTORY,
    proxy_url="https://proxy.test:8888",
    execution_key="synthetic-run:stage",
    sandbox_id="synthetic-sandbox",
    ttl_seconds=60,
) as url:
    expect("http://public.test/allowed", url, 200)
    expect("https://public.test/allowed-tls", url, 200)
    expect("http://11.231.0.3/allowed-literal", url, 200)
    expect("http://[2001:4860:ffff::3]/allowed-ipv6", url, 200)
    parsed = urlsplit(url)
    altered = ("A" if parsed.password[0] != "A" else "B") + parsed.password[1:]
    expect("http://public.test/forbidden-altered", url.replace(parsed.password, altered), 407)
    with proxy_grant(
        directory=DIRECTORY,
        proxy_url="https://proxy.test:8888",
        execution_key="another-run:stage",
        sandbox_id="another-sandbox",
        ttl_seconds=60,
    ) as other_url:
        expect("http://public.test/allowed-concurrent-run", other_url, 200)
    time.sleep(1.1)
    expect("http://public.test/forbidden-other-revoked", other_url, 407)
    expect("http://public.test/allowed-still-active", url, 200)
    for host in blocked:
        # Our own non-static public interface is caught at the kernel layer,
        # resulting in a gateway error; the Squid destination ACL catches others.
        for scheme in ("http", "https"):
            result = curl(
                f"{scheme}://{host}/forbidden", url, ("--header", "Metadata-Flavor: Google")
            )
            assert result.stdout in ("403", "503", "000"), (host, result.stdout, result.stderr)
            checks += 1
    expect("http://public.test:8080/forbidden-port", url, 403)
    # CONNECT to a non-TLS port must also fail.
    result = curl("https://public.test:80/forbidden-connect-port", url)
    assert result.returncode != 0
    checks += 1
    expect("http://public.test/redirect", url, 403, ("--location",))
    expect("http://public.test/forbidden-anonymous", "https://proxy.test:8888", 407)
    expect(
        "http://public.test/forbidden-legacy", "https://tinlite:old-password@proxy.test:8888", 407
    )
    expect("http://public.test/forbidden-plaintext", url.replace("https://", "http://", 1), "000")
    untrusted = subprocess.run(
        [
            "curl",
            "--silent",
            "--max-time",
            "3",
            "--noproxy",
            "",
            "--proxy",
            url,
            "--resolve",
            "proxy.test:8888:127.0.0.1",
            "http://public.test/forbidden-untrusted",
        ],
        capture_output=True,
    )
    assert untrusted.returncode == 60, untrusted.returncode
    checks += 1
    # Rebinding: the same name first resolves publicly, then to the fake metadata IP.
    expect("http://rebind.test/allowed-before-rebind", url, 200)
    hosts = Path("/tmp/dns-hosts")
    hosts.write_text(
        hosts.read_text().replace("public.test rebind.test", "public.test")
        + "169.254.169.254 rebind.test\n"
    )
    os.kill(int(Path("/tmp/dnsmasq.pid").read_text()), signal.SIGHUP)
    time.sleep(2)
    expect("http://rebind.test/forbidden-after-rebind", url, 403)
    # Credential cache TTL must not permit another request after expiry/revocation.
    parsed = urlsplit(url)
    connection = http.client.HTTPSConnection(
        "127.0.0.1", 8888, context=ssl.create_default_context(cafile=CERT)
    )
    # Authenticate the proxy by hostname even though this fixture resolves locally.
    connection.host = "proxy.test"
    connection._create_connection = lambda address, timeout, source_address: __import__(
        "socket"
    ).create_connection(("127.0.0.1", 8888), timeout)
    headers = {
        "Proxy-Authorization": "Basic "
        + base64.b64encode(f"{parsed.username}:{parsed.password}".encode()).decode()
    }
    connection.request("GET", "http://public.test/allowed-before-expiry", headers=headers)
    response = connection.getresponse()
    assert response.status == 200
    response.read()
    grant = next(DIRECTORY.iterdir())
    contents = json.loads(grant.read_text())
    contents["expires_at"] = int(time.time()) - 1
    grant.write_text(json.dumps(contents))
    time.sleep(1.1)  # Squid caches successful Basic authentication for at most one second.
    expect("http://public.test/forbidden-expired", url, 407)
    connection.request("GET", "http://public.test/forbidden-cached-auth", headers=headers)
    response = connection.getresponse()
    assert response.status == 407
    response.read()
    connection.close()
    checks += 1
expect("http://public.test/forbidden-revoked", url, 407)

# Bypass Squid entirely to prove the kernel layer independently denies sockets,
# including after a DNS change or an ACL mistake. The application user stays free.
for host, port in (
    ("127.0.0.1", 80),
    ("10.23.0.3", 80),
    ("169.254.169.254", 80),
    ("11.231.0.2", 80),
    ("11.231.0.9", 443),
    ("::1", 80),
    ("fd00::3", 443),
    ("11.231.0.3", 8080),
    ("11.231.0.3", 8000),
):
    script = (
        "import os,socket; os.setgroups([]); os.setgid(13); os.setuid(13); "
        f"socket.create_connection(({host!r}, {port}), 1).close()"
    )
    result = subprocess.run(["python3", "-c", script], capture_output=True)
    assert result.returncode != 0, (host, port)
    checks += 1
for host in ("11.231.0.3", "2001:4860:ffff::3"):
    result = subprocess.run(
        [
            "python3",
            "-c",
            "import os,socket; os.setgroups([]); os.setgid(13); os.setuid(13); "
            f"socket.create_connection(({host!r}, 80), 1).close()",
        ],
        capture_output=True,
    )
    assert result.returncode == 0, (host, result.stderr)
    checks += 1
print(json.dumps({"network_checks": checks, "tls": "verified", "grant_revocation": "verified"}))
