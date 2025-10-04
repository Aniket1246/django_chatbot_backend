# chatbot/models.py
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
import datetime

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_premium = models.BooleanField(default=False)
    session_count = models.IntegerField(default=0)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=15, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_profiles'

    def __str__(self):
        return f"{self.user.username} - {'Premium' if self.is_premium else 'Free'}"

    def increment_session_count(self):
        """Increment session count when user books a session"""
        self.session_count += 1
        self.save()

class Mentor(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mentor_profile")
    expertise = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_head_mentor = models.BooleanField(default=False, help_text="Check if this mentor is the head mentor for first-time users")
    display_name = models.CharField(max_length=255, blank=True, null=True, help_text="Custom display name (e.g., 'Vardaan')")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Mentor: {self.user.username} ({'Active' if self.is_active else 'Inactive'})"
    
    def get_display_name(self):
        """Return display name if set, otherwise return username"""
        return self.display_name if self.display_name else self.user.username
    
    def delete(self, *args, **kwargs):
        """Override delete to also delete all time slots for this mentor"""
        # Delete all time slots for this mentor
        self.time_slots.all().delete()
        # Call the parent delete method
        super().delete(*args, **kwargs)

# Existing models - retained but not used in new implementation
class MentorSchedule(models.Model):
    """
    Defines recurring weekly availability for mentors
    """
    WEEKDAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    mentor = models.ForeignKey(Mentor, on_delete=models.CASCADE, related_name='schedules')
    weekday = models.IntegerField(choices=WEEKDAY_CHOICES)
    start_time = models.TimeField(help_text="Start time of availability (e.g., 09:00)")
    end_time = models.TimeField(help_text="End time of availability (e.g., 17:00)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'mentor_schedules'
        ordering = ['weekday', 'start_time']
        unique_together = ['mentor', 'weekday', 'start_time']

    def __str__(self):
        return f"{self.mentor.user.username} - {self.get_weekday_display()} {self.start_time}-{self.end_time}"

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError("End time must be after start time")

class SessionBooking(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed')
    ]

    # Linked to the user who booked the session
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    mentor = models.ForeignKey(Mentor, on_delete=models.SET_NULL, null=True, blank=True, related_name="sessions")

    # Session details
    organizer = models.CharField(max_length=255, null=True, blank=True)
    confirmed = models.BooleanField(default=False)
    
    # Timing
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    
    # Links
    calendar_link = models.URLField(max_length=500, null=True, blank=True)
    meet_link = models.URLField(max_length=500, null=True, blank=True)
    
    # Use Django's native JSONField (Django 3.1+)
    attendees = models.JSONField(default=list, null=True, blank=True)    
    event_id = models.CharField(max_length=200, null=True, blank=True)
    invitation_sent = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        db_table = 'session_bookings'

    def __str__(self):
        return f"Session for {self.user.username} at {self.start_time}"

    @property
    def is_past(self):
        """Check if the session is in the past"""
        if not self.start_time:
            return False
        # Import here to avoid circular imports
        try:
            from .calendar_client import IST
            return self.start_time < datetime.datetime.now(IST)
        except ImportError:
            # Fallback if calendar_client doesn't exist
            import pytz
            IST = pytz.timezone('Asia/Kolkata')
            return self.start_time < datetime.datetime.now(IST)

    def save(self, *args, **kwargs):
        """Override save to increment user's session count"""
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        if is_new and self.status == 'confirmed':
            # Increment session count for the user
            profile, created = UserProfile.objects.get_or_create(user=self.user)
            profile.increment_session_count()

class ChatHistory(models.Model):
    # Keep track of messages per user
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    response = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        db_table = 'chat_history'

    def __str__(self):
        return f"{self.user.username}: {self.message[:50]}..."

# New models for the simplified booking system
class MentorAvailability(models.Model):
    """
    Simplified mentor availability model with date and time slots
    """
    mentor = models.ForeignKey(Mentor, on_delete=models.CASCADE, related_name='availabilities')
    date = models.DateField()
    
    # Simplified time slots (30-minute intervals)
    morning_9_930 = models.BooleanField(default=False, verbose_name="9:00 AM - 9:30 AM")
    morning_930_10 = models.BooleanField(default=False, verbose_name="9:30 AM - 10:00 AM")
    morning_10_1030 = models.BooleanField(default=False, verbose_name="10:00 AM - 10:30 AM")
    morning_1030_11 = models.BooleanField(default=False, verbose_name="10:30 AM - 11:00 AM")
    morning_11_1130 = models.BooleanField(default=False, verbose_name="11:00 AM - 11:30 AM")
    
    lunch_1130_12 = models.BooleanField(default=False, verbose_name="11:30 AM - 12:00 PM")
    lunch_12_1230 = models.BooleanField(default=False, verbose_name="12:00 PM - 12:30 PM")
    lunch_1230_1 = models.BooleanField(default=False, verbose_name="12:30 PM - 1:00 PM")
    
    afternoon_1_130 = models.BooleanField(default=False, verbose_name="1:00 PM - 1:30 PM")
    afternoon_130_2 = models.BooleanField(default=False, verbose_name="1:30 PM - 2:00 PM")
    afternoon_2_230 = models.BooleanField(default=False, verbose_name="2:00 PM - 2:30 PM")
    afternoon_230_3 = models.BooleanField(default=False, verbose_name="2:30 PM - 3:00 PM")
    afternoon_3_330 = models.BooleanField(default=False, verbose_name="3:00 PM - 3:30 PM")
    afternoon_330_4 = models.BooleanField(default=False, verbose_name="3:30 PM - 4:00 PM")
    afternoon_4_430 = models.BooleanField(default=False, verbose_name="4:00 PM - 4:30 PM")
    afternoon_430_5 = models.BooleanField(default=False, verbose_name="4:30 PM - 5:00 PM")
    
    notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'mentor_availabilities'
        unique_together = ['mentor', 'date']
        ordering = ['date']

    def __str__(self):
        return f"{self.mentor.user.username} - {self.date}"

    def get_available_slots(self):
        """Get list of available time slots for this day"""
        available_slots = []
        
        slot_mapping = [
            ('morning_9_930', '9:00 AM', '9:30 AM'),
            ('morning_930_10', '9:30 AM', '10:00 AM'),
            ('morning_10_1030', '10:00 AM', '10:30 AM'),
            ('morning_1030_11', '10:30 AM', '11:00 AM'),
            ('morning_11_1130', '11:00 AM', '11:30 AM'),
            ('lunch_1130_12', '11:30 AM', '12:00 PM'),
            ('lunch_12_1230', '12:00 PM', '12:30 PM'),
            ('lunch_1230_1', '12:30 PM', '1:00 PM'),
            ('afternoon_1_130', '1:00 PM', '1:30 PM'),
            ('afternoon_130_2', '1:30 PM', '2:00 PM'),
            ('afternoon_2_230', '2:00 PM', '2:30 PM'),  # Fixed this line
            ('afternoon_230_3', '2:30 PM', '3:00 PM'),
            ('afternoon_3_330', '3:00 PM', '3:30 PM'),
            ('afternoon_330_4', '3:30 PM', '4:00 PM'),
            ('afternoon_4_430', '4:00 PM', '4:30 PM'),
            ('afternoon_430_5', '4:30 PM', '5:00 PM'),
        ]
        
        for slot_field, start_time, end_time in slot_mapping:
            if getattr(self, slot_field):
                available_slots.append({
                    'start_time': start_time,
                    'end_time': end_time,
                    'slot_field': slot_field
                })
        
        return available_slots

class BlockedDate(models.Model):
    """Dates when mentor is completely unavailable"""
    mentor = models.ForeignKey(Mentor, on_delete=models.CASCADE, related_name='blocked_dates')
    date = models.DateField()
    reason = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'blocked_dates'
        unique_together = ['mentor', 'date']
        ordering = ['date']

    def __str__(self):
        return f"{self.mentor.user.username} - Blocked on {self.date}"

class TimeSlot(models.Model):
    """
    Individual 15-minute time slots that can be booked
    """
    mentor = models.ForeignKey(Mentor, on_delete=models.CASCADE, related_name='time_slots')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_available = models.BooleanField(default=True, help_text="Admin can check/uncheck availability")
    is_booked = models.BooleanField(default=False)
    booking = models.ForeignKey(
        'EnhancedSessionBooking', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='time_slots'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'time_slots'
        ordering = ['date', 'start_time']
        unique_together = ['mentor', 'date', 'start_time']

    def __str__(self):
        status = "Booked" if self.is_booked else ("Available" if self.is_available else "Unavailable")
        return f"{self.mentor.user.username} - {self.date} {self.start_time} ({status})"

    @property
    def datetime_start(self):
        """Combine date and start_time into datetime"""
        return timezone.make_aware(
            datetime.datetime.combine(self.date, self.start_time),
            timezone.get_current_timezone()
        )

    @property
    def datetime_end(self):
        """Combine date and end_time into datetime"""
        return timezone.make_aware(
            datetime.datetime.combine(self.date, self.end_time),
            timezone.get_current_timezone()
        )

    def clean(self):
        # Validate slot duration
        dt_start = datetime.datetime.combine(datetime.date.today(), self.start_time)
        dt_end = datetime.datetime.combine(datetime.date.today(), self.end_time)
        duration = (dt_end - dt_start).total_seconds() / 60
        
        if duration != 15:
            raise ValidationError("Time slot must be exactly 15 minutes")
        
        # Cannot book if not available
        if self.is_booked and not self.is_available:
            raise ValidationError("Cannot book an unavailable slot")

    def get_next_available_slot(self):
        """Get the next available slot after this one, considering 15-minute breaks"""
        # Calculate the next slot start time (current end time + 15 minutes break)
        current_end = datetime.datetime.combine(self.date, self.end_time)
        next_start = current_end + datetime.timedelta(minutes=15)
        
        # If next_start goes beyond 5:00 PM, return None
        if next_start.time() > datetime.time(17, 0):
            return None
            
        # Try to find the next slot
        try:
            next_slot = TimeSlot.objects.get(
                mentor=self.mentor,
                date=self.date,
                start_time=next_start.time(),
                is_available=True,
                is_booked=False
            )
            return next_slot
        except TimeSlot.DoesNotExist:
            return None

    def get_next_available_slots(self, count=1):
        """Get the next available slots with 15-minute breaks between them"""
        slots = []
        current_slot = self
        
        while len(slots) < count:
            # Get the next available slot after the current one
            next_slot = current_slot.get_next_available_slot()
            if not next_slot:
                break
                
            slots.append(next_slot)
            current_slot = next_slot
            
        return slots

class EnhancedSessionBooking(models.Model):
    """
    Enhanced booking model that tracks multiple 15-min slots
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed')
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='enhanced_bookings')
    mentor = models.ForeignKey(Mentor, on_delete=models.CASCADE, related_name='enhanced_sessions')
    
    # Session details
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    duration_minutes = models.IntegerField(default=15)
    
    # Calendar integration
    event_id = models.CharField(max_length=200, null=True, blank=True)
    calendar_link = models.URLField(max_length=500, null=True, blank=True)
    meet_link = models.URLField(max_length=500, null=True, blank=True)
    
    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    invitation_sent = models.BooleanField(default=False)
    
    # Additional info
    notes = models.TextField(blank=True, null=True)
    attendees = models.JSONField(default=list, null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'enhanced_session_bookings'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} with {self.mentor.user.username} - {self.start_time.strftime('%Y-%m-%d %H:%M')}"

    @property
    def is_past(self):
        return self.start_time < timezone.now()

    def save(self, *args, **kwargs):
        # Calculate duration
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds() / 60
            self.duration_minutes = int(duration)
        
        is_new = self.pk is None
        super().save(*args, **kwargs)
        
        # Increment session count for new confirmed bookings
        if is_new and self.status == 'confirmed':
            profile, created = UserProfile.objects.get_or_create(user=self.user)
            profile.increment_session_count()

    def cancel_booking(self):
        """Cancel booking and free up time slots"""
        self.status = 'cancelled'
        self.save()
        
        # Free up associated time slots
        for slot in self.time_slots.all():
            slot.is_booked = False
            slot.booking = None
            slot.save()