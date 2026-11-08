# Team and Alpha scope

Andrii Moroz · Artem Ankudinov · Illia Yerokhin

## Updated responsibilities

| Member | Responsible area | Implemented in the shared Alpha |
| --- | --- | --- |
| Andrii Moroz | Allocation, inventory, operations, suspension/preparation | Matching resources, transactional assignment, pool entry, pending operation workflow, power state, expiry scan, suspension and credential rotation before reuse; customer control-panel UI |
| Artem Ankudinov | Accounts, authorization, plans, orders | Registration/login/logout, session cookies/CSRF, server-side role/ownership checks, manager plan CRUD/disable, immutable order snapshots, catalogue, term selection and order UI |
| Illia Yerokhin | Test payments, renewals, support, activity | Invoice/payment records and idempotency, exactly-once 30-day renewal, ticket/message/status workflows, audit records and their UI |

Each member is responsible for reviewing their area, running the scenario and
explaining the complete request flow at the review. Database design and
integration checks are shared.

## Changes from Stage 1

1. The approved mockup includes monthly and annual initial orders. Monthly means
   30 days from allocation; annual means 12 calendar months from allocation.
   Renewals remain exactly 30 days and use the monthly price snapshotted at order
   creation. This extends Stage 1's initial 30-day-only catalogue to match the
   approved term selector.
2. The approved connection method is SSH with a username/password. No SSH-key
   setup flow is implemented. Show reveals the encrypted server password only
   to its active rental owner.
3. The Alpha demonstrates manual infrastructure work. Inventory initially uses
   documentation IPs so the full database workflow can run without purchasing
   or operating external VPS instances. Replace them through operator inventory
   entry for a real hosting demonstration.

All payments remain tests. Registration cannot grant staff roles. The operational
and support permissions remain separate. No supplier purchase, proxy service,
custom-domain billing, real payment gateway or claim about server location is
included. Prices reproduce the approved mockup and are demo configuration.

## Open risks / next work

- Real infrastructure: validate provider resale terms, availability and the
  manual assignment/preparation checklist before onboarding real customers.
  The Alpha cannot verify that a physical provider action actually happened.
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
