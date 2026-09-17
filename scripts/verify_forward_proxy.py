"""Test the actual Squid/nftables configuration on a disposable, offline Docker network.

Builds only tests/proxy (never the repository or local secrets). No host firewall,
cloud resource, provider login, or real metadata service is accessed.
"""

# Fixed /tmp paths refer exclusively to fresh disposable containers.
# ruff: noqa: S108
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "tin-lite-proxy-test:sec01"


def command(*args, check=True, input=None):
    result = subprocess.run(  # noqa: S603 — explicit test-owned Docker commands
        args, input=input, text=True, capture_output=True, timeout=180
    )
    if check and result.returncode:
        raise RuntimeError(f"test command failed: {result.stderr[-3000:]}")
    return result


def main():
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("Docker is required")
    command(docker, "build", "-t", IMAGE, str(ROOT / "tests/proxy"))
    prefix = "tin-lite-proxy-test-" + uuid4().hex[:10]
    proxy, origin = prefix + "-proxy", prefix + "-origin"
    containers = []

    def run(container, *args, **kwargs):
        return command(docker, "exec", "-i", container, *args, **kwargs)

    try:
        command(
            docker,
            "network",
            "create",
            "--ipv6",
            "--subnet",
            "11.231.0.0/24",
            "--subnet",
            "2001:4860:ffff::/64",
            prefix,
        )
        for name, suffix in ((proxy, "2"), (origin, "3")):
            command(
                docker,
                "run",
                "-d",
                "--name",
                name,
                "--cap-add",
                "NET_ADMIN",
                "--network",
                prefix,
                "--ip",
                "11.231.0." + suffix,
                "--ip6",
                "2001:4860:ffff::" + suffix,
                IMAGE,
            )
            containers.append(name)
            # No route to the Internet; only the controlled fixture routes below.
            run(name, "ip", "route", "del", "default", check=False)
            run(name, "ip", "-6", "route", "del", "default", check=False)
            run(
                name,
                "mkdir",
                "-p",
                "/etc/tin-lite-proxy/tls",
                "/run/tin-lite-proxy",
                "/var/lib/tin-lite-proxy-grants",
                "/usr/local/lib/tin-lite",
            )
            command(docker, "cp", str(ROOT / "tests/proxy/origin.py"), name + ":/origin.py")
        run(
            proxy,
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=proxy.test",
            "-addext",
            "subjectAltName=DNS:proxy.test,DNS:public.test",
            "-keyout",
            "/etc/tin-lite-proxy/tls/privkey.pem",
            "-out",
            "/etc/tin-lite-proxy/tls/fullchain.pem",
        )
        with tempfile.TemporaryDirectory() as temporary:
            command(docker, "cp", proxy + ":/etc/tin-lite-proxy/tls/.", temporary)
            command(docker, "cp", temporary + "/.", origin + ":/etc/tin-lite-proxy/tls/")
        for name in containers:
            command(docker, "exec", "-d", name, "python3", "/origin.py")
        # These addresses exist only in this offline test network.
        internal4 = ("10.23.0.3", "169.254.169.254", "100.64.0.3", "192.0.2.3", "11.231.0.9")
        for address in internal4:
            run(origin, "ip", "addr", "add", address + "/32", "dev", "eth0")
            run(proxy, "ip", "route", "add", address + "/32", "via", "11.231.0.3")
        run(origin, "ip", "-6", "addr", "add", "fd00::3/128", "dev", "eth0")
        run(proxy, "ip", "-6", "route", "add", "fd00::3/128", "via", "2001:4860:ffff::3")
        for src, target in (
            ("infra/proxy_policy.py", "proxy_policy.py"),
            ("src/tin_lite/proxy_grants.py", "proxy_grants.py"),
        ):
            command(docker, "cp", str(ROOT / src), proxy + ":/usr/local/lib/tin-lite/" + target)
        run(
            proxy,
            "python3",
            "-c",
            "from pathlib import Path; "
            "Path('/tmp/resolvers').write_text('nameserver 127.0.0.1\\n'); "
            "Path('/tmp/dns-hosts').write_text('11.231.0.3 public.test rebind.test\\n'"
            "'10.23.0.3 private.test\\n169.254.169.254 metadata.google.internal\\n')",
        )
        command(
            docker,
            "exec",
            "-d",
            proxy,
            "dnsmasq",
            "--keep-in-foreground",
            "--no-resolv",
            "--no-hosts",
            "--addn-hosts=/tmp/dns-hosts",
            "--listen-address=127.0.0.1",
            "--bind-interfaces",
            "--pid-file=/tmp/dnsmasq.pid",
        )
        run(
            proxy,
            "python3",
            "/usr/local/lib/tin-lite/proxy_policy.py",
            "--static-ip",
            "11.231.0.9",
            "--uid",
            "13",
            "--resolv-conf",
            "/tmp/resolvers",
            "--output",
            "/etc/tin-lite-proxy",
        )
        run(
            proxy,
            "chown",
            "-R",
            "proxy:proxy",
            "/etc/tin-lite-proxy/tls",
            "/run/tin-lite-proxy",
            "/var/log/squid",
        )
        run(proxy, "chown", "1001:proxy", "/var/lib/tin-lite-proxy-grants")
        run(proxy, "chmod", "2750", "/var/lib/tin-lite-proxy-grants")
        # Independent host firewall state survives installation and reinstallation.
        run(proxy, "nft", "add", "table", "inet", "unrelated_fixture")
        for _ in range(2):
            run(proxy, "nft", "-f", "/etc/tin-lite-proxy/proxy.nft")
        run(proxy, "nft", "list", "table", "inet", "unrelated_fixture")
        # Speed up DNS cache expiry only, keeping the generated access/network
        # policy intact. A cached public address is safe until it expires.
        run(
            proxy,
            "python3",
            "-c",
            "from pathlib import Path; "
            "p=Path('/etc/tin-lite-proxy/squid.conf'); "
            "p.write_text(p.read_text() + 'positive_dns_ttl 1 seconds\\n' "
            "'negative_dns_ttl 1 seconds\\n')",
        )
        run(proxy, "squid", "-k", "parse", "-f", "/etc/tin-lite-proxy/squid.conf")
        command(
            docker,
            "exec",
            "-d",
            "-u",
            "proxy",
            proxy,
            "squid",
            "-N",
            "-f",
            "/etc/tin-lite-proxy/squid.conf",
        )
        # The client exercises the real helper and issues/deletes grants locally.
        command(docker, "cp", str(ROOT / "tests/proxy/client.py"), proxy + ":/client.py")
        for _ in range(50):
            ready = run(
                proxy,
                "python3",
                "-c",
                "import socket; socket.create_connection(('127.0.0.1',8888),.1).close()",
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.1)
        if ready.returncode:
            raise RuntimeError(run(proxy, "cat", "/var/log/squid/cache.log").stdout[-3000:])
        result = run(proxy, "python3", "/client.py", check=False)
        if result.returncode:
            diagnostic = run(proxy, "cat", "/var/log/squid/cache.log").stdout[-3000:]
            raise RuntimeError(result.stderr + diagnostic)
        print(result.stdout.strip())
        for name in containers:
            hits = run(name, "cat", "/tmp/origin-hits", check=False).stdout.splitlines()
            assert not any("forbidden" in path or "redirected" in path for path in hits), hits
        print(json.dumps({"origin_observed_forbidden_requests": 0, "status": "PASS"}))
    finally:
        for name in containers:
            command(docker, "rm", "-f", name, check=False)
        command(docker, "network", "rm", prefix, check=False)


if __name__ == "__main__":
    main()
