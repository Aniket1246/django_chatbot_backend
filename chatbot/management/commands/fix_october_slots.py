# chatbot/management/commands/fix_october_slots.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, time, timedelta
from chatbot.models import Mentor, TimeSlot, BlockedDate, MentorAvailability
from zoneinfo import ZoneInfo

UK_TZ = ZoneInfo("Europe/London")

class Command(BaseCommand):
    help = 'Fix October slots to have 15-minute breaks between sessions'

    def handle(self, *args, **options):
        # Define the date range to fix (up to October 13, 2025)
        start_date = datetime(2025, 10, 1).date()
        end_date = datetime(2025, 10, 13).date()
        
        self.stdout.write(f'Fixing slots from {start_date} to {end_date}...\n')
        
        # Delete existing slots in this range
        deleted_count = TimeSlot.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        ).count()
        
        TimeSlot.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        ).delete()
        
        self.stdout.write(self.style.WARNING(f'Deleted {deleted_count} old slots\n'))
        
        # Get all active mentors
        mentors = Mentor.objects.filter(is_active=True)
        
        if not mentors.exists():
            self.stdout.write(self.style.WARNING('No active mentors found.'))
            return

        slots_created = 0

        for mentor in mentors:
            self.stdout.write(f'Creating slots for mentor: {mentor.user.username}')
            
            # Check if mentor has any blocked dates
            blocked_dates = set(BlockedDate.objects.filter(mentor=mentor).values_list('date', flat=True))
            
            current_date = start_date
            while current_date <= end_date:
                # Skip weekends
                if current_date.weekday() >= 5:  # Saturday (5) and Sunday (6)
                    current_date += timedelta(days=1)
                    continue
                
                # Skip blocked dates
                if current_date in blocked_dates:
                    self.stdout.write(f'  Skipping blocked date: {current_date}')
                    current_date += timedelta(days=1)
                    continue
                
                # Get mentor availability for this date
                try:
                    availability = MentorAvailability.objects.get(
                        mentor=mentor,
                        date=current_date,
                        is_active=True
                    )
                    
                    # Get available slots from the availability
                    available_slots = availability.get_available_slots()
                    
                    if not available_slots:
                        current_date += timedelta(days=1)
                        continue
                    
                    # Create 15-minute slots with 15-minute breaks between sessions
                    for slot in available_slots:
                        # Parse time strings
                        start_time_str = slot['start_time']
                        
                        # Parse hours and minutes
                        start_parts = start_time_str.replace(':', ' ').replace('AM', '').replace('PM', '').strip().split()
                        
                        start_hour = int(start_parts[0])
                        start_minute = int(start_parts[1]) if len(start_parts) > 1 else 0
                        
                        # Adjust for PM
                        if 'PM' in start_time_str and start_hour != 12:
                            start_hour += 12
                        if 'AM' in start_time_str and start_hour == 12:
                            start_hour = 0
                        
                        # Create only ONE 15-minute slot per 30-minute availability
                        # The remaining 15 minutes serve as a break
                        slot_start = time(start_hour, start_minute)
                        slot_end = time(start_hour, start_minute + 15)
                        
                        # Skip slots in the past for today
                        today = timezone.now().date()
                        if current_date == today:
                            slot_time = datetime(current_date.year, current_date.month, current_date.day, 
                                               start_hour, start_minute, tzinfo=UK_TZ)
                            if slot_time < timezone.now():
                                continue
                        
                        # Create the time slot
                        TimeSlot.objects.create(
                            mentor=mentor,
                            date=current_date,
                            start_time=slot_start,
                            end_time=slot_end,
                            is_available=True,
                            is_booked=False
                        )
                        slots_created += 1
                        
                except MentorAvailability.DoesNotExist:
                    # No availability set for this day, skip
                    pass
                
                current_date += timedelta(days=1)
            
            self.stdout.write(f'  Completed for {mentor.user.username}')

        self.stdout.write(self.style.SUCCESS(f'\n=== Summary ==='))
        self.stdout.write(self.style.WARNING(f'Deleted old slots: {deleted_count}'))
        self.stdout.write(self.style.SUCCESS(f'Created new slots with breaks: {slots_created}'))
        self.stdout.write(self.style.SUCCESS(f'Total slots in database: {TimeSlot.objects.count()}'))