Andrii Moroz Â· Artem Ankudinov Â· Illia Yerokhin

# Team and Beta scope

## Updated responsibilities

| Member | Responsible area | Current shared Beta implementation |
| --- | --- | --- |
| Andrii Moroz | Allocation, inventory, operations, suspension/preparation | Matching resources, transactional assignment, pool entry, operation completion/rejection, power state, expiry scan, suspension and credential rotation before reuse; refreshed locked operation state prevents duplicate concurrent resolution; operation lifecycle and race regression coverage |
| Artem Ankudinov | Accounts, authorization, plans, orders | Registration/login/logout, session cookies/CSRF, backend role/ownership checks, manager plan create/update/disable, immutable order snapshots, catalogue, monthly/annual selection and order UI; role access matrix and registration/session regression coverage |
| Illia Yerokhin | Test payments, renewals, support, activity | Invoice/payment records and idempotency, exactly-once 30-day renewal, Monobank sandbox checkout with stored exchange quotes and verified events, ticket/message/status workflows, role-filtered history; payment, renewal, support and webhook regression coverage |

Each member is responsible for reviewing their area, running the scenario and
explaining the complete request flow at the review. Database design and
integration checks are shared.

These are the team's ownership areas and the implementation available in the
shared repository. Each member must review and confirm their contribution
statement before submission; the table is not a claim about commit authorship.
The Beta requirements matrix, review procedure and verification record are
shared deliverables in `beta.md` and `beta-review.md`.

## Changes from Stage 1

1. The approved mockup includes monthly and annual initial orders. Monthly means
   30 days from allocation; annual means 12 calendar months from allocation.
   Renewals remain exactly 30 days and use the monthly price snapshotted at order
   creation. This extends Stage 1's initial 30-day-only catalogue to match the
   approved term selector.
2. The approved connection method is SSH with a username/password. No SSH-key
   setup flow is implemented. Show reveals the encrypted server password only
   to its active rental owner.
3. The Beta retains manual infrastructure work. Inventory initially uses
   documentation IPs so the full database workflow can run without purchasing
   or operating external VPS instances. Replace them through operator inventory
   entry for a real hosting demonstration.

All payments remain tests. Registration cannot grant staff roles. The operational
and support permissions remain separate. No supplier purchase, proxy service,
custom-domain billing, real payment gateway or claim about server location is
included. Test checkout now supports Monobank's sandbox, hosted card entry and
verified status notifications, optional saved-card automatic renewal and confirmed test refunds. These additions exercise payment reliability while keeping Stage 1 test-only payments. Prices reproduce the approved mockup and are
demo configuration.

## Open risks / next work

- Real infrastructure: validate provider resale terms, availability and the
  manual assignment/preparation checklist before onboarding real customers.
  The application cannot verify that a physical provider action happened.
- Production: require HTTPS and `COOKIE_SECURE=true`, deployment secret storage,
  encrypted backups, key-recovery procedures, and login throttling before
  exposing this local prototype publicly. Password reset/email verification
  are not implemented.
- Operations: the expiry worker runs with the app. During downtime, overdue
  rentals are picked up at the next startup. A separate supervised scheduler
  and monitoring are planned for production.
- Scale: current lists are intentionally small. Add pagination, query
  optimization and load tests before growing beyond a small initial pool.
- Annual renewal discounts and real taxes/payment fees need separate business
  decisions. The annual selector currently applies only to the initial term.
- PostgreSQL enforces uniqueness and financial/state checks. Administrative
  database access remains trusted; database-level immutable audit roles and
  protection against direct SQL edits are future deployment work.

## Payment integration provenance

Illia Yerokhin authored the payment-processing PR (original commit `8b14049`).
Integration review corrected ambiguous automatic charges, asynchronous refunds
and settlement validation, then added explicit UAH quoting after a real sandbox
check exposed Monobank conversion. These fixes and regressions were applied to
the PR branch and integrated with the existing Beta role and operation tests.
This is a shared assisted integration; each member must review the final code.
