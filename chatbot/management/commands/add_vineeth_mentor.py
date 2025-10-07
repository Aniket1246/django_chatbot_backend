from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from chatbot.models import Mentor, TimeSlot
from datetime import datetime, timedelta, time
import pytz

class Command(BaseCommand):
    help = 'Add Vineeth Kumar Vellala as mentor with UK time slots (6:30-7:30 PM UK, Weekdays Only)'

    def handle(self, *args, **kwargs):
        # --- Create or get user ---
        username = 'vineeth_kumar'
        email = 'vardaan@ukjobsinsider.com'

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': email,
                'first_name': 'Vineeth Kumar',
                'last_name': 'Vellala'
            }
        )

        if created:
            user.set_password('VineethMentor@2024')
            user.save()
            self.stdout.write(self.style.SUCCESS(f'✓ Created user: {username}'))
        else:
            self.stdout.write(self.style.WARNING(f'⚠ User {username} already exists'))

        # --- Create or get mentor ---
        mentor, created = Mentor.objects.get_or_create(
            user=user,
            defaults={
                'expertise': 'Senior Data Scientist at DatAInfa',
                'is_active': True,
                'is_head_mentor': False,
                'display_name': 'Vineeth Kumar Vellala'
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS(f'✓ Created mentor: {mentor.display_name}'))
        else:
            self.stdout.write(self.style.WARNING(f'⚠ Mentor {mentor.display_name} already exists'))
            mentor.expertise = 'Senior Data Scientist at DatAInfa'
            mentor.display_name = 'Vineeth Kumar Vellala'
            mentor.save()

        # --- Delete old time slots ---
        old_slots = TimeSlot.objects.filter(mentor=mentor)
        deleted_count = old_slots.count()
        old_slots.delete()
        self.stdout.write(self.style.SUCCESS(f'✓ Deleted {deleted_count} old time slots'))

        # --- Timezone setup ---
        uk_tz = pytz.timezone('Europe/London')
        ist_tz = pytz.timezone('Asia/Kolkata')

        # --- UK time: 6:30 PM - 7:30 PM (18:30 - 19:30) ---
        uk_start_hour = 18
        uk_start_minute = 30
        uk_end_hour = 19
        uk_end_minute = 30

        # --- Generate slots for next 60 days (WEEKDAYS ONLY) ---
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=60)

        slots_created = 0
        current_date = start_date

        while current_date <= end_date:
            # Only process weekdays (Monday=0 to Friday=4)
            if current_date.weekday() < 5:
                # Create UK datetime for 6:30 PM UK
                uk_datetime = uk_tz.localize(
                    datetime.combine(current_date, time(uk_start_hour, uk_start_minute))
                )
                uk_end_datetime = uk_tz.localize(
                    datetime.combine(current_date, time(uk_end_hour, uk_end_minute))
                )

                # Store UK time directly (no conversion)
                # This will show as 6:30-7:30 PM in database
                current_slot_time = uk_datetime
                while current_slot_time < uk_end_datetime:
                    slot_end_time = current_slot_time + timedelta(minutes=15)

                    slot, slot_created = TimeSlot.objects.get_or_create(
                        mentor=mentor,
                        date=current_slot_time.date(),
                        start_time=current_slot_time.time(),
                        defaults={
                            'end_time': slot_end_time.time(),
                            'is_available': True,
                            'is_booked': False
                        }
                    )

                    if slot_created:
                        slots_created += 1

                    current_slot_time = slot_end_time

            current_date += timedelta(days=1)

        # --- Summary ---
        self.stdout.write(self.style.SUCCESS('\n' + '='*60))
        self.stdout.write(self.style.SUCCESS('✓ VINEETH MENTOR SETUP COMPLETE'))
        self.stdout.write(self.style.SUCCESS('='*60))
        self.stdout.write(self.style.SUCCESS(f'✓ Created {slots_created} time slots'))
        self.stdout.write(self.style.SUCCESS(f'✓ Mentor: {mentor.display_name}'))
        self.stdout.write(self.style.SUCCESS(f'✓ Email: {email}'))
        self.stdout.write(self.style.SUCCESS(f'✓ Username: {username}'))
        self.stdout.write(self.style.SUCCESS(f'✓ Password: VineethMentor@2024'))
        self.stdout.write(self.style.SUCCESS(f'✓ Availability: 6:30-7:30 PM UK Time (stored as UK time)'))
        self.stdout.write(self.style.SUCCESS(f'✓ Days: Monday-Friday ONLY'))
        self.stdout.write(self.style.SUCCESS(f'✓ Duration: 15-minute slots'))
        self.stdout.write(self.style.SUCCESS('='*60))