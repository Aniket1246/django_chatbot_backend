from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, time, timedelta
from chatbot.models import Mentor, TimeSlot, BlockedDate, MentorAvailability
from zoneinfo import ZoneInfo

UK_TZ = ZoneInfo("Europe/London")

class Command(BaseCommand):
    help = 'Creates time slots based on mentor availability'

    def add_arguments(self, parser):
        parser.add_argument(
            '--recreate',
            action='store_true',
            help='Delete all existing slots and recreate them',
        )

    def handle(self, *args, **options):
        recreate = options.get('recreate', False)
        
        # Get all active mentors
        mentors = Mentor.objects.filter(is_active=True)
        
        if not mentors.exists():
            self.stdout.write(self.style.WARNING('No active mentors found.'))
            return

        # If recreate flag is set, delete all existing time slots
        if recreate:
            self.stdout.write(self.style.WARNING('Deleting all existing time slots...'))
            deleted_count = TimeSlot.objects.all().count()
            TimeSlot.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f'Deleted {deleted_count} existing time slots.'))

        # Create slots until January 31, 2026 (excluding weekends)
        today = timezone.now().date()
        end_date = datetime(2026, 1, 31).date()
        slots_created = 0
        slots_skipped = 0

        for mentor in mentors:
            self.stdout.write(f'\nCreating slots for mentor: {mentor.user.username}')
            
            # Check if mentor has any blocked dates
            blocked_dates = set(BlockedDate.objects.filter(mentor=mentor).values_list('date', flat=True))
            
            current_date = today
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
                        end_time_str = slot['end_time']
                        
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
                        if current_date == today:
                            slot_time = datetime(current_date.year, current_date.month, current_date.day, 
                                               start_hour, start_minute, tzinfo=UK_TZ)
                            if slot_time < timezone.now():
                                continue
                        
                        # Create the time slot
                        slot_obj, created = TimeSlot.objects.get_or_create(
                            mentor=mentor,
                            date=current_date,
                            start_time=slot_start,
                            end_time=slot_end,
                            defaults={'is_available': True, 'is_booked': False}
                        )
                        
                        if created:
                            slots_created += 1
                        else:
                            slots_skipped += 1
                        
                except MentorAvailability.DoesNotExist:
                    # No availability set for this day, skip
                    pass
                
                current_date += timedelta(days=1)
            
            self.stdout.write(f'  Completed for {mentor.user.username}')

        self.stdout.write(self.style.SUCCESS(f'\n=== Summary ==='))
        self.stdout.write(self.style.SUCCESS(f'Successfully created: {slots_created} time slots'))
        self.stdout.write(self.style.WARNING(f'Already existed (skipped): {slots_skipped} time slots'))
        self.stdout.write(self.style.SUCCESS(f'Total slots now in database: {TimeSlot.objects.count()}'))