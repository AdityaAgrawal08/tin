# Security reporting

Please report suspected vulnerabilities privately to **[hello@tin.computer](mailto:hello@tin.computer)**
with the subject **Tin security report**. This is the existing founder-monitored contact;
do not put exploit details, credentials or customer data in a public issue or pull request.

Include:

- The affected commit or deployed version, component and configuration relevant to the issue.
- Minimal reproduction steps using your own project or disposable local test resources.
- Expected behavior, observed behavior and potential impact.
- Redacted logs or a small proof of concept, if useful. Never send reusable keys, login tokens
  or another user's private files as evidence.

If you encounter unintended access to another user's data, stop testing that path and report
what happened. Do not modify, export or retain additional data to demonstrate the issue.

## Scope and expectations

Relevant areas include project authorization, credential handling, sandbox/controller
separation, run-bound grants, billing authorization, and duplicate or unauthorized publication
under retries. Review gates and integration permissions are also security boundaries.

Development currently targets `main`; there is no separate documented LTS or backport policy.
Include the exact affected revision so the report can be assessed against the current code.
This document does not promise a response deadline, bounty, completed security audit or
permission to test systems you do not own.

Self-host operators are responsible for their infrastructure, provider accounts, secret
storage, updates and network configuration. Browser workflows intentionally allow external
website access; do not assume every sandbox profile is network-isolated. Hosted billing
settings and historical authentication compatibility are not self-host defaults.

Review the exact source tree, Git refs and packaged assets before each release; never
publish private development history or unlicensed font assets. See
[source release limits](docs/feature-status.md#source-release-and-self-hosting-limits).
Contributor guidance and this reporting channel are not substitutes for a release review.
