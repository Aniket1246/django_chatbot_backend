# chatbot/admin.py

from django.contrib import admin
from .models import (
    UserProfile, 
    Mentor, 
    MentorSchedule,  # Existing model - retained
    SessionBooking,   # Existing model - retained
    MentorAvailability, 
    BlockedDate, 
    TimeSlot, 
    EnhancedSessionBooking,
    ChatHistory
)

# Existing model admins - retained but not used in new implementation
@admin.register(MentorSchedule)
class MentorScheduleAdmin(admin.ModelAdmin):
    list_display = ['mentor', 'weekday', 'start_time', 'end_time', 'is_active', 'created_at']
    list_filter = ['weekday', 'is_active', 'mentor']
    search_fields = ['mentor__username']

@admin.register(SessionBooking)
class SessionBookingAdmin(admin.ModelAdmin):
    list_display = ['user', 'mentor', 'start_time', 'end_time', 'status', 'created_at']
    list_filter = ['status', 'created_at', 'mentor', 'user']
    search_fields = ['user__username', 'mentor__username', 'event_id']
    date_hierarchy = 'start_time'

# New model admins - these will be used in the new implementation
@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_premium', 'session_count', 'created_at']
    list_filter = ['is_premium', 'created_at']
    search_fields = ['user__username', 'user__email']

@admin.register(Mentor)
class MentorAdmin(admin.ModelAdmin):
    list_display = ['user', 'expertise', 'is_active', 'created_at']
    list_filter = ['is_active', 'expertise', 'created_at']
    search_fields = ['user__username', 'user__email', 'expertise']

@admin.register(MentorAvailability)
class MentorAvailabilityAdmin(admin.ModelAdmin):
    list_display = ['mentor', 'date', 'is_active', 'created_at']
    list_filter = ['date', 'is_active', 'mentor']
    search_fields = ['mentor__username', 'date']
    date_hierarchy = 'date'
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('mentor', 'date', 'is_active')
        }),
        ('Morning Slots', {
            'fields': (
                'morning_9_930', 'morning_930_10', 'morning_10_1030', 
                'morning_1030_11', 'morning_11_1130'
            ),
            'classes': ('collapse',)
        }),
        ('Lunch Slots', {
            'fields': ('lunch_1130_12', 'lunch_12_1230', 'lunch_1230_1'),
            'classes': ('collapse',)
        }),
        ('Afternoon Slots', {
            'fields': (
                'afternoon_1_130', 'afternoon_130_2', 'afternoon_2_230',
                'afternoon_230_3', 'afternoon_3_330', 'afternoon_330_4',
                'afternoon_4_430', 'afternoon_430_5'
            ),
            'classes': ('collapse',)
        }),
        ('Additional Info', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )

@admin.register(BlockedDate)
class BlockedDateAdmin(admin.ModelAdmin):
    list_display = ['mentor', 'date', 'reason', 'created_at']
    list_filter = ['date', 'mentor']
    search_fields = ['mentor__username', 'date', 'reason']
    date_hierarchy = 'date'

@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ['mentor', 'date', 'start_time', 'end_time', 'is_available', 'is_booked', 'created_at']
    list_filter = ['date', 'is_available', 'is_booked', 'mentor']
    search_fields = ['mentor__username', 'date']
    date_hierarchy = 'date'
    
    fieldsets = (
        ('Slot Info', {
            'fields': ('mentor', 'date', 'start_time', 'end_time')
        }),
        ('Status', {
            'fields': ('is_available', 'is_booked')
        }),
        ('Booking Info', {
            'fields': ('booking',),
            'classes': ('collapse',)
        }),
    )

@admin.register(EnhancedSessionBooking)
class EnhancedSessionBookingAdmin(admin.ModelAdmin):
    list_display = ['user', 'mentor', 'start_time', 'end_time', 'status', 'created_at']
    list_filter = ['status', 'created_at', 'mentor', 'user']
    search_fields = ['user__username', 'mentor__username', 'event_id']
    date_hierarchy = 'start_time'
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('user', 'mentor', 'start_time', 'end_time')
        }),
        ('Status & Tracking', {
            'fields': ('status', 'invitation_sent')
        }),
        ('Calendar Integration', {
            'fields': ('event_id', 'meet_link', 'calendar_link'),
            'classes': ('collapse',)
        }),
        ('Additional Info', {
            'fields': ('notes', 'attendees'),
            'classes': ('collapse',)
        }),
    )

@admin.register(ChatHistory)
class ChatHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'message', 'response', 'created_at']
    list_filter = ['created_at', 'user']
    search_fields = ['user__username', 'message', 'response']
    date_hierarchy = 'created_at'