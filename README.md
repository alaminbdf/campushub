# CampusHub — Centralized Campus Service Management System

> **Academic Capstone Prototype** modelled around Daffodil International University (DIU). This project uses clearly labelled synthetic prototype data and is **not** an institutionally approved DIU production system. Locker registration and management are explicitly excluded per project scope.

**Team & Maintainers**
- **Abdullah Al Shahriar Shobuj** ([@Shahriar-786](https://github.com/Shahriar-786)) — Library Domain, Concurrency & Reservation Engine, Mandatory ML Demand Forecasting
- **Md Alamin** ([@alaminbdf](https://github.com/alaminbdf)) — Core Foundation, Custom User & 9-Role RBAC, Audit & Notifications, Lost & Found, Facility Ticketing, CI/CD & Free Hosting

---

## 1. Architecture & Approved Decisions (ADRs)
- **ADR-001 (`docs/decisions/ADR-001-architecture-choice.md`):** Django 5.2 LTS + Python 3.13 modular monolith (11 Django apps), PostgreSQL, Django Templates + HTMX + Bootstrap 5, Chart.js, pandas + scikit-learn.
- **ADR-002 (`docs/decisions/ADR-002-hosting-choice.md`):** $0 Free Hosting via **Render Free Web Service** (Singapore region) + **Neon Free PostgreSQL** (serverless Postgres, 1 GB storage, no 30-day DB expiry).
- **ADR-003 (`docs/decisions/ADR-003-library-policy-decisions.md`):** Configurable prototype defaults stored in `BookingPolicyVersion` (seat-level selection inside zones, `Asia/Dhaka` operational day, max 2 consecutive sessions, no second booking same day, all-or-nothing group consent with 30-minute expiry, 15-minute check-in grace period).

---

## 2. Role-Based Usage Guide (All 9 Operational Roles)

After seeding demo data (`python manage.py seed_demo_data`), sign in at `/accounts/login/` using any of the 9 role accounts below (all demo passwords: **`CampusHub@2026`**):

| Role | Demo Account ID | Where to Go & What You Can Do |
|---|---|---|
| **1. Student** | `DIU-STU-001` & `DIU-STU-002` | Browse live seat availability (`/library/availability/`), create individual or group bookings (`/reservations/book/`), accept/decline group invitations (`/reservations/my/`), check in, submit Lost & Found reports/claims (`/lost-found/`), and report Facility/Equipment tickets (`/facilities/`). Use both accounts to test group consent and anti-proxy (`A↔B`) loophole blocking. |
| **2. Library Staff** | `DIU-LIB-001` | View daily reservations, perform staff check-ins, run the transactional no-show release sweep (`/reservations/staff/operations/`), and create temporary zone/seat closures (`/library/closures/`). |
| **3. Library Supervisor** | `DIU-SUP-001` | Everything Library Staff can do, plus audited supervisor overrides (mandatory written reason), re-running the ML demand forecast pipeline (`/forecasting/`), and viewing library-scoped audit logs (`/audit/`). |
| **4. Lost & Found Reviewer** | `DIU-LFR-001` | Screen submitted reports, view restricted `private_details`, approve/reject/escalate ownership claims, and record chain-of-custody handovers before closing cases (`/lost-found/`). |
| **5. Security Officer** | `DIU-SEC-001` | View **only** disputed or suspicious Lost & Found cases explicitly escalated and assigned to them, and assist with verified handovers (`/lost-found/`). |
| **6. IT Staff** | `DIU-IT-001` | Triage, work on, add timestamped logs, escalate, and resolve tickets strictly in the **IT Equipment / Network** queue (`/facilities/`), plus inspect operational audit trails (`/audit/`). |
| **7. Utility Staff** | `DIU-UTL-001` | Triage, work on, add maintenance notes, resolve (with mandatory completion note), and reopen tickets strictly in the **Utility / Maintenance** queue (`/facilities/`). |
| **8. Management Officer** | `DIU-MGT-001` | View aggregate cross-module KPIs on the home dashboard (`/`), inspect ML demand vs. capacity forecasts (`/forecasting/`), and oversee facility tickets and audit summaries without exposing unnecessary personal data. |
| **9. System Administrator** | `DIU-ADM-001` | Manage user accounts and role assignments (`/accounts/admin/users/` — with self-escalation and last-admin lockout guards), configure system settings, and inspect full immutable audit logs (`/audit/`). |

---




## 3. How to Contribute (Two-Developer Protected-`main` Workflow)

1. Never push directly to `main`. Create a short-lived branch (`feature/<issue>-short-name` or `fix/<issue>-short-name`).
2. Follow `SEQUENTIAL_COMMIT_GUIDE.md` so **Abdullah Al Shahriar Shobuj (`Shahriar-786`)** and **Md Alamin (`alaminbdf`)** alternate commits cleanly across their respective modules.
3. Run `ruff check .` and `pytest -q` before opening a Pull Request using `.github/PULL_REQUEST_TEMPLATE.md`.
4. Every PR must pass GitHub Actions CI (PostgreSQL 17 tests, migration check, lint) and receive 1 review from the other teammate before squash-merging.
5. Update `CONTRIBUTION_JOURNAL.md` whenever a new feature or fix is merged.
