"""
Lenders against whom LOCs must NOT be generated because the entity is
dissolved, in administration, insolvent, or no longer trading.

Matching is case-insensitive and partial — a blocklist entry matches if it
appears anywhere in the lender name stored on the credit report.  Prefer
the most distinctive part of the name to avoid false positives.

Keep this list sorted alphabetically for easy maintenance.
Add a comment with the reason and date confirmed.
"""

_BLOCKLIST_FRAGMENTS = [
    "ADVANTAGE FINANCE",          # Advantage Finance Ltd — administration 2023
    "BLUE MOTOR FINANCE",         # Blue Motor Finance Ltd — administration Jan 2023
    "FIRST RESPONSE FINANCE",     # First Response Finance Ltd — administration 2024
    "HOME RETAIL GROUP CARD",     # Home Retail Group Card Services Ltd — dissolved after Argos card moved to Sainsbury's Bank
    "JAJA FINANCE",               # Jaja Finance Limited — administration 2023
    "KOYO FINANCE",               # Koyo Finance 1 Ltd — administration
    "MATCH THE CASH",             # Match The Cash — ceased trading
    "OAKAM",                      # Oakam 2 Ltd — administration
    "PCF BANK",                   # PCF Bank — administration 2023
    "SHOP DIRECT FINANCE",        # Shop Direct Finance Company Ltd — dissolved (Very Group restructure)
    "STARTLINE MOTOR FINANCE",    # Startline Motor Finance Ltd — administration 2024
    "THE 1ST STOP GROUP",         # The 1st Stop Group Limited — dissolved
    "1ST STOP GROUP",
]

# Normalised to upper for fast lookup
_NORMALISED = [f.upper() for f in _BLOCKLIST_FRAGMENTS]

_REASON = "No longer trading — entity dissolved or in administration. No claim can be pursued."


def is_blocked(lender_name: str) -> bool:
    """Return True if the lender is on the dissolved/insolvent blocklist."""
    upper = lender_name.upper()
    return any(fragment in upper for fragment in _NORMALISED)
