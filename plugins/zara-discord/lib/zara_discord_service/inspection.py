from __future__ import annotations


def inspection_context(
    *,
    display_name: str,
    content: str,
    content_available: bool,
    trigger_prompt: str = "",
    response_style_prompt: str = "",
) -> str:
    name = display_name.strip() or "Discord user"
    instructions = []
    trigger = trigger_prompt.strip()
    style = response_style_prompt.strip()
    if trigger:
        instructions.append(f"Inspection trigger: {trigger}")
    if style:
        instructions.append(f"Response style: {style}")
    suffix = " " + " ".join(instructions) if instructions else ""

    if not content_available:
        return (
            f"Inspect this Discord message from {name}. "
            "content_available=false. The privileged Discord Message Content "
            "intent is unavailable, so only metadata-level reasoning is valid. "
            "Do not claim the message body was inspected."
            f"{suffix}"
        )

    body = content.strip()
    if not body:
        return (
            f"Inspect this Discord message from {name}. "
            "content_available=true. The message body is empty."
            f"{suffix}"
        )
    return (
        f"Inspect this Discord message from {name}. content_available=true. "
        f"They said: {body}{suffix}"
    )
