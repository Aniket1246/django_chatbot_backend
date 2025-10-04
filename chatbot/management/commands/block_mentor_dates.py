# chatbot/management/commands/block_mentor_dates.py
"""
Management command to block a mentor for an extended period
Usage: python manage.py block_mentor_dates --mentor_email=kapil@example.com --start=2024-10-10 --end=2024-11-10 --reason="Medical leave"
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from datetime import datetime, timedelta
from chatbot.models import Mentor, BlockedDate, TimeSlot, MentorAvailability

class Command(BaseCommand):
    help = 'Block a mentor for an extended period and mark all slots unavailable'

    def add_arguments(self, parser):
        parser.add_argument('--mentor_email', type=str, required=True, help='Mentor email address')
        parser.add_argument('--start', type=str, required=True, help='Start date (YYYY-MM-DD)')
        parser.add_argument('--end', type=str, required=True, help='End date (YYYY-MM-DD)')
        parser.add_argument('--reason', type=str, default='Unavailable', help='Reason for blocking')
        parser.add_argument('--unblock', action='store_true', help='Unblock instead of block')

    @transaction.atomic
    def handle(self, *args, **options):
        mentor_email = options['mentor_email']
        start_date = datetime.strptime(options['start'], '%Y-%m-%d').date()
        end_date = datetime.strptime(options['end'], '%Y-%m-%d').date()
        reason = options['reason']
        unblock = options['unblock']

        # Get mentor
        try:
            mentor = Mentor.objects.get(user__email=mentor_email, is_active=True)
        except Mentor.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'❌ Mentor with email {mentor_email} not found'))
            return

        if unblock:
            self._unblock_mentor(mentor, start_date, end_date)
        else:
            self._block_mentor(mentor, start_date, end_date, reason)

    def _block_mentor(self, mentor, start_date, end_date, reason):
        """Block mentor for the specified period"""
        self.stdout.write(f'🚫 Blocking {mentor.user.username} from {start_date} to {end_date}')
        
        blocked_count = 0
        slots_disabled = 0
        availability_disabled = 0
        
        # Create BlockedDate records for each day
        current_date = start_date
        while current_date <= end_date:
            blocked_date, created = BlockedDate.objects.get_or_create(
                mentor=mentor,
                date=current_date,
                defaults={'reason': reason}
            )
            if created:
                blocked_count += 1
            current_date += timedelta(days=1)
        
        # Disable all TimeSlot records in this period
        slots_updated = TimeSlot.objects.filter(
            mentor=mentor,
            date__gte=start_date,
            date__lte=end_date
        ).update(is_available=False)
        slots_disabled += slots_updated
        
        # Disable all MentorAvailability records in this period
        availability_updated = MentorAvailability.objects.filter(
            mentor=mentor,
            date__gte=start_date,
            date__lte=end_date
        ).update(is_active=False)
        availability_disabled += availability_updated
        
        self.stdout.write(self.style.SUCCESS(
            f'✅ Successfully blocked {mentor.user.username}\n'
            f'   - Created {blocked_count} blocked date records\n'
            f'   - Disabled {slots_disabled} time slots\n'
            f'   - Disabled {availability_disabled} availability records'
        ))

    def _unblock_mentor(self, mentor, start_date, end_date):
        """Unblock mentor for the specified period"""
        self.stdout.write(f'✅ Unblocking {mentor.user.username} from {start_date} to {end_date}')
        
        # Remove BlockedDate records
        deleted_count = BlockedDate.objects.filter(
            mentor=mentor,
            date__gte=start_date,
            date__lte=end_date
        ).delete()[0]
        
        # Re-enable TimeSlot records (only if not booked)
        slots_enabled = TimeSlot.objects.filter(
            mentor=mentor,
            date__gte=start_date,
            date__lte=end_date,
            is_booked=False
        ).update(is_available=True)
        
        # Re-enable MentorAvailability records
        availability_enabled = MentorAvailability.objects.filter(
            mentor=mentor,
            date__gte=start_date,
            date__lte=end_date
        ).update(is_active=True)
        
        self.stdout.write(self.style.SUCCESS(
            f'✅ Successfully unblocked {mentor.user.username}\n'
            f'   - Removed {deleted_count} blocked date records\n'
            f'   - Enabled {slots_enabled} time slots\n'
            f'   - Enabled {availability_enabled} availability records'
        ))


# chatbot/utils.py - Add helper function
def is_mentor_available_on_date(mentor, date):
    """
    Check if a mentor is available on a specific date
    Returns False if there's a BlockedDate record
    """
    from chatbot.models import BlockedDate
    return not BlockedDate.objects.filter(mentor=mentor, date=date).exists()