"""Deterministic, provenance-preserving extraction; no model may self-verify."""
from __future__ import annotations
import re
import hashlib

# Restrict supported automatic assertions to unambiguous, quoted price values.
PRICE = re.compile(r"(?P<currency>\$|€|£|USD\s*|EUR\s*|GBP\s*)(?P<amount>\d{1,5}(?:[.,]\d{1,2})?)\s*(?:/|per\s+)(?P<period>month|mo\b|year|yr\b)", re.I)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def claims_for(text: str, fields: list[dict], snapshot_id: str) -> list[dict]:
    """No inferred facts; exact span, or explicit insufficient/unverified state."""
    result = []
    for field in fields:
        kind = field["kind"]
        hint = field.get("hint", "").lower()
        anchors = []
        if kind == "price":
            # Price extraction is intentionally strict; differences become conflicts.
            for match in list(PRICE.finditer(text))[:8]:
                amount = match.group("amount").replace(",", ".")
                period = "month" if match.group("period").lower() in ("mo", "month") else "year"
                currency = {"$":"USD", "€":"EUR", "£":"GBP"}.get(match.group("currency").strip().upper(), match.group("currency").strip().upper())
                context=text[max(0,match.start()-45):min(len(text),match.end()+85)].lower()
                if any(phrase in context for phrase in ("billed annually","annual billing","paid annually","yearly billing")):
                    billing="billed_annually"
                elif any(phrase in context for phrase in ("billed monthly","monthly billing","paid monthly")):
                    billing="billed_monthly"
                else:
                    billing="not_stated"
                anchors.append({"start":match.start(), "end":match.end(),
                                "quote":text[match.start():match.end()],
                                "value":{"amount":amount,"currency":currency,"period":period,
                                         "billing_condition":billing},
                                "stance":"supports"})
            unique = {(a["value"]["amount"],a["value"]["currency"],a["value"]["period"],
                       a["value"]["billing_condition"]) for a in anchors}
            if not anchors:
                status, value = "INSUFFICIENT", None
            elif len(unique) > 1:
                status, value = "CONFLICTED", None
            else:
                status, value = "SUPPORTED", anchors[0]["value"]
        else:
            at = text.lower().find(hint) if hint else -1
            if at < 0:
                status, value = "INSUFFICIENT", None
            else:
                start = max(0, at-64)
                end = min(len(text), at+len(hint)+160)
                anchors = [{"start":start,"end":end,"quote":text[start:end],"stance":"mentions"}]
                status, value = "NEEDS_REVIEW", text[start:end]
        result.append({"field":field["key"], "status":status,"value":value,
                       "anchors":anchors, "reason":{
                           "SUPPORTED":"Exact price amount, currency and billing period appear in source text; no independent business-terms verification.",
                           "CONFLICTED":"Multiple distinct price expressions on the same page; a plan cannot be selected safely.",
                           "INSUFFICIENT":"Field is not established by the retrieved source text.",
                           "NEEDS_REVIEW":"Source mentions the keyword but does not independently prove the feature claim."
                       }[status], "snapshot_id":snapshot_id})
    return result


def validate_anchors(text: str, anchors: list[dict]) -> None:
    for item in anchors:
        s, e = item["start"], item["end"]
        if type(s) is not int or type(e) is not int or not 0 <= s < e <= len(text):
            raise ValueError("Evidence anchor does not lie within snapshot")
        if text[s:e] != item["quote"]:
            raise ValueError("Evidence anchor quote does not match immutable source")
