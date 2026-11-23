from __future__ import annotations

from datetime import date, time, timedelta
from django.core.management.base import BaseCommand

from apps.accounts.models import OperationalRole, User
from apps.facilities.models import FacilityTicket, TicketTransition
from apps.forecasting.ml_pipeline import run_demand_forecast
from apps.forecasting.models import ForecastRun
from apps.library.models import BookingPolicy, LibrarySeat, LibrarySession, LibraryZone
from apps.lost_found.models import LostFoundReport, PotentialMatch


DEMO_USERS = [
    ("student1", "STU-2026-001", "Alamin (Student)", OperationalRole.STUDENT),
    ("student2", "STU-2026-002", "Nadia (Student)", OperationalRole.STUDENT),
    ("student3", "STU-2026-003", "Rafiq (Student)", OperationalRole.STUDENT),
    ("libstaff", "LIB-STAFF-01", "Karim (Library Staff)", OperationalRole.LIBRARY_STAFF),
    ("libsuper", "LIB-SUP-01", "Farhana (Library Supervisor)", OperationalRole.LIBRARY_SUPERVISOR),
    ("lfreviewer", "LF-REV-01", "Tarek (L&F Reviewer)", OperationalRole.LF_REVIEWER),
    ("security", "SEC-OFF-01", "Major Hasan (Security Officer)", OperationalRole.SECURITY_OFFICER),
    ("itstaff", "IT-STAFF-01", "Sajib (IT Staff)", OperationalRole.IT_STAFF),
    ("utility", "UT-STAFF-01", "Mizan (Utility Staff)", OperationalRole.UTILITY_STAFF),
    ("manager", "MGT-OFF-01", "Dr. Rahman (Management Officer)", OperationalRole.MANAGEMENT_OFFICER),
    ("sysadmin", "ADM-SYS-01", "System Administrator", OperationalRole.SYSTEM_ADMIN),
]

SESSIONS_TEMPLATE = [
    (1, "Slot 1 (09:00-11:00)", time(9, 0), time(11, 0)),
    (2, "Slot 2 (11:00-13:00)", time(11, 0), time(13, 0)),
    (3, "Slot 3 (14:00-16:00)", time(14, 0), time(16, 0)),
    (4, "Slot 4 (16:00-18:00)", time(16, 0), time(18, 0)),
]


class Command(BaseCommand):
    help = "Seeds labeled synthetic prototype data for all 9 CampusHub operational roles and modules."

    def handle(self, *args, **options) -> None:
        users: dict[str, User] = {}
        for username, inst_id, full_name, role in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "institutional_id": inst_id,
                    "first_name": full_name,
                    "email": f"{username}@campushub.prototype.local",
                    "role": role,
                    "is_staff": role == OperationalRole.SYSTEM_ADMIN,
                    "is_superuser": role == OperationalRole.SYSTEM_ADMIN,
                },
            )
            if created:
                user.set_password("CampusHub@2026")
                user.save()
            users[username] = user

        BookingPolicy.get_active()

        quiet_zone, _ = LibraryZone.objects.get_or_create(name="Quiet Study Zone", defaults={"floor_no": 2})
        collab_zone, _ = LibraryZone.objects.get_or_create(name="Group Study Zone", defaults={"floor_no": 3})

        for idx in range(1, 7):
            LibrarySeat.objects.get_or_create(seat_code=f"Q-20{idx}", defaults={"zone": quiet_zone})
        for idx in range(1, 7):
            LibrarySeat.objects.get_or_create(seat_code=f"G-30{idx}", defaults={"zone": collab_zone})

        today = date.today()
        for offset in range(3):
            target_date = today + timedelta(days=offset)
            for slot_order, label, start_t, end_t in SESSIONS_TEMPLATE:
                LibrarySession.objects.get_or_create(
                    session_date=target_date,
                    slot_order=slot_order,
                    defaults={"label": label, "start_time": start_t, "end_time": end_t},
                )

        if not LostFoundReport.objects.exists():
            lost = LostFoundReport.objects.create(
                reporter=users["student1"],
                report_type=LostFoundReport.ReportType.LOST,
                item_category="Electronics",
                public_summary="Black scientific calculator lost near Floor 2",
                private_details="Casio fx-991EX with scratched initials 'AA' on back cover.",
                location="Central Library Floor 2",
                status=LostFoundReport.Status.ACTIVE,
            )
            found = LostFoundReport.objects.create(
                reporter=users["student2"],
                report_type=LostFoundReport.ReportType.FOUND,
                item_category="Electronics",
                public_summary="Black scientific calculator found on study desk",
                private_details="Casio fx-991EX with scratched initials 'AA' on battery lid.",
                location="Quiet Study Zone Desk Q-202",
                status=LostFoundReport.Status.ACTIVE,
            )
            PotentialMatch.objects.create(
                lost_report=lost,
                found_report=found,
                rationale="Category and Floor 2 location match (UNVERIFIED lead — ownership proof required).",
            )

        if not FacilityTicket.objects.exists():
            t1 = FacilityTicket.objects.create(
                reporter=users["student1"],
                issue_type=FacilityTicket.IssueType.EQUIPMENT,
                category="Projector / AV",
                location="Academic Building Room 405",
                description="Classroom projector flickers and loses HDMI signal every 5 minutes.",
                priority=FacilityTicket.Priority.HIGH,
                status=FacilityTicket.Status.ASSIGNED,
                assigned_to=users["itstaff"],
            )
            TicketTransition.objects.create(
                ticket=t1,
                from_status="SUBMITTED",
                to_status="ASSIGNED",
                actor=users["manager"],
                note="Assigned to IT Staff for HDMI port inspection.",
            )
            t2 = FacilityTicket.objects.create(
                reporter=users["student2"],
                issue_type=FacilityTicket.IssueType.FACILITY,
                category="Electrical / AC",
                location="Library Floor 3 West Wing",
                description="Air conditioner unit 2 is leaking condensation near seat G-304.",
                priority=FacilityTicket.Priority.MEDIUM,
                status=FacilityTicket.Status.SUBMITTED,
            )
            TicketTransition.objects.create(
                ticket=t2,
                from_status="NEW",
                to_status="SUBMITTED",
                actor=users["student2"],
                note="Initial student submission.",
            )

        if not ForecastRun.objects.exists():
            run_demand_forecast(actor=users["sysadmin"], horizon_days=3)

        self.stdout.write(
            self.style.SUCCESS(
                "CampusHub synthetic demo data seeded! All 9 role accounts created (Password: CampusHub@2026)."
            )
        )