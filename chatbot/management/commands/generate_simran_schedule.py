from django.core.management.base import BaseCommand
from datetime import date, datetime, timedelta, time
from chatbot.models import Mentor, TimeSlot

class Command(BaseCommand):
    help = "Generate Simran's 15-min slots until January 2026"

    def handle(self, *args, **options):
        try:
            simran = Mentor.objects.select_related("user").get(user__username__iexact="simran")
        except Mentor.DoesNotExist:
            self.stdout.write(self.style.ERROR("❌ Mentor 'Simran' not found. Please ensure her user exists."))
            return

        # Target end date (January 31, 2026)
        end_date = date(2026, 1, 31)
        today = date.today()
        total_days = (end_date - today).days

        self.stdout.write(self.style.WARNING(f"🗓 Generating Simran's schedule from {today} until {end_date} ({total_days} days)"))

        # IMPORTANT: Delete ALL of Simran's slots first (past and future) to ensure clean slate
        deleted_count = TimeSlot.objects.filter(mentor=simran).delete()[0]
        self.stdout.write(self.style.WARNING(f"🗑 Deleted {deleted_count} existing slots"))

        # Define recurring weekly slots
        # Monday=0, Tuesday=1, Wednesday=2, Thursday=3, Friday=4, Saturday=5, Sunday=6
        weekday_slots = {
            0: [(time(8, 0), time(9, 0)), (time(17, 30), time(18, 30))],  # Monday
            1: [(time(8, 0), time(9, 0)), (time(17, 30), time(18, 30))],  # Tuesday
            2: [(time(8, 0), time(9, 0)), (time(17, 30), time(18, 30))],  # Wednesday
            3: [(time(8, 0), time(9, 0)), (time(17, 30), time(18, 30))],  # Thursday
            4: [(time(8, 0), time(9, 0)), (time(17, 30), time(18, 30))],  # Friday
            5: [(time(9, 0), time(10, 0))],  # Saturday
            6: [(time(9, 0), time(10, 0))],  # Sunday
        }

        total_slots_created = 0
        slots_to_create = []

        # Generate slots for each day from TODAY onwards
        current_date = today
        while current_date <= end_date:
            weekday = current_date.weekday()
            
            # Only process if this weekday has slots defined
            if weekday in weekday_slots:
                for start_time, end_time in weekday_slots[weekday]:
                    # Generate 15-minute slots with 15-minute gaps
                    # Pattern: 15 min session, 15 min gap, 15 min session, 15 min gap...
                    current_datetime = datetime.combine(current_date, start_time)
                    end_datetime = datetime.combine(current_date, end_time)
                    
                    while current_datetime < end_datetime:
                        slot_end_datetime = current_datetime + timedelta(minutes=15)
                        
                        # Only create if slot end time doesn't exceed session end
                        if slot_end_datetime <= end_datetime:
                            # Create slots for all future dates
                            # For today, only create slots that are at least 15 minutes in the future
                            now = datetime.now()
                            slot_datetime = datetime.combine(current_date, current_datetime.time())
                            
                            # Create slot if it's a future date OR it's today and slot is in future
                            if current_date > today or slot_datetime >= now:
                                slots_to_create.append(
                                    TimeSlot(
                                        mentor=simran,
                                        date=current_date,
                                        start_time=current_datetime.time(),
                                        end_time=slot_end_datetime.time(),
                                        is_available=True,
                                        is_booked=False
                                    )
                                )
                                total_slots_created += 1
                        
                        # Move ahead by 30 minutes (15 min slot + 15 min gap)
                        current_datetime += timedelta(minutes=30)
            
            # Move to next day
            current_date += timedelta(days=1)

        # Bulk create all slots at once (much faster)
        TimeSlot.objects.bulk_create(slots_to_create, batch_size=1000)

        self.stdout.write(self.style.SUCCESS(f"✅ Created {total_slots_created} slots for Simran from {today} until {end_date}."))
        
        # Show next 5 days summary
        self.stdout.write(self.style.SUCCESS("\n📅 Next 5 days preview:"))
        for i in range(5):
            check_date = today + timedelta(days=i)
            count = TimeSlot.objects.filter(
                mentor=simran, 
                date=check_date,
                is_available=True
            ).count()
            self.stdout.write(f"  {check_date.strftime('%Y-%m-%d (%A)')}: {count} slots")