from __future__ import annotations

from datetime import datetime


class CommsError(RuntimeError):
    pass


class CommsDomain:
    def __init__(self, providers, resolver, *, max_results: int = 50, max_body_bytes: int = 65536) -> None:
        if not isinstance(providers, dict) or not providers:
            raise CommsError("providers must be a non-empty mapping")
        if not 1 <= int(max_results) <= 200:
            raise CommsError("max_results is out of range")
        if not 256 <= int(max_body_bytes) <= 1_048_576:
            raise CommsError("max_body_bytes is out of range")
        self.providers = dict(providers)
        self.resolver = resolver
        self.max_results = int(max_results)
        self.max_body_bytes = int(max_body_bytes)

    @staticmethod
    def _text(value, name, limit=1024, *, allow_empty=False):
        if not isinstance(value, str) or (not allow_empty and not value.strip()):
            raise CommsError(f"{name} must be a string")
        if len(value.encode("utf-8")) > limit:
            raise CommsError(f"{name} exceeds byte limit")
        if any(ord(ch) < 0x20 and ch not in "\n\r\t" for ch in value):
            raise CommsError(f"{name} contains invalid control characters")
        return value

    def _provider(self, name):
        name = self._text(name, "provider", 128)
        provider = self.providers.get(name)
        if provider is None:
            raise CommsError("provider is unavailable")
        return name, provider

    def normalize_message(self, message):
        if not isinstance(message, dict):
            raise CommsError("message must be an object")
        required = {"provider", "account_id", "conversation_id", "message_id", "sender", "recipients", "timestamp", "body", "attachments", "read", "reply_to"}
        if not required.issubset(message):
            raise CommsError("message is missing required fields")
        recipients = message["recipients"]
        if not isinstance(recipients, list) or not 1 <= len(recipients) <= 128:
            raise CommsError("recipients are invalid")
        normalized_recipients = [self._text(value, "recipient", 320) for value in recipients]
        if len(set(normalized_recipients)) != len(normalized_recipients):
            raise CommsError("recipients contain duplicates")
        try:
            timestamp = datetime.fromisoformat(message["timestamp"])
        except (TypeError, ValueError) as error:
            raise CommsError("timestamp is invalid") from error
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise CommsError("timestamp must include timezone information")
        body = self._text(message["body"], "body", self.max_body_bytes, allow_empty=True)
        attachments = message["attachments"]
        if not isinstance(attachments, list) or len(attachments) > 32:
            raise CommsError("attachments are invalid")
        normalized_attachments = []
        for item in attachments:
            if not isinstance(item, dict):
                raise CommsError("attachment metadata is invalid")
            required_attachment = {"attachment_id", "name", "size", "content_type"}
            if not required_attachment.issubset(item):
                raise CommsError("attachment metadata is incomplete")
            size = int(item["size"])
            if size < 0 or size > 100 * 1024 * 1024:
                raise CommsError("attachment size is out of range")
            normalized_attachments.append({
                "attachment_id": self._text(item["attachment_id"], "attachment id", 256),
                "name": self._text(item["name"], "attachment name", 512),
                "size": size,
                "content_type": self._text(item["content_type"], "content type", 256),
            })
        reply_to = message["reply_to"]
        if reply_to is not None:
            reply_to = self._text(reply_to, "reply_to", 256)
        return {
            "provider": self._text(message["provider"], "provider", 128),
            "account_id": self._text(message["account_id"], "account id", 256),
            "conversation_id": self._text(message["conversation_id"], "conversation id", 256),
            "message_id": self._text(message["message_id"], "message id", 256),
            "sender": self._text(message["sender"], "sender", 320),
            "recipients": normalized_recipients,
            "timestamp": message["timestamp"],
            "body": body,
            "attachments": normalized_attachments,
            "read": bool(message["read"]),
            "reply_to": reply_to,
        }

    def search(self, query, *, provider=None, limit=None):
        query = self._text(query, "query", 1024)
        bounded = min(self.max_results, self.max_results if limit is None else int(limit))
        if bounded < 1:
            raise CommsError("result limit is invalid")
        selected = self.providers.items() if provider is None else [self._provider(provider)]
        results = []
        for name, adapter in selected:
            values = adapter.search(query, bounded)
            if not isinstance(values, list):
                raise CommsError(f"provider {name} returned invalid search results")
            for value in values:
                normalized = self.normalize_message(value)
                if normalized["provider"] != name:
                    raise CommsError("provider identity mismatch")
                results.append(normalized)
                if len(results) >= bounded:
                    return results
        return results

    def get(self, provider, message_id):
        provider_name, adapter = self._provider(provider)
        message_id = self._text(message_id, "message id", 256)
        value = adapter.get(message_id)
        if value is None:
            return None
        normalized = self.normalize_message(value)
        if normalized["provider"] != provider_name:
            raise CommsError("provider identity mismatch")
        return normalized

    def draft(self, *, provider, account_id, recipient_query, subject, body):
        provider_name, _ = self._provider(provider)
        account_id = self._text(account_id, "account id", 256)
        subject = self._text(subject, "subject", 1024, allow_empty=True)
        body = self._text(body, "body", self.max_body_bytes, allow_empty=True)
        resolved = self.resolver.resolve(recipient_query, "email" if provider_name == "gmail" else provider_name)
        status = resolved.get("status") if isinstance(resolved, dict) else None
        if status == "ambiguous":
            raise CommsError("recipient is ambiguous")
        if status != "resolved" or not isinstance(resolved.get("recipient"), dict):
            raise CommsError("recipient is unavailable")
        recipient = self._text(resolved["recipient"].get("value"), "recipient", 320)
        return {
            "status": "draft",
            "provider": provider_name,
            "account_id": account_id,
            "conversation_id": None,
            "recipients": [recipient],
            "subject": subject,
            "body": body,
            "reply_to": None,
        }

    def draft_reply(self, provider, message_id, body):
        original = self.get(provider, message_id)
        if original is None:
            raise CommsError("message does not exist")
        return {
            "status": "draft",
            "provider": original["provider"],
            "account_id": original["account_id"],
            "conversation_id": original["conversation_id"],
            "recipients": [original["sender"]],
            "subject": "",
            "body": self._text(body, "body", self.max_body_bytes, allow_empty=True),
            "reply_to": original["message_id"],
        }

    def send(self, draft):
        if not isinstance(draft, dict) or draft.get("status") != "draft":
            raise CommsError("send requires a draft")
        provider_name, adapter = self._provider(draft.get("provider"))
        recipients = draft.get("recipients")
        if not isinstance(recipients, list) or not recipients:
            raise CommsError("draft recipients are invalid")
        normalized = {
            "provider": provider_name,
            "account_id": self._text(draft.get("account_id"), "account id", 256),
            "conversation_id": draft.get("conversation_id"),
            "recipients": [self._text(value, "recipient", 320) for value in recipients],
            "subject": self._text(draft.get("subject", ""), "subject", 1024, allow_empty=True),
            "body": self._text(draft.get("body", ""), "body", self.max_body_bytes, allow_empty=True),
            "reply_to": draft.get("reply_to"),
        }
        evidence = adapter.send(normalized)
        accepted = isinstance(evidence, dict) and bool(evidence.get("accepted"))
        message = self.get(provider_name, evidence.get("message_id")) if accepted and evidence.get("message_id") else None
        verified = accepted and message is not None and message["provider"] == provider_name
        if verified and normalized["conversation_id"] is not None:
            verified = message["conversation_id"] == normalized["conversation_id"] and message["reply_to"] == normalized["reply_to"]
        return {
            "status": "verified" if verified else "verification_failed",
            "accepted": accepted,
            "verified": verified,
            "message": message,
            "evidence": evidence,
        }
