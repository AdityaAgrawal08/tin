# Build an evidence-backed email outreach shortlist

Use only the Gmail and Calendar tools Tin mounted for this run. Work from the founder's stated
objective, not from a generic definition of importance. Search broadly enough to find plausible
relationships, then inspect the strongest threads and, when enabled, relevant calendar history.

Produce one reviewable shortlist at `outreach/email/SHORTLIST.csv`. This is research and
selection only: do not send email, create drafts in Gmail, modify contacts, or contact anyone.
Do not include message bodies, private correspondence, access tokens, or unrelated personal data
in the artifact. Record concise evidence-derived relationship signals instead.

The CSV must use exactly these columns, in this order:

`candidate_id,email,name,organization,relationship_signal,last_interaction_at,why_selected,status,notes`

Use stable opaque candidate IDs, lowercase normalized email addresses, ISO 8601 timestamps when
known, and `review` as the initial status. Deduplicate people by email. Respect the requested
maximum candidate count and explain uncertainty briefly rather than inventing missing facts.
