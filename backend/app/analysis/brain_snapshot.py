"""
The slim, identity-free copy of a parsed report that survives job completion.

deliver.py used to null job.normalised_data outright once documents were in S3
(it held the raw report text and the client's identity, and bloated the jobs
table). The brain feed needs the account-level evidence, so instead we keep only
the credit data the engine scored on: no client block, no raw text, no account
numbers. The 30-day batch retention purge still removes it with the job.
"""
from app.analysis.computed_at_lending import compute_at_lending, _parse_date

_DROP_ACCOUNT_KEYS = {"account_number"}
_KEEP_TOP_LEVEL = ("_source", "accounts", "searches", "defaults", "public_records", "risk_flags")


def slim_schema(schema: dict | None) -> dict | None:
    if not schema:
        return None
    slim = {k: schema.get(k) for k in _KEEP_TOP_LEVEL if k in schema}
    slim["accounts"] = [
        {k: v for k, v in a.items() if k not in _DROP_ACCOUNT_KEYS}
        for a in (schema.get("accounts") or []) if isinstance(a, dict)
    ]
    slim["_retained"] = "slim-v1"
    return slim


def attach_at_lending(schema: dict, lender_names: list[str], analysed_types: set[str]) -> dict:
    """Re-attach the per-lender at-lending snapshot exactly as analyse.py does:
    lending date = opened_date of the lender's first in-scope account."""
    accounts = schema.get("accounts") or []
    for name in lender_names:
        accs = [a for a in accounts if a.get("lender") == name
                and (a.get("account_type") or "OTHER").upper() in analysed_types]
        if not accs:
            continue
        cal = compute_at_lending(_parse_date(accs[0].get("opened_date")), accounts,
                                 schema.get("searches") or [], schema.get("defaults") or [], name)
        for a in accs:
            a["computed_at_lending"] = cal
    return schema
