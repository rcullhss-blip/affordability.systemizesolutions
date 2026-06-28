# V2 — Estimated Claim Value (Sandbox)

A **completely isolated** test version of Systemize that adds an estimated
indicative claim value per lender to the affordability assessment. Built so it
can be tested and approved **without touching the live V1 stack** the firms are
piloting.

> ⚠️ V1 (`main` branch + live Vercel/Railway) is untouched and stays live.
> Nothing here shares V1's database.

---

## What V2 adds

Credit reports do **not** contain APR, so a real "APR × term" figure can't be
read from the data. Instead V2 models the **interest paid** (which is what
unaffordable-lending redress actually refunds) using an **assumed
representative APR per product type** applied to the balance over the months the
account was live, plus 8% statutory interest, capped for payday under the FCA
cost cap.

Output, on the assessment only:
- **Per in-scope lender:** `Estimated indicative redress: £X` with the assumed
  APR, product type and months shown.
- **Top of in-scope section:** `Total estimated indicative claim value: £X`.
- Everything is labelled *estimate only, subject to solicitor review*.

All of it is gated behind one env flag and is **off by default**, so the code is
dormant even if it ever merges to `main`.

### Tuning the estimate
The assumed APRs live in one place: `backend/app/analysis/claim_value.py`
(`ASSUMED_APR`). Change them there during testing — that's the single source of
truth. Figures round to the nearest £50 to read as estimates, not precise sums.

---

## Isolation model (decisions locked in)

| Layer | V1 (live) | V2 (sandbox) |
|---|---|---|
| Git branch | `main` | `v2-claim-value` |
| Frontend | live Vercel domains | **auto Vercel preview URL** for the branch |
| Backend | Railway prod | **separate Railway service** |
| Database / Redis | Railway prod | **separate Postgres + Redis** |
| Admin | live admin | V2 admin (own login, own DB) |
| Feature flag | `CLAIM_VALUE_ESTIMATE_ENABLED` unset → off | set to `true` → on |

Two fully independent systems. Test data can never reach live pilot data.

---

## Stand-up steps (cloud — needs your account access)

The code is done on the `v2-claim-value` branch. To make the sandbox live:

1. **Push the branch**
   ```
   git push -u origin v2-claim-value
   ```
   Vercel automatically builds a **preview URL** for the branch
   (e.g. `affordability-systemizesolutions-git-v2-claim-value-...vercel.app`).
   The live domains are unaffected.

2. **Create the separate Railway backend**
   - New Railway service from the same repo, set its deploy branch to
     `v2-claim-value`.
   - Add its **own** Postgres and Redis plugins (do **not** point at the V1
     database).
   - Copy env from `backend/.env.v2.example`, fill in the new DB/Redis URLs,
     and set `CLAIM_VALUE_ESTIMATE_ENABLED=true`.
   - Run migrations on the new DB.

3. **Point the V2 frontend at the V2 backend**
   - In the Vercel preview/branch settings, set
     `NEXT_PUBLIC_API_URL` to the new Railway backend URL.

4. **Test**
   - Upload sample reports to the V2 site, generate assessments, review the
     estimated claim values, tune `ASSUMED_APR` as needed.

5. **When approved**
   - Merge `v2-claim-value` → `main`. The feature stays off until
     `CLAIM_VALUE_ESTIMATE_ENABLED=true` is set on the live backend, so the
     roll-out is a single flag flip once the firms sign off.

---

## Files in this change
- `backend/app/analysis/claim_value.py` — new. Estimate logic + assumed APR table.
- `backend/app/documents/assessment_pdf.py` — renders the estimate (flag-gated).
- `backend/.env.v2.example` — env template for the V2 backend.
- `V2_CLAIM_VALUE_SANDBOX.md` — this file.
