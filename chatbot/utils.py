# chatbot/utils.py
"""
Utility functions for calendar integration with free Gmail accounts.
"""

import datetime
import re
import urllib.parse
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# IST timezone
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

def validate_email_list(emails: List[str]) -> List[str]:
    """Validate and clean email addresses"""
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    valid_emails = []
    
    for email in emails:
        email = email.strip()
        if re.match(email_pattern, email):
            valid_emails.append(email)
        else:
            logger.warning(f"Invalid email address skipped: {email}")
    
    return valid_emails

def create_calendar_url(summary: str, start_time: datetime.datetime, end_time: datetime.datetime, description: str = "") -> str:
    """
    Create a Google Calendar URL for adding events manually.
    This serves as a fallback when API creation fails.
    """
    # Format dates for Google Calendar URL
    start_str = start_time.strftime('%Y%m%dT%H%M%S')
    end_str = end_time.strftime('%Y%m%dT%H%M%S')
    
    params = {
        'action': 'TEMPLATE',
        'text': summary,
        'dates': f'{start_str}/{end_str}',
        'details': description,
        'location': 'Google Meet',
        'ctz': 'Asia/Kolkata'
    }
    
    base_url = 'https://calendar.google.com/calendar/render'
    url_params = urllib.parse.urlencode(params)
    return f"{base_url}?{url_params}"

def format_meeting_summary(booking) -> str:
    """Format a summary of the meeting for display"""
    from .models import SessionBooking  # Import here to avoid circular imports
    
    attendee_names = ', '.join(booking.attendees) if booking.attendees else 'No attendees'
    
    summary = f"""
📅 Meeting Summary
=================
🏷️  Title: 1-on-1 Mentorship Session
👤 Organizer: {booking.user.username}
👥 Attendees: {attendee_names}
🕐 Time: {booking.start_time.strftime('%A, %B %d, %Y at %I:%M %p')} IST
⏱️  Duration: {int((booking.end_time - booking.start_time).total_seconds() / 60)} minutes
🎥 Google Meet: {booking.meet_link}
📅 Calendar: {booking.calendar_link}
✅ Status: {booking.get_status_display()}

📋 Next Steps:
- Share the Google Meet link with all attendees
- Add the event to attendees' calendars using the calendar link
- Join the meeting a few minutes early to test audio/video
"""
    return summary

def is_meeting_request(message: str) -> bool:
    """
    Detect if user is asking for a session/1-on-1 call/meeting/mentorship.
    Returns True if any keyword matches.
    """
    msg = message.lower().strip()

    patterns = [
        # --- Generic booking phrases ---
        r"\bbook( a)? (call|meeting|session|mentor|mentorship|chat)\b",
        r"\bschedule( a)? (call|meeting|session|mentor|mentorship|chat)\b",
        r"\b(reserve|arrange|setup|set up|fix|plan)( a)? (call|meeting|session|chat)\b",

        # --- Mentorship-specific ---
        r"\bbook( a)? mentor\b",
        r"\bbook( a)? mentorship (call|session|meeting)?\b",
        r"\bschedule( a)? mentorship (call|session|meeting)?\b",
        r"\bconnect with (a )?mentor\b",
        r"\btalk to (a )?mentor\b",
        r"\bneed (a )?mentor\b",
        r"\bwant (a )?mentor\b",

        # --- 1-on-1 / 1:1 variants ---
        r"\b1[\s:\-]?[oO]n[\s:\-]?1\b",         # 1on1 / 1:1 / 1-on-1
        r"\bone[\s\-]?on[\s\-]?one\b",           # one on one
        r"\bone to one\b",
        r"\b1[\s:\-]?1[\s:\-]?\b",               # "1 1" or "1-1" or "1:1"
        r"\bbook 1[\s:\-]?[1lI]\b",              # handles "book 1:11" typo too

        # --- Common phrasing ---
        r"\bmentor(ship)? (session|call|meeting|chat)\b",
        r"\bjoin (a )?(mentor|mentorship) (session|call)\b",
        r"\bget (a )?(mentor|guidance|session)\b",
        r"\bstart (a )?1[\s:\-]?1\b",
        r"\bhelp me (book|schedule) (a )?(mentor|call|session)\b"
    ]

    return any(re.search(p, msg) for p in patterns)



def extract_duration(message: str) -> int:
    """
    Extract duration in minutes from user message if specified.
    Defaults to 120 minutes (2 hours).
    Examples:
        "book a 30 min call" → 30
        "schedule 1 hour session" → 60
    """
    msg = message.lower()

    # Match "30 min" / "45 minutes"
    match_min = re.search(r"(\d+)\s*(min|minutes?)", msg)
    if match_min:
        return int(match_min.group(1))

    # Match "1 hour" / "2 hours"
    match_hr = re.search(r"(\d+)\s*(hour|hours?)", msg)
    if match_hr:
        return int(match_hr.group(1)) * 60

    return 120  # default 2 hours

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

def cancel_calendar_event(event_id: str) -> bool:
    """
    Cancel a Google Calendar event using the API.
    """
    try:
        creds = Credentials.from_authorized_user_file("token.json", ["https://www.googleapis.com/auth/calendar"])
        service = build("calendar", "v3", credentials=creds)

        service.events().delete(calendarId="primary", eventId=event_id).execute()

        print(f"✅ Google Calendar event {event_id} cancelled successfully")
        return True
    except Exception as e:
        print(f"❌ Failed to cancel Google Calendar event: {e}")
        return False
