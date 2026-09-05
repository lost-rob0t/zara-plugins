from __future__ import annotations

import re


class ContactsError(RuntimeError):
    pass


_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE = re.compile(r"^\+[1-9][0-9]{6,14}$")


class ContactsDomain:
    def __init__(self, backend, *, max_results: int = 50) -> None:
        if not 1 <= int(max_results) <= 200:
            raise ContactsError("max_results is out of range")
        self.backend = backend
        self.max_results = int(max_results)

    @staticmethod
    def _text(value, name, limit=512):
        if not isinstance(value, str) or not value.strip():
            raise ContactsError(f"{name} must be a non-empty string")
        if len(value.encode("utf-8")) > limit or any(ord(ch) < 0x20 for ch in value):
            raise ContactsError(f"{name} is invalid")
        return value

    @classmethod
    def _list(cls, values, name, limit=64, item_limit=512):
        if not isinstance(values, list) or len(values) > limit:
            raise ContactsError(f"{name} are invalid")
        normalized = [cls._text(value, name[:-1] if name.endswith("s") else name, item_limit) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ContactsError(f"{name} contain duplicates")
        return normalized

    @classmethod
    def normalize_contact(cls, contact):
        if not isinstance(contact, dict):
            raise ContactsError("contact must be an object")
        required = {"display_name", "aliases", "emails", "phones", "organizations", "handles", "sources"}
        if not required.issubset(contact):
            raise ContactsError("contact is missing required fields")
        contact_id = contact.get("contact_id")
        if contact_id is not None:
            contact_id = cls._text(contact_id, "contact id", 256)
        aliases = cls._list(contact["aliases"], "aliases", 128, 256)
        emails = cls._list(contact["emails"], "emails", 64, 320)
        if any(not _EMAIL.fullmatch(email) for email in emails):
            raise ContactsError("email address is invalid")
        phones = cls._list(contact["phones"], "phones", 64, 32)
        if any(not _PHONE.fullmatch(phone) for phone in phones):
            raise ContactsError("phone number is invalid")
        organizations = contact["organizations"]
        if not isinstance(organizations, list) or len(organizations) > 64:
            raise ContactsError("organizations are invalid")
        normalized_orgs = []
        for item in organizations:
            if not isinstance(item, dict) or set(item) - {"name", "role"} or "name" not in item:
                raise ContactsError("organization is invalid")
            normalized_orgs.append({"name": cls._text(item["name"], "organization", 256), "role": None if item.get("role") is None else cls._text(item["role"], "role", 256)})
        handles = contact["handles"]
        if not isinstance(handles, list) or len(handles) > 128:
            raise ContactsError("handles are invalid")
        normalized_handles = []
        seen_handles = set()
        for item in handles:
            if not isinstance(item, dict) or set(item) != {"provider", "value"}:
                raise ContactsError("handle is invalid")
            pair = (cls._text(item["provider"], "provider", 128), cls._text(item["value"], "handle", 320))
            if pair in seen_handles:
                raise ContactsError("handles contain duplicates")
            seen_handles.add(pair)
            normalized_handles.append({"provider": pair[0], "value": pair[1]})
        sources = contact["sources"]
        if not isinstance(sources, list) or len(sources) > 128:
            raise ContactsError("sources are invalid")
        normalized_sources = []
        for item in sources:
            if not isinstance(item, dict) or set(item) != {"provider", "record_id", "confidence"}:
                raise ContactsError("source is invalid")
            confidence = float(item["confidence"])
            if not 0.0 <= confidence <= 1.0:
                raise ContactsError("source confidence is out of range")
            normalized_sources.append({"provider": cls._text(item["provider"], "source provider", 128), "record_id": cls._text(item["record_id"], "source record id", 256), "confidence": confidence})
        return {
            "contact_id": contact_id,
            "display_name": cls._text(contact["display_name"], "display name", 512),
            "aliases": aliases,
            "emails": emails,
            "phones": phones,
            "organizations": normalized_orgs,
            "handles": normalized_handles,
            "sources": normalized_sources,
        }

    def search(self, query, *, limit=None):
        query = self._text(query, "query", 512)
        bounded = min(self.max_results, self.max_results if limit is None else int(limit))
        if bounded < 1:
            raise ContactsError("result limit is invalid")
        values = self.backend.search_contacts(query, bounded)
        if not isinstance(values, list):
            raise ContactsError("contacts backend returned invalid search results")
        return [self.normalize_contact(value) for value in values[:bounded]]

    def get(self, contact_id):
        contact_id = self._text(contact_id, "contact id", 256)
        value = self.backend.get_contact(contact_id)
        return None if value is None else self.normalize_contact(value)

    @staticmethod
    def _recipient(contact, channel):
        if channel == "email":
            return None if not contact["emails"] else {"channel": "email", "value": contact["emails"][0]}
        if channel == "phone":
            return None if not contact["phones"] else {"channel": "phone", "value": contact["phones"][0]}
        matches = [item for item in contact["handles"] if item["provider"] == channel]
        return None if not matches else {"channel": channel, "value": matches[0]["value"]}

    def resolve(self, query, *, channel):
        channel = self._text(channel, "channel", 64)
        candidates = self.search(query)
        exact = [c for c in candidates if c["display_name"].casefold() == query.casefold()]
        if len(exact) == 1:
            candidates = exact
        if len(candidates) > 1:
            return {"status": "ambiguous", "candidates": candidates}
        if not candidates:
            return {"status": "not_found", "candidates": []}
        contact = candidates[0]
        recipient = self._recipient(contact, channel)
        if recipient is None:
            return {"status": "unavailable", "contact": contact, "channel": channel}
        return {"status": "resolved", "contact": contact, "recipient": recipient}

    def create(self, contact):
        candidate = self.normalize_contact({"contact_id": None, **contact})
        candidate.pop("contact_id")
        evidence = self.backend.create_contact(candidate)
        accepted = isinstance(evidence, dict) and bool(evidence.get("accepted"))
        observed = self.get(evidence.get("contact_id")) if accepted and evidence.get("contact_id") else None
        verified = accepted and observed is not None
        return {"status": "verified" if verified else "verification_failed", "accepted": accepted, "verified": verified, "contact": observed, "evidence": evidence}

    def update(self, contact_id, patch):
        contact_id = self._text(contact_id, "contact id", 256)
        if not isinstance(patch, dict) or not patch:
            raise ContactsError("patch must be a non-empty object")
        allowed = {"display_name", "aliases", "emails", "phones", "organizations", "handles", "sources"}
        if set(patch) - allowed:
            raise ContactsError("patch contains unsupported fields")
        current = self.get(contact_id)
        if current is None:
            raise ContactsError("contact does not exist")
        merged = dict(current)
        merged.update(patch)
        expected = self.normalize_contact(merged)
        evidence = self.backend.update_contact(contact_id, patch)
        accepted = isinstance(evidence, dict) and bool(evidence.get("accepted"))
        observed = self.get(contact_id) if accepted else current
        verified = accepted and observed == expected
        return {"status": "verified" if verified else "verification_failed", "accepted": accepted, "verified": verified, "contact": observed, "evidence": evidence}
