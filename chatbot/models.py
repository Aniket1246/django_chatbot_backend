# chatbot/models.py
from django.db import models
from django.contrib.auth.models import User
import datetime

class UserProfile(models.Model):
    # Link to Django User (one-to-one relationship)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    
    # Profile fields
    is_premium = models.BooleanField(default=False)
    session_count = models.IntegerField(default=0)
    
    # Keep email for flexibility
    email = models.EmailField(unique=True, null=True, blank=True)
    
    # Additional profile fields
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

    # 🔹 Add timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Mentor: {self.user.username} ({'Active' if self.is_active else 'Inactive'})"

    
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