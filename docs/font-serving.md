# Font serving and source distribution

The hosted shell, document reader, sign-in/up and MCP consent pages use separately
licensed FK Grotesk Neue through an optional external stylesheet, following the
same pattern as with.md. Set only on deployments licensed to use that font:

```text
TIN_LITE_PRIVATE_FONTS_STYLESHEET_URL=https://fonts.tin.computer/v1/private-fonts.css
```

No private URL is enabled by default. Self-hosts use bundled Geist Sans and Geist
Mono and require no font service, Cloudflare credential or private font. An operator
can supply their own HTTPS stylesheet defining `--brand-sans`; it loads after base
styles on every product/auth page. Failed CDN loading falls back to Geist Sans.

## Hosted Cloudflare setup

The dedicated R2 bucket `tin-private-fonts` is in the account owning `tin.computer`.
It uses the custom domain `fonts.tin.computer`, with TLS 1.2 minimum. It does not
alter with.md's bucket or its files. The versioned `v1/` prefix contains only:

- `private-fonts.css`;
- `fk-grotesk-neue-regular.woff2`;
- `fk-grotesk-neue-bold.woff2`.

The WOFF2 assets and stylesheet carry one-year immutable cache headers; publish a
new versioned prefix for changes. CORS allows GET/HEAD from `https://app.tin.computer`
only, including the anonymous cross-origin stylesheet request. Never upload keys,
font purchase receipts, environment files, or other private files to this bucket.
Cloudflare documents [public bucket custom domains](https://developers.cloudflare.com/r2/buckets/public-buckets/)
and [CORS configuration](https://developers.cloudflare.com/r2/buckets/cors/).

This is web-font delivery, not DRM: browsers must download the font, and CORS is
not an authentication boundary. It keeps font binaries out of the source release;
it does not confer font redistribution rights or replace the purchased license.

## Portable diagrams and build artifacts

Diagrams, their offline checker and SVG exports use Geist Sans/Mono, not FK.
The glyph-width and vertical metrics are regenerated from the bundled fonts.
Their source, license and upstream revision are recorded in `THIRD_PARTY_NOTICES.md`.
New sandbox builds contain these open-source fonts only. Existing private images
and old private release backups are not source-distribution artifacts.

Deploy the rebuilt isolated diagram image alongside this code: older images have
different fonts/checker hashes and must not be mixed with the new validator.
No customer diagram source is changed and no paid generation is needed to test it.

## Source distribution checks

Verify each source archive and wheel contains only the redistributable font assets
listed in THIRD_PARTY_NOTICES.md, with their licenses. Proprietary font binaries and
embedded copies must not enter Git, generated bundles or release artifacts. Existing
private deployment backups are not source-distribution artifacts. The .gitignore guard
and font tests help prevent accidental re-addition; they do not grant redistribution rights.
