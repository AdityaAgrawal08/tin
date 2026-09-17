# Untrusted project file delivery

Project files and workflow outputs are untrusted content, including canonical and
reviewed revisions. Project membership permits reading their bytes; it must not give
those bytes JavaScript access to the reader's Tin session or other projects.

## HTTP contract

The project raw-file endpoint and canonical/retained run-artifact endpoint share one
response policy. HTML, SVG, XML, PDF and unknown formats default to attachment.
Only explicitly supported inert text, raster images, audio and video may open inline.
`download=true` still forces an attachment for project files. MIME types, original
bytes, revision metadata and membership checks remain intact.

Every raw response, including the Markdown-only task-review endpoint, also has:

- `Content-Security-Policy: sandbox; default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`
- `X-Content-Type-Options: nosniff`
- `Cache-Control: private, no-store`
- `Referrer-Policy: no-referrer`

The document sandbox is defense in depth if a client displays an attachment inline.
It grants neither scripts nor the application origin. This policy applies to raw
content responses, not the trusted application shell or its packaged assets.

## Browser contract

Fetching a response and constructing a Blob does **not** preserve its HTTP policy.
The authenticated Files viewer therefore creates raw-view Blobs as UTF-8 plain text
and download Blobs as `application/octet-stream`, preserving their source bytes.
It never opens project-controlled HTML or SVG as an active application-origin Blob.

SVG previews use a base64 data URL in an image element. Image rendering disables SVG
script execution; the data URL has an opaque origin even if opened as a separate
document. A same-origin SVG Blob would lose that protection on document navigation.
Raster, audio, video and PDF previews retain their existing typed viewers. Downloads
retain the original file and filename; this is isolation, not content sanitization.

Browser behavior references: [SVG image restrictions](https://developer.mozilla.org/en-US/docs/Web/SVG/Guides/SVG_as_an_image),
[data URL origins](https://developer.mozilla.org/en-US/docs/Web/URI/Reference/Schemes/data),
and [CSP document sandbox](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/sandbox).

## Verification and release

Run `uv run pytest tests/test_raw_file_security.py` and
`npm run test:raw-file-security` after the normal dependency and Playwright setup.
CI runs both. The fixture binds only to loopback, generates a temporary signing key,
and uses real Tin routes, Clerk SDK session verification and project membership
checks over synthetic project/storage data. It does not use production credentials
or call a provider.

The Chromium regression first demonstrates successful theft of synthetic private
data through the old inline response and an ambient session cookie. It then checks
HTML/SVG/XML and retained downloads, document sandbox enforcement even with inline
disposition, plain-text Blob views, functioning SVG/PNG previews, opaque SVG document
navigation, misleading image extensions and byte-exact downloads. The API regression
checks headers, revisions, membership and unauthenticated denial.

After deployment, reload
the application to obtain its newly hashed assets, verify the raw response headers,
and check a disposable SVG preview and original download with a signed-in member.
Do not use a customer's files or a production session for an attack demonstration.
No sandbox rebuild, migration or workflow-definition change is required for this file-delivery change.
