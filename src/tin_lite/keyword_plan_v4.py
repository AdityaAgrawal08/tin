"""Require the actual product capability, not a hypothetical adjacent product."""

from tin_lite import keyword_plan_v3 as v3

POLICY = {
    **v3.POLICY,
    "version": "keyword-plan-v4",
    "buyer_fit": "explicit-capability-and-complete-intent.v1",
}
INSTRUCTIONS = {
    **v3.INSTRUCTIONS,
    "triage": v3.INSTRUCTIONS["triage"]
    + """
Capability boundary: buyer_context establishes what this product actually does. Audit findings,
rankings, snippets and seed proposals do not establish additional product capabilities.
Read the WHOLE query, including qualifiers. A shared underlying API or transport is insufficient:
an email delivery API does not establish a CRM, an identity-verification service, or healthcare
compliance. A product's transport cannot by itself satisfy searches for managed authentication,
special certifications, unrelated platform tokens, or another platform's distinct API.
Label a query wrong_buyer when it asks for a different solution, or unclear when a necessary
specialized capability is not established. Do not label these direct or adjacent merely because
someone could build a different product on top of this API. Adjacent means a nearby audience or
use of an ESTABLISHED capability, not a hypothetical feature expansion. Explicit niche buyer
problems remain direct even if the search database has no volume for them.""",
    "review": v3.INSTRUCTIONS["review"]
    + """
Apply the same capability boundary again: buyer_context is the product contract. Exclude an
intent needing an unstated specialized capability, certification, or different platform API,
even when screening incorrectly marked it direct. Do not recommend such a group conditionally
with 'confirm whether we support this' in evidence_needed. That field verifies implementation
details and original evidence WITHIN an already supported intent; it cannot rescue an invented
product fit. API transport alone does not imply managed verification or regulated compliance.
Prioritize the product's distinctive stated buyer tasks and integrations over generic category
volume. Explicit niche integrations can be high priority with unknown volume. Order groups by
relative priority and strength of buyer fit, with the clearest core opportunities first.
Keep each group's title, primary, members and page approach consistent. Separate different
channels or platform APIs when they need different implementation answers; do not call one
channel another merely because both send messages. Do not lump every language, SDK and channel
into a single implementation group unless one coherent page could actually answer that intent.
Check these conditions before assigning slots; exclude doubtful members instead of stretching
the group. Complete, concise English sentences are still required.""",
}
SCHEMAS = v3.SCHEMAS
