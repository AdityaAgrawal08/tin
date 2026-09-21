# Buyer-trust fix playbook

Use these copy-paste starters when the audit finds a gap. Prefer the smallest safe change. Do not paste secrets.

## Security headers

Static hosts (`_headers`, `vercel.json`, `netlify.toml`, or reverse proxy):

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
X-Content-Type-Options: nosniff
```

Starter Content-Security-Policy. Tighten `script-src` and `connect-src` to the hosts the site actually uses:

```
Content-Security-Policy: default-src 'self'; img-src 'self' https: data:; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'
```

Next.js (`next.config.js` headers) or Express (`helmet`) can emit the same values. Verify with one safe GET and record the exact response headers.

## security.txt

Serve at `/.well-known/security.txt` with `Content-Type: text/plain`:

```
Contact: mailto:security@example.com
Expires: 2027-01-01T00:00:00Z
Preferred-Languages: en
```

Replace the contact and expiry. Keep it to contact plus expiry unless a policy URL already exists.

## Trust surface checklist

- Footer links Privacy plus Terms on every page, including checkout.
- Contact page or footer with real address or monitored inbox, plus response expectation.
- Refunds or returns statement linked within one click of checkout.
- Cookie notice only where tracking or non-essential cookies exist; link it to Privacy.
- Checkout shows lock (HTTPS), guest option, line-item total before pay, and no mixed-content warnings.
- `/.git/HEAD` and `/.env` return 404. If either returns 200, treat as Fix now and rotate any exposed secret out of band.

## What this playbook is not

No CVE database, no dependency scan, no intrusive prober. For full CVE management use Dependabot, Snyk, or the platform patch channel. Never invent CVEs, versions, or exploitability.
