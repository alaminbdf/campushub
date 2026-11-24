# CampusHub Engineering Contribution Journal

This engineering journal records the exact module ownership, architectural decisions, and code contributions of both capstone developers across the implementation lifecycle of **CampusHub**.

**Project Team**
- **Developer A:** Abdullah Al Shahriar Shobuj (`@Shahriar-786`)
- **Developer B:** Md Alamin (`@alaminbdf`)

---

## Entry 01 — Governance, ADRs & Project Scaffold
- **Contributor:** Md Alamin (`@alaminbdf`)
- **Reviewed By:** Abdullah Al Shahriar Shobuj (`@Shahriar-786`)
- **Code & Files Owned:**
  - `config/settings.py`, `config/urls.py`, `config/wsgi.py`, `config/asgi.py`, `manage.py`
  - `docs/decisions/ADR-001-architecture-choice.md`, `ADR-002-hosting-choice.md`, `ADR-003-library-policy-decisions.md`
  - `Dockerfile`, `compose.yaml`, `render.yaml`, `build.sh`, `requirements.txt`, `pyproject.toml`, `.env.example`, `.gitignore`
  - `.github/workflows/ci.yml`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/dependabot.yml`
- **Engineering Notes:** Established the Django 5.2 LTS modular monolith layout, PostgreSQL 17 Docker Compose environment, Render + Neon free-tier deployment blueprint, and automated GitHub Actions CI pipeline.

---

## Entry 02 — Custom User Identity, 9-Role RBAC, Audit Trail & Notifications
- **Contributor:** Md Alamin (`@alaminbdf`)
- **Reviewed By:** Abdullah Al Shahriar Shobuj (`@Shahriar-786`)
- **Code & Files Owned:**
  - `apps/core/` (`TimeStampedUUIDModel`, `SystemSetting`, `RequestCorrelationMiddleware`, `/health/` endpoint)
  - `apps/accounts/` (Custom UUID `User` with normalized `institutional_id`, 9 operational `RoleCode` choices, `UserRole` effective dating, session-rotating login/logout, self-escalation & last-admin lockout guards)
  - `apps/access_control/` (Deny-by-default `@require_roles` decorator and role context processor)
  - `apps/audit/` (Append-only `AuditEvent` blocking `.save()` updates and `.delete()` at model level)
  - `apps/notifications/` (`NotificationOutbox` transactional outbox with deduplication key)
- **Engineering Notes:** Separated operational roles from the Development Team stakeholder and ensured UI navigation never acts as the security boundary—every endpoint enforces server-side RBAC.

---

## Entry 03 — Library Inventory, Closures & Configurable Policy Engine
- **Contributor:** Abdullah Al Shahriar Shobuj (`@Shahriar-786`)
- **Reviewed By:** Md Alamin (`@alaminbdf`)
- **Code & Files Owned:**
  - `apps/library/models.py` (`LibraryZone`, `LibrarySeat`, `LibrarySession`, `ZoneClosure`, `SeatClosure`, `BookingPolicyVersion`)
  - `apps/library/views.py`, `apps/library/urls.py`
  - `templates/library/availability.html`, `templates/library/manage_closures.html`
- **Engineering Notes:** Implemented live seat discovery by date/zone/session while keeping ML demand estimates visually and semantically separate from live capacity. Stored ADR-003 rules in `BookingPolicyVersion` so no prototype default is mistaken for hard-coded institutional policy.

---

## Entry 04 — Reservation Core, Anti-Proxy Controls & Corrected PostgreSQL Concurrency Protocol
- **Contributor:** Abdullah Al Shahriar Shobuj (`@Shahriar-786`)
- **Reviewed By:** Md Alamin (`@alaminbdf`)
- **Code & Files Owned:**
  - `apps/reservations/models.py` (`Reservation`, `ReservationAttendee`, `AttendeeSessionAllocation` with partial unique constraints, `CheckIn`, `ReservationTransition`)
  - `apps/reservations/services.py` (`create_reservation`, `respond_to_invitation`, `cancel_reservation`, `record_checkin`, `release_no_shows`, `apply_supervisor_override`)
  - `apps/reservations/views.py`, `apps/reservations/urls.py`
  - `templates/reservations/my_reservations.html`, `create_booking.html`, `staff_operations.html`
- **Engineering Notes:** Implemented the exact locking sequence from `CampusHub_Final_Engineering_Corrections.docx`: inside `transaction.atomic()`, attendee `User` identity rows are locked in ascending UUID order *first*, followed by `LibrarySession` and `LibrarySeat` rows, before re-reading all active attendee allocations across all reservation creators. This closes phantom-row races, proxy booking, reciprocal `A↔B` limit bypasses, and last-seat overbooking.

---

## Entry 05 — Mandatory ML Library Demand Forecasting Pipeline
- **Contributor:** Abdullah Al Shahriar Shobuj (`@Shahriar-786`)
- **Reviewed By:** Md Alamin (`@alaminbdf`)
- **Code & Files Owned:**
  - `apps/forecasting/models.py` (`ForecastDatasetVersion`, `ForecastModelVersion`, `ForecastRun`, `ForecastMetric`, `ForecastValue`)
  - `apps/forecasting/pipeline.py` (Synthetic DIU occupancy generator, strict chronological 80/20 time-aware split, naive weekday+session baseline vs. `scikit-learn GradientBoostingRegressor`, MAE/RMSE evaluation)
  - `apps/forecasting/services.py`, `apps/forecasting/views.py`, `apps/forecasting/urls.py`
  - `templates/forecasting/dashboard.html` (Chart.js Predicted Demand vs. Configured Capacity chart with caveat banner)
- **Engineering Notes:** Guaranteed zero future-data leakage via time-ordered splitting and attached explicit synthetic-data provenance, model version, training window, and timestamp metadata to every published forecast.

---

## Entry 06 — Lost & Found Verification & Chain-of-Custody Workflow
- **Contributor:** Md Alamin (`@alaminbdf`)
- **Reviewed By:** Abdullah Al Shahriar Shobuj (`@Shahriar-786`)
- **Code & Files Owned:**
  - `apps/lost_found/models.py` (`LostFoundReport` splitting `public_description` and `private_details`, unverified `PotentialMatch`, `OwnershipClaim`, `ItemHandover`, `LostFoundTransition`)
  - `apps/lost_found/services.py`, `apps/lost_found/views.py`, `apps/lost_found/urls.py`
  - `templates/lost_found/list.html`, `templates/lost_found/detail.html`
- **Engineering Notes:** Enforced that a `PotentialMatch` never proves ownership (`is_verified_ownership=False`), restricted `Security Officer` visibility strictly to assigned escalated claims, and blocked case closure until an approved claim has a recorded `ItemHandover`.

---

## Entry 07 — Facility & Equipment Issue Ticketing, Role Dashboards & Demo Seeder
- **Contributor:** Md Alamin (`@alaminbdf`)
- **Reviewed By:** Abdullah Al Shahriar Shobuj (`@Shahriar-786`)
- **Code & Files Owned:**
  - `apps/facilities/` (`FacilityTicket`, `WorkLog`, `TicketTransition`, strict state-transition guard, IT vs. Utility queue isolation, mandatory completion note on resolve)
  - `apps/dashboards/` (Role-scoped home dashboard; aggregate-only KPIs for Management Officer)
  - `apps/core/management/commands/seed_demo_data.py` (Seeds all 9 operational roles, sample seats/sessions, sample cases/tickets, and initial ML forecast)
  - `templates/base.html`, `static/css/campushub.css`, `templates/dashboards/home.html`, `templates/facilities/`, `templates/audit/`, `templates/notifications/`
- **Engineering Notes:** Unified responsive Bootstrap 5 + HTMX UI with a persistent academic prototype banner across all pages.

---

## Entry 08 — Automated Test Suite (Concurrency, RBAC, Domain & ML) & Documentation
- **Contributors:**
  - **Abdullah Al Shahriar Shobuj (`@Shahriar-786`):** `tests/unit/test_library_rules.py`, `tests/concurrency/test_reservation_concurrency.py`, `tests/unit/test_ml_forecasting.py`
  - **Md Alamin (`@alaminbdf`):** `tests/conftest.py`, `tests/authorization/test_rbac_boundaries.py`, `tests/integration/test_lost_found_and_facilities.py`, `README.md`, `CONTRIBUTION_JOURNAL.md`, `SEQUENTIAL_COMMIT_GUIDE.md`
- **Engineering Notes:** Covered every mandatory release-gate test from the blueprint: simultaneous last-seat contention, idempotent retry, reciprocal `A↔B` prevention, seat closure conflict, RBAC negative tests, append-only audit immutability, Lost & Found handover gate, Facility queue isolation, and time-aware ML evaluation.
