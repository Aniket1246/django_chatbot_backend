from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from chatbot.models import Mentor, TimeSlot, BlockedDate, MentorAvailability

UK_TZ = ZoneInfo("Europe/London")


class Command(BaseCommand):
    help = "Recreate Kapil (id=14) mentor slots up to Jan 2026 safely"

    def add_arguments(self, parser):
        parser.add_argument(
            "--recreate",
            action="store_true",
            help="Delete Kapil’s existing slots before recreating them",
        )

    def handle(self, *args, **options):
        recreate = options.get("recreate", False)
        mentor_id = 14

        try:
            mentor = Mentor.objects.get(id=mentor_id)
        except Mentor.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Mentor id={mentor_id} not found."))
            return

        self.stdout.write(self.style.SUCCESS(f"Target mentor: {mentor.user.username} (id={mentor_id})"))

        if recreate:
            count = TimeSlot.objects.filter(mentor=mentor).count()
            TimeSlot.objects.filter(mentor=mentor).delete()
            self.stdout.write(self.style.WARNING(f"Deleted {count} existing slots for {mentor.user.username}"))

        today = timezone.now().date()
        end_date = datetime(2026, 1, 31).date()
        slots_created = 0
        slots_skipped = 0

        blocked_dates = set(BlockedDate.objects.filter(mentor=mentor).values_list("date", flat=True))

        current_date = today
        while current_date <= end_date:
            # Skip weekends
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue

            # Skip blocked days
            if current_date in blocked_dates:
                self.stdout.write(f"Skipping blocked date: {current_date}")
                current_date += timedelta(days=1)
                continue

            try:
                availability = MentorAvailability.objects.get(
                    mentor=mentor, date=current_date, is_active=True
                )
            except MentorAvailability.DoesNotExist:
                current_date += timedelta(days=1)
                continue

            available_slots = availability.get_available_slots()
            if not available_slots:
                current_date += timedelta(days=1)
                continue

            for slot in available_slots:
                start_str = slot["start_time"]
                end_str = slot["end_time"]

                # Parse hours/minutes safely
                def parse_time(tstr: str):
                    ts = tstr.strip().upper().replace(" ", "")
                    hour, minute = 0, 0
                    if ":" in ts:
                        parts = ts.replace("AM", "").replace("PM", "").split(":")
                        hour = int(parts[0])
                        minute = int(parts[1]) if len(parts) > 1 else 0
                    else:
                        hour = int(ts.replace("AM", "").replace("PM", ""))

                    if "PM" in ts and hour != 12:
                        hour += 12
                    if "AM" in ts and hour == 12:
                        hour = 0
                    return time(hour, minute)

                start_time = parse_time(start_str)
                end_time = parse_time(end_str)

                # Build a 15-minute actual slot
                end_slot_dt = datetime.combine(current_date, start_time) + timedelta(minutes=15)
                slot_end_time = end_slot_dt.time()

                # Skip past slots for today
                if current_date == today:
                    slot_dt = datetime.combine(current_date, start_time, tzinfo=UK_TZ)
                    if slot_dt < timezone.now():
                        continue

                obj, created = TimeSlot.objects.get_or_create(
                    mentor=mentor,
                    date=current_date,
                    start_time=start_time,
                    defaults={
                        "end_time": slot_end_time,
                        "is_available": True,
                        "is_booked": False,
                    },
                )

                if created:
                    slots_created += 1
                else:
                    slots_skipped += 1

            current_date += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS("\n=== Summary for Kapil ==="))
        self.stdout.write(self.style.SUCCESS(f"Created: {slots_created} new slots"))
        self.stdout.write(self.style.WARNING(f"Skipped existing: {slots_skipped}"))
        self.stdout.write(
            self.style.SUCCESS(f"Total Kapil slots now: {TimeSlot.objects.filter(mentor=mentor).count()}")
        )
