"""
Live-run safety net.

We only have one (redacted) sample of the new Experian report format, so the
first real reports must be watched closely for anything the parser drops or the
rules engine lets slip through. This module provides:

  * audit_report()  — per-report sanity checks on the normalised schema, run as
    each report completes. Any HIGH/CRITICAL finding flags the job for spot check.
  * is_checkpoint() — True at 3, 8, 15, 25, 50 completed reports.
  * format_checkpoint() — a human-readable checkpoint summary from aggregate
    batch stats, logged at each boundary so a person can eyeball the pool.

All logic is pure/deterministic and side-effect free; deliver.py owns the DB
reads and logging. After the 5th checkpoint (50 reports) the pool is broad
enough to trust the format at scale.
"""
from __future__ import annotations

# Checkpoints during the live ramp — a person reviews the pool at each boundary.
CHECKPOINTS = (3, 8, 15, 25, 50)

# Above this share of accounts typed OTHER, the CAIS code map is probably missing
# codes for this lender population (e.g. 18/29/40/46/60 not yet mapped).
_OTHER_TYPE_THRESHOLD = 0.40

_UNNAMED_LENDERS = {"", "unknown", "redacted"}


def is_checkpoint(processed: int) -> bool:
    return processed in CHECKPOINTS


def _f(code: str, severity: str, detail: str) -> dict:
    return {"code": code, "severity": severity, "detail": detail}


def audit_report(schema: dict, lender_results: list[dict]) -> list[dict]:
    """Run per-report checks. Returns a list of findings (possibly empty).

    schema          : the normalised report (accounts/searches/defaults/_source)
    lender_results  : [{"traffic_light": ..., "lender_name": ...}, ...] for this job
    """
    findings: list[dict] = []
    accounts = schema.get("accounts") or []
    source = schema.get("_source") or "?"

    # 1. Nothing parsed — the parser produced an empty file. Most important signal.
    if not accounts:
        findings.append(_f("PARSE_EMPTY", "CRITICAL",
                           f"No accounts parsed from report (source={source}) — "
                           f"parser did not recognise or fully read this file"))
        return findings

    n = len(accounts)

    # 2. Account-type map gaps — too many OTHER means CAIS codes are unmapped.
    other = sum(1 for a in accounts if (a.get("account_type") or "OTHER").upper() == "OTHER")
    if other / n > _OTHER_TYPE_THRESHOLD:
        findings.append(_f("UNMAPPED_ACCOUNT_TYPES", "MEDIUM",
                           f"{other}/{n} accounts typed OTHER — likely unmapped CAIS "
                           f"account-type codes; payday/HP may be misgraded"))

    # 3. Missing opened_date — breaks the at-lending snapshot and adverse-at-lending scoring.
    no_open = sum(1 for a in accounts if not a.get("opened_date"))
    if no_open:
        findings.append(_f("MISSING_OPENED_DATE", "MEDIUM",
                           f"{no_open}/{n} accounts have no opened_date — "
                           f"at-lending analysis cannot anchor these"))

    # 4. Defaults without a default_date — weakens the default-registered evidence.
    def_no_date = sum(1 for a in accounts
                      if (a.get("status") or "").upper() == "DEFAULT" and not a.get("default_date"))
    if def_no_date:
        findings.append(_f("DEFAULT_NO_DATE", "MEDIUM",
                           f"{def_no_date} defaulted account(s) have no default_date"))

    # 5. Unnamed lenders — on live files supplyCompanyName should always resolve.
    unnamed = sum(1 for a in accounts if (a.get("lender") or "").strip().lower() in _UNNAMED_LENDERS)
    if unnamed:
        findings.append(_f("UNNAMED_LENDER", "MEDIUM",
                           f"{unnamed}/{n} accounts have no resolved lender name — "
                           f"LOCs cannot be addressed"))

    # 6. All-RED despite adverse markers on file — a scoring miss worth a human look.
    lights = [r.get("traffic_light") for r in (lender_results or [])]
    has_adverse = any((a.get("status") or "").upper() == "DEFAULT" for a in accounts) \
        or bool(schema.get("defaults"))
    if lights and all(l == "RED" for l in lights) and has_adverse:
        findings.append(_f("ALL_RED_WITH_ADVERSE", "MEDIUM",
                           "Every lender graded RED despite adverse markers on file — "
                           "possible scoring gap"))

    # 7. Accounts present but no financial lender analysed at all.
    if accounts and not lender_results:
        findings.append(_f("NO_FINANCIAL_LENDERS", "LOW",
                           f"{n} accounts parsed but none analysed as a financial lender "
                           f"(all mortgage/telecom/debt-purchaser?)"))

    return findings


def worst_severity(findings: list[dict]) -> str | None:
    order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
    if not findings:
        return None
    return max(findings, key=lambda f: order.get(f.get("severity", "LOW"), 0))["severity"]


def needs_spot_check(findings: list[dict]) -> bool:
    """A report is pulled for human review on any MEDIUM-or-worse finding while we
    ramp. Reused via the existing Job.spot_check_required plumbing."""
    return any(f.get("severity") in ("MEDIUM", "HIGH", "CRITICAL") for f in findings)


def format_checkpoint(batch_id: int, processed: int, agg: dict) -> str:
    """Build the checkpoint summary block from aggregate batch stats.

    agg keys (all ints unless noted):
        total, failed, green, amber, red,
        completed_no_lenders, missing_assessment, green_without_loc,
        flagged_for_review  (spot_check_required count so far)
    Returns a multi-line string; verdict is REVIEW if any red-flag stat > 0.
    """
    idx = CHECKPOINTS.index(processed) + 1 if processed in CHECKPOINTS else "?"
    concerns = []
    if agg.get("failed"):
        concerns.append(f"{agg['failed']} report(s) FAILED to process")
    if agg.get("completed_no_lenders"):
        concerns.append(f"{agg['completed_no_lenders']} completed with 0 lenders analysed")
    if agg.get("missing_assessment"):
        concerns.append(f"{agg['missing_assessment']} completed without an assessment doc")
    if agg.get("green_without_loc"):
        concerns.append(f"{agg['green_without_loc']} GREEN lender(s) with no LOC generated")
    if agg.get("flagged_for_review"):
        concerns.append(f"{agg['flagged_for_review']} report(s) auto-flagged for spot check")

    verdict = "REVIEW" if concerns else "PASS"
    lines = [
        f"===== CHECKPOINT {idx}/5  (batch {batch_id}, {processed} reports processed) =====",
        f"  grades: GREEN={agg.get('green', 0)}  AMBER={agg.get('amber', 0)}  RED={agg.get('red', 0)}"
        f"   failed={agg.get('failed', 0)}  total={agg.get('total', 0)}",
    ]
    if concerns:
        lines.append("  concerns:")
        lines += [f"    - {c}" for c in concerns]
    else:
        lines.append("  concerns: none")
    lines.append(f"  VERDICT: {verdict}"
                 + ("  — pause and review flagged jobs before continuing" if verdict == "REVIEW"
                    else "  — pool looks clean, safe to continue"))
    if processed == CHECKPOINTS[-1]:
        lines.append("  (final checkpoint — after this the format is considered proven for scale)")
    return "\n".join(lines)
