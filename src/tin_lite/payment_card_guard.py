"""Shared by the switchboard and the standalone sandbox runner."""

import re


def card_secrets(card: dict | None) -> tuple[str, ...]:
    if not card:
        return ()
    number = card["number"]
    return tuple(
        dict.fromkeys(
            [
                *card.values(),
                " ".join(number[i : i + 4] for i in range(0, len(number), 4)),
                "-".join(number[i : i + 4] for i in range(0, len(number), 4)),
            ]
        )
    )


def reject_card_leak(content: bytes, card: dict | None) -> None:
    if not card:
        return
    text = content.decode("utf-8", errors="replace")
    # Detect arbitrary spacing/hyphenation of the PAN as well as literal fields.
    pattern = r"[\s-]*".join(re.escape(digit) for digit in card["number"])
    if re.search(pattern, text) or any(value in text for value in card_secrets(card)):
        raise RuntimeError("procedure output contains payment details")
