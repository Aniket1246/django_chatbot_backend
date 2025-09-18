# chatbot/admin.py

from django.contrib import admin
from .models import SessionBooking, UserProfile,ChatHistory, Mentor

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_premium', 'session_count']
    search_fields = ['user__username']

@admin.register(SessionBooking)
class SessionBookingAdmin(admin.ModelAdmin):
    # Change 'time' to 'start_time'
    list_display = ['user', 'start_time', 'confirmed', 'calendar_link', 'meet_link']
    list_filter = ['confirmed', 'created_at']
    search_fields = ['user__username', 'summary']
    readonly_fields = ['created_at']

@admin.register(ChatHistory)
class ChatHistoryAdmin(admin.ModelAdmin):
    list_display = ("user", "message", "created_at")
    search_fields = ("user__username", "message")

# ✅ New Mentor model admin
@admin.register(Mentor)
class MentorAdmin(admin.ModelAdmin):
    list_display = ("user", "expertise", "is_active", "created_at")
    search_fields = ("user__username", "expertise")
    list_filter = ("is_active", "created_at")