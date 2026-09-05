from __future__ import annotations


def inspection_context(
    *,
    display_name: str,
    content: str,
    content_available: bool,
) -> str:
    name = display_name.strip() or "Discord user"
    if not content_available:
        return (
            f"Inspect this Discord message from {name}. "
            "content_available=false. The privileged Discord Message Content "
            "intent is unavailable, so only metadata-level reasoning is valid. "
            "Do not claim the message body was inspected."
        )

    body = content.strip()
    if not body:
        return (
            f"Inspect this Discord message from {name}. "
            "content_available=true. The message body is empty."
        )
    return (
        f"Inspect this Discord message from {name}. content_available=true. "
        f"They said: {body}"
    )
