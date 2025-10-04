# chatbot/management/commands/init_mentor_availability.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import datetime, timedelta
from chatbot.models import Mentor, MentorAvailability

class Command(BaseCommand):
    help = 'Initialize default mentor availability through January 2026'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help='Number of days to create availability for (default: until Jan 31, 2026)',
        )

    def handle(self, *args, **options):
        # Get all active mentors
        mentors = Mentor.objects.filter(is_active=True)
        
        if not mentors.exists():
            self.stdout.write(self.style.WARNING('No active mentors found.'))
            return

        availabilities_created = 0
        availabilities_existed = 0
        
        # Determine end date
        today = timezone.now().date()
        if options['days']:
            end_date = today + timedelta(days=options['days'])
        else:
            end_date = datetime(2026, 1, 31).date()
        
        total_days = (end_date - today).days + 1
        self.stdout.write(f'Creating availability from {today} to {end_date} ({total_days} days)\n')
        
        for mentor in mentors:
            self.stdout.write(f'Processing mentor: {mentor.user.username}')
            
            current_date = today
            mentor_created = 0
            mentor_existed = 0
            
            while current_date <= end_date:
                # Skip weekends
                if current_date.weekday() >= 5:  # Saturday (5) and Sunday (6)
                    current_date += timedelta(days=1)
                    continue
                
                # Create or get availability for this date
                availability, created = MentorAvailability.objects.get_or_create(
                    mentor=mentor,
                    date=current_date,
                    defaults={
                        # Set default availability (9 AM to 5 PM with lunch break)
                        'morning_9_930': True,
                        'morning_930_10': True,
                        'morning_10_1030': True,
                        'morning_1030_11': True,
                        'morning_11_1130': True,
                        'lunch_1130_12': False,  # Lunch break
                        'lunch_12_1230': False,  # Lunch break
                        'lunch_1230_1': True,
                        'afternoon_1_130': True,
                        'afternoon_130_2': True,
                        'afternoon_2_230': True,
                        'afternoon_230_3': True,
                        'afternoon_3_330': True,
                        'afternoon_330_4': True,
                        'afternoon_4_430': True,
                        'afternoon_430_5': True,
                    }
                )
                
                if created:
                    availabilities_created += 1
                    mentor_created += 1
                else:
                    availabilities_existed += 1
                    mentor_existed += 1
                
                current_date += timedelta(days=1)
            
            self.stdout.write(f'  Created: {mentor_created}, Already existed: {mentor_existed}')

        self.stdout.write(self.style.SUCCESS(f'\n=== Summary ==='))
        self.stdout.write(self.style.SUCCESS(f'Successfully created: {availabilities_created} availability records'))
        self.stdout.write(self.style.WARNING(f'Already existed: {availabilities_existed} availability records'))
        self.stdout.write(self.style.SUCCESS(f'Total availability records in database: {MentorAvailability.objects.count()}'))