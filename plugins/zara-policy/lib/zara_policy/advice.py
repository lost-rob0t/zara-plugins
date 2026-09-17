"""Transient model guidance assembled only from trusted policy advice."""

from typing import Any, Callable
from .client import MAX_TEXT_CHARS, clean_advice

TAG = 'zara-policy-advice-v1'
GUIDANCE = (
    'Output-quality advice: before finalizing a substantive answer, you may call '
    'policy_advice once with your draft. Review matches against actual tool results '
    'and sources; a phrase match is not proof of failure and no matches is not '
    'verification. Preserve justified uncertainty, legitimate refusals and tool '
    'approvals. Do not invent successful actions or start unbounded rewrite loops.'
)


def owned(message: Any) -> bool:
    return (getattr(message, 'type', None) == 'system' and
            getattr(message, 'additional_kwargs', {}).get(TAG) is True)


def remove_advice(messages: list[Any]) -> list[Any]:
    return [message for message in messages if not owned(message)]


def previous_output(messages: list[Any]) -> str:
    for message in reversed(messages):
        if getattr(message, 'type', None) != 'ai' or getattr(message, 'tool_calls', None):
            continue
        content = getattr(message, 'content', '')
        if isinstance(content, str):
            return content[:MAX_TEXT_CHARS + 1]
        if isinstance(content, list):
            text = ''
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text' and isinstance(block.get('text'), str):
                    remaining = MAX_TEXT_CHARS + 1 - len(text)
                    text += block['text'][:remaining]
                    if len(text) > MAX_TEXT_CHARS:
                        break
            return text
    return ''


def prepare_messages(messages: list[Any], report: dict[str, Any],
                     make_message: Callable[..., Any]) -> list[Any]:
    clean = remove_advice(messages)
    if report.get('status') == 'disabled':
        return clean
    content = GUIDANCE
    advice = clean_advice(report)
    if report.get('status') != 'ok':
        content += '\nPolicy review is unavailable; do not treat this as a clean check.'
    elif advice:
        content += '\nReview reminders from the previous completed assistant answer:\n'
        content += '\n'.join(f'- {text}' for text in advice[:8])
    entry = make_message(content=content, type='system', id=TAG, additional_kwargs={TAG: True})
    index = 1 if clean and getattr(clean[0], 'type', None) == 'system' else 0
    clean.insert(index, entry)
    return clean
