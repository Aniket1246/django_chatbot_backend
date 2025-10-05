from django.conf import settings
from typing import List, Tuple, Optional
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
import datetime as dt
from django.core.mail import EmailMessage
import ssl
from urllib.parse import quote
import json
from django.db import transaction
from django.core.exceptions import ValidationError
from functools import lru_cache

# Import models
from .models import TimeSlot, EnhancedSessionBooking, Mentor, UserProfile

BASE_DIR = Path(__file__).resolve().parent.parent
from zoneinfo import ZoneInfo
UK_TZ = ZoneInfo("Europe/London")

# MENTOR CONFIGURATION - Using single credentials file for all mentors
MENTOR_CONFIG = {
    "head": {
        "name": "Vardaan (Head Mentor)",
        "email": "sunilramtri000@gmail.com",
        "credentials_file": "credsam.json",  # Same file for all
        "meet_link": "https://meet.google.com/gbv-mkux-scx",
        "calendar_id": "sunilramtri000@gmail.com"
    },
    "kapil": {
        "name": "Kapil Mentor", 
        "email": "kapilsanjaykanjani@gmail.com",
        "credentials_file": "credsam.json",  # Same file
        "meet_link": "https://meet.google.com/csx-bkoy-sct",
        "calendar_id": "kapilsanjaykanjani@gmail.com"
    },
    "meena": {
        "name": "Meena Mentor", 
        "email": "meenavalavala@gmail.com",
        "credentials_file": "credsam.json",  # Same file
        "meet_link": "https://meet.google.com/csx-bkoy-sct",
        "calendar_id": "meenavalavala@gmail.com"
    },
    "amit": {
        "name": "Amit Mentor", 
        "email": "amit@example.com",
        "credentials_file": "credsam.json",  # Same file
        "meet_link": "https://meet.google.com/csx-bkoy-sct",
        "calendar_id": "amit@example.com"
    },
    "simran": {
        "name": "Simran Mentor", 
        "email": "simranchetanshah98@gmail.com",
        "credentials_file": "credsam.json",  # Same file
        "meet_link": "https://meet.google.com/vbu-xbhk-dji",
        "calendar_id": "simranchetanshah98@gmail.com"
    }
}

# Fallback configuration
DEFAULT_MENTOR_CONFIG = {
    "credentials_file": "credsam.json",  # Single credentials file
    "meet_link": "https://meet.google.com/csx-bkoy-sct",
    "calendar_id": "meenavalavala@gmail.com"
}

# 15-minute time slots (9 AM - 5 PM)
AVAILABLE_TIME_SLOTS = [
    (9, 0, 9, 15),   # 9:00 AM - 9:15 AM
    (9, 15, 9, 30),  # 9:15 AM - 9:30 AM
    (9, 30, 9, 45),  # 9:30 AM - 9:45 AM
    (9, 45, 10, 0),  # 9:45 AM - 10:00 AM
    (10, 0, 10, 15), # 10:00 AM - 10:15 AM
    (10, 15, 10, 30),# 10:15 AM - 10:30 AM
    (10, 30, 10, 45),# 10:30 AM - 10:45 AM
    (10, 45, 11, 0), # 10:45 AM - 11:00 AM
    (11, 0, 11, 15), # 11:00 AM - 11:15 AM
    (11, 15, 11, 30),# 11:15 AM - 11:30 AM
    (11, 30, 11, 45),# 11:30 AM - 11:45 AM
    (11, 45, 12, 0), # 11:45 AM - 12:00 PM
    (12, 0, 12, 15), # 12:00 PM - 12:15 PM
    (12, 15, 12, 30),# 12:15 PM - 12:30 PM
    (12, 30, 12, 45),# 12:30 PM - 12:45 PM
    (12, 45, 13, 0), # 12:45 PM - 1:00 PM
    (13, 0, 13, 15), # 1:00 PM - 1:15 PM
    (13, 15, 13, 30),# 1:15 PM - 1:30 PM
    (13, 30, 13, 45),# 1:30 PM - 1:45 PM
    (13, 45, 14, 0), # 1:45 PM - 2:00 PM
    (14, 0, 14, 15), # 2:00 PM - 2:15 PM
    (14, 15, 14, 30),# 2:15 PM - 2:30 PM
    (14, 30, 14, 45),# 2:30 PM - 2:45 PM
    (14, 45, 15, 0), # 2:45 PM - 3:00 PM
    (15, 0, 15, 15), # 3:00 PM - 3:15 PM
    (15, 15, 15, 30),# 3:15 PM - 3:30 PM
    (15, 30, 15, 45),# 3:30 PM - 3:45 PM
    (15, 45, 16, 0), # 3:45 PM - 4:00 PM
    (16, 0, 16, 15), # 4:00 PM - 4:15 PM
    (16, 15, 16, 30),# 4:15 PM - 4:30 PM
    (16, 30, 16, 45),# 4:30 PM - 4:45 PM
    (16, 45, 17, 0), # 4:45 PM - 5:00 PM
]

# Minimum gap between sessions (7 days)
MIN_SESSION_GAP_DAYS = 7

def debug_service_account_info(credentials_file: str):
    """Debug service account email and permissions"""
    try:
        credentials_path = BASE_DIR / credentials_file
        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path), 
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        service = build("calendar", "v3", credentials=credentials)
        
        # Get service account email from credentials
        with open(credentials_path, 'r') as f:
            cred_data = json.load(f)
            service_account_email = cred_data.get('client_email')
        
        print(f"Service Account Email: {service_account_email}")
        
        # Test calendar access
        calendar_list = service.calendarList().list().execute()
        print(f"Accessible calendars: {len(calendar_list.get('items', []))}")
        
        for cal in calendar_list.get('items', []):
            print(f"  - {cal['summary']} ({cal['id']}) - Access: {cal.get('accessRole', 'unknown')}")
            
        return service_account_email
        
    except Exception as e:
        print(f"Debug failed: {e}")
        return None

def get_mentor_config(mentor_email: str) -> dict:
    """
    Get mentor configuration based on email.
    Returns mentor config or default if not found.
    """
    # Check if it's a known mentor
    for mentor_key, config in MENTOR_CONFIG.items():
        if config["email"].lower() == mentor_email.lower():
            return config
    
    # Fallback to default configuration
    return {
        "name": "Mentor",
        "email": mentor_email,
        "credentials_file": DEFAULT_MENTOR_CONFIG["credentials_file"],
        "meet_link": DEFAULT_MENTOR_CONFIG["meet_link"],
        "calendar_id": mentor_email  # Use the mentor's email as calendar_id
    }

@lru_cache(maxsize=10)
def get_calendar_service(mentor_email: str = None):
    """
    Get Google Calendar service for specific mentor with caching.
    If mentor_email is provided, use their specific credentials.
    """
    mentor_config = get_mentor_config(mentor_email) if mentor_email else DEFAULT_MENTOR_CONFIG
    
    credentials_file = BASE_DIR / mentor_config["credentials_file"]
    
    if not os.path.exists(credentials_file):
        print(f"❌ Credentials file not found: {credentials_file}")
        # Fallback to default credentials
        credentials_file = BASE_DIR / DEFAULT_MENTOR_CONFIG["credentials_file"]
        if not os.path.exists(credentials_file):
            raise FileNotFoundError(f"No valid credentials file found")
    
    print(f"🔑 Using credentials: {credentials_file}")
    
    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    credentials = service_account.Credentials.from_service_account_file(
        str(credentials_file), scopes=SCOPES
    )
    service = build("calendar", "v3", credentials=credentials)
    return service, mentor_config

def verify_calendar_access(mentor_email: str) -> bool:
    """Verify that the service account has access to the mentor's calendar"""
    try:
        service, mentor_config = get_calendar_service(mentor_email)
        calendar_id = mentor_config["calendar_id"]
        
        # Try to access the calendar
        service.calendarList().get(calendarId=calendar_id).execute()
        print(f"✅ Calendar access verified for {mentor_email}")
        return True
    except Exception as e:
        print(f"❌ Calendar access verification failed for {mentor_email}: {e}")
        return False

def round_to_nearest_hour(dt_obj: datetime, round_up: bool = False) -> datetime:
    """
    Rounds a datetime object to the nearest hour.
    round_up=True => always rounds up to next hour if minutes > 0
    round_up=False => always rounds down to current hour
    """
    dt_obj = dt_obj.replace(second=0, microsecond=0)
    if round_up and dt_obj.minute > 0:
        return dt_obj.replace(minute=0) + timedelta(hours=1)
    return dt_obj.replace(minute=0)

def _ensure_tz(dt_obj: datetime) -> datetime:
    """Ensure datetime is timezone-aware (UK time)"""
    if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
        return dt_obj.replace(tzinfo=UK_TZ)
    return dt_obj

def get_user_last_session_date(user_email: str, mentor_email: str = None) -> Optional[datetime]:
    """
    Get the most recent confirmed session date for a user.
    Now checks ALL mentor calendars or specific mentor if provided.
    """
    try:
        all_sessions = []
        
        # If specific mentor provided, check only their calendar
        if mentor_email:
            calendars_to_check = [mentor_email]
            print(f"📅 Checking last session for {user_email} with mentor {mentor_email}")
        else:
            # Check all mentor calendars
            calendars_to_check = [config["email"] for config in MENTOR_CONFIG.values()]
            print(f"📅 Checking last session for {user_email} in all calendars: {calendars_to_check}")
        
        for calendar_email in calendars_to_check:
            try:
                service, mentor_config = get_calendar_service(calendar_email)
                calendar_id = mentor_config["calendar_id"]
                
                # Search for past events where this user was an attendee
                now = datetime.now(UK_TZ)
                start_search = now - timedelta(days=180)
                
                events = service.events().list(
                    calendarId=calendar_id,
                    timeMin=start_search.isoformat(),
                    timeMax=now.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    q=user_email
                ).execute().get("items", [])
                
                for event in events:
                    attendees = event.get('attendees', [])
                    if any(att.get('email') == user_email and att.get('responseStatus') == 'accepted' 
                           for att in attendees):
                        
                        end_time_str = event.get("end", {}).get("dateTime")
                        if end_time_str:
                            end_time = dt.datetime.fromisoformat(
                                end_time_str.replace("Z", "+00:00")
                            ).astimezone(UK_TZ)
                            all_sessions.append(end_time)
                            print(f"📅 Found session in {calendar_email}: {end_time}")
                            
            except Exception as e:
                print(f"⚠️ Error checking calendar {calendar_email}: {e}")
                continue
        
        if all_sessions:
            last_session = max(all_sessions)
            print(f"📅 Latest session for {user_email}: {last_session}")
            return last_session
        else:
            print(f"📅 No previous sessions found for {user_email}")
            return None
            
    except Exception as e:
        print(f"❌ Error getting last session date: {e}")
        return None

def calculate_earliest_next_session(user_email: str, mentor_email: str = None) -> datetime:
    """
    Calculate the earliest date a user can book their next session
    based on the 7-day gap rule. Now considers specific mentor.
    """
    last_session_end = get_user_last_session_date(user_email, mentor_email)
    now = datetime.now(UK_TZ)
    
    if last_session_end is None:
        print(f"📅 {user_email} - No previous sessions found")
        return now
    
    earliest_next = last_session_end + timedelta(days=MIN_SESSION_GAP_DAYS)
    
    if earliest_next < now:
        return now
    
    print(f"📅 7-day gap enforcement: earliest next session for {user_email} is {earliest_next}")
    return earliest_next

def get_busy_slots(start_ist: datetime, end_ist: datetime, mentor_email: str = None) -> List[Tuple[datetime, datetime]]:
    """Get busy time slots from specific mentor's Google Calendar"""
    service, mentor_config = get_calendar_service(mentor_email)
    calendar_id = mentor_config["calendar_id"]
    
    start_ist = _ensure_tz(start_ist)
    end_ist = _ensure_tz(end_ist)

    events = service.events().list(
        calendarId=calendar_id,
        timeMin=start_ist.isoformat(),
        timeMax=end_ist.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute().get("items", [])

    busy = []
    for e in events:
        s = e.get("start", {}).get("dateTime")
        e_ = e.get("end", {}).get("dateTime")
        if not s or not e_:
            continue
        sdt = dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UK_TZ)
        edt = dt.datetime.fromisoformat(e_.replace("Z", "+00:00")).astimezone(UK_TZ)
        busy.append((sdt, edt))
    return busy

def has_overlap(start_a: datetime, end_a: datetime, ranges: List[Tuple[datetime, datetime]]) -> bool:
    """Check if a time slot overlaps with busy periods"""
    start_a = _ensure_tz(start_a)
    end_a = _ensure_tz(end_a)
    for s, e in ranges:
        s = _ensure_tz(s)
        e = _ensure_tz(e)
        if not (end_a <= s or start_a >= e):
            return True
    return False

def find_next_available_15min_slot(mentor_email: str = None, after: datetime = None) -> Tuple[datetime, datetime]:
    """Find next available 15-minute slot for specific mentor after given datetime."""
    now = after or datetime.now(UK_TZ)
    
    # Scan today and next 3 days
    for day_offset in range(0, 4):
        scan_date = (now + timedelta(days=day_offset)).date()
        
        # Skip if it's today but current time is past 4:45 PM (last slot start)
        if day_offset == 0 and now.hour >= 16 and now.minute >= 45:
            continue
            
        print(f"🔍 Scanning {scan_date} for {mentor_email or 'default'} available slots...")
        
        # Get busy slots for the entire day for this mentor
        day_start = datetime.combine(scan_date, dt.time(9, 0), tzinfo=UK_TZ)
        day_end = datetime.combine(scan_date, dt.time(17, 0), tzinfo=UK_TZ)
        busy_slots = get_busy_slots(day_start, day_end, mentor_email)
        
        # Check each 15-minute slot
        for start_hour, start_min, end_hour, end_min in AVAILABLE_TIME_SLOTS:
            slot_start = datetime(
                year=scan_date.year, 
                month=scan_date.month, 
                day=scan_date.day,
                hour=start_hour, 
                minute=start_min, 
                tzinfo=UK_TZ
            )
            slot_end = datetime(
                year=scan_date.year, 
                month=scan_date.month, 
                day=scan_date.day,
                hour=end_hour, 
                minute=end_min, 
                tzinfo=UK_TZ
            )
            
            # Skip if slot is in the past
            if slot_start <= now:
                continue
                
            # Check if slot is free for this mentor
            if not has_overlap(slot_start, slot_end, busy_slots):
                print(f"✅ Found free slot for {mentor_email or 'default'}: {slot_start.strftime('%Y-%m-%d %I:%M %p')} - {slot_end.strftime('%I:%M %p')}")
                return slot_start, slot_end
            else:
                print(f"❌ Slot busy for {mentor_email or 'default'}: {slot_start.strftime('%Y-%m-%d %I:%M %p')} - {slot_end.strftime('%I:%M %p')}")
    
    # Fallback - schedule for next week Monday 9 AM
    next_monday = now + timedelta(days=(7 - now.weekday()))
    fallback_start = datetime.combine(next_monday.date(), dt.time(9, 0), tzinfo=UK_TZ)
    fallback_end = fallback_start + timedelta(minutes=15)
    
    print(f"⚠️ No slots available this week for {mentor_email or 'default'}. Fallback: {fallback_start}")
    return fallback_start, fallback_end

def get_next_available_slots_for_user(user_email: str, count: int = 5, mentor_email: str = None) -> List[dict]:
    """
    Get multiple available slot options for a user across different days for a specific mentor,
    respecting the 7-day gap from their last session.
    """
    # Use head mentor as default if not specified
    if not mentor_email:
        mentor_email = "sunilramtri000@gmail.com"
    
    earliest_allowed = calculate_earliest_next_session(user_email, mentor_email)
    slots = []
    
    # Start from earliest allowed date
    current_date = earliest_allowed.date()
    days_checked = 0
    max_days_to_check = 30
    
    print(f"📅 Finding {count} slots for {user_email} with mentor {mentor_email} starting from {current_date}")
    
    while len(slots) < count and days_checked < max_days_to_check:
        check_date = current_date + timedelta(days=days_checked)
        
        # Skip weekends
        if check_date.weekday() >= 5:
            days_checked += 1
            continue
        
        print(f"🔍 Checking {check_date} for available slots...")
        
        # Get busy slots for this entire day for the specific mentor
        day_start = datetime.combine(check_date, dt.time(9, 0), tzinfo=UK_TZ)
        day_end = datetime.combine(check_date, dt.time(17, 0), tzinfo=UK_TZ)
        busy_slots = get_busy_slots(day_start, day_end, mentor_email)
        
        # Track slots found for this day
        day_slots_found = 0
        max_slots_per_day = 8  # Max 8 slots per day (2 hours)
        
        # Check each time slot for this day
        for start_hour, start_min, end_hour, end_min in AVAILABLE_TIME_SLOTS:
            if len(slots) >= count or day_slots_found >= max_slots_per_day:
                break
                
            slot_start = datetime(
                year=check_date.year,
                month=check_date.month,
                day=check_date.day,
                hour=start_hour,
                minute=start_min,
                tzinfo=UK_TZ
            )
            slot_end = datetime(
                year=check_date.year,
                month=check_date.month,
                day=check_date.day,
                hour=end_hour,
                minute=end_min,
                tzinfo=UK_TZ
            )
            
            # Skip if before earliest allowed time
            if slot_start < earliest_allowed:
                continue
            
            # Check if slot is available for this mentor
            if not has_overlap(slot_start, slot_end, busy_slots):
                print(f"✅ Found available slot: {slot_start.strftime('%Y-%m-%d %I:%M %p')} - {slot_end.strftime('%I:%M %p')}")
                
                slots.append({
                    "start_time": slot_start,
                    "end_time": slot_end,
                    "formatted_date": slot_start.strftime('%A, %B %d'),
                    "formatted_time": f"{slot_start.strftime('%I:%M %p')} - {slot_end.strftime('%I:%M %p')} UK time",
                    "date_iso": slot_start.date().isoformat(),
                    "is_gap_compliant": slot_start >= earliest_allowed,
                    "day_name": slot_start.strftime('%A'),
                    "full_datetime": slot_start.strftime('%A, %B %d, %Y at %I:%M %p UK time')
                })
                
                day_slots_found += 1
            else:
                print(f"❌ Slot busy: {slot_start.strftime('%Y-%m-%d %I:%M %p')} - {slot_end.strftime('%I:%M %p')}")
        
        days_checked += 1
    
    print(f"📅 Found {len(slots)} available slots for {user_email} with mentor {mentor_email}")
    return slots

def cancel_calendar_event(event_id, mentor_email: str = None):
    """Cancel a Google Calendar event by its ID with proper error handling"""
    if not event_id or event_id.strip() == "":
        print("⚠️ No event_id provided for calendar cancellation")
        return False
        
    try:
        service, mentor_config = get_calendar_service(mentor_email)
        calendar_id = mentor_config["calendar_id"]
        
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        print(f"✅ Successfully cancelled calendar event: {event_id}")
        return True
        
    except Exception as e:
        error_msg = str(e)
        
        if "410" in error_msg or "deleted" in error_msg.lower():
            print(f"ℹ️ Calendar event {event_id} was already deleted")
            return True
        elif "404" in error_msg or "not found" in error_msg.lower():
            print(f"ℹ️ Calendar event {event_id} not found (may have been manually deleted)")
            return True
        elif "403" in error_msg or "forbidden" in error_msg.lower():
            print(f"❌ Access denied for calendar event {event_id}")
            return False
        else:
            print(f"❌ Unexpected error cancelling calendar event {event_id}: {e}")
            return False

def create_enhanced_event(
    summary: str, 
    description: str, 
    start_time_ist: datetime,
    end_time_ist: datetime, 
    attendees: List[str],
    mentor_email: str = None,
    mentor_name: str = None,
    student_name: str = None
) -> dict:
    """Creates enhanced calendar event in specific mentor's calendar with their meet link"""
    
    try:
        service, mentor_config = get_calendar_service(mentor_email)
        calendar_id = mentor_config["calendar_id"]
        meet_link = mentor_config["meet_link"]
        
        # Verify calendar access first
        try:
            service.calendarList().get(calendarId=calendar_id).execute()
        except Exception as e:
            print(f"⚠️ Cannot access calendar {calendar_id}: {e}")
            return {"success": False, "error": f"Calendar access denied: {str(e)}"}
        
        start_time_ist = _ensure_tz(start_time_ist).astimezone(UK_TZ)
        end_time_ist = _ensure_tz(end_time_ist).astimezone(UK_TZ)
        
        # Enhanced description
        duration_mins = int((end_time_ist - start_time_ist).total_seconds() / 60)
        enhanced_description = f"""
📋 MENTORSHIP SESSION DETAILS

👨‍🏫 Mentor: {mentor_name or mentor_config["name"]}
👨‍🎓 Student: {student_name or 'TBD'}
⏱️ Duration: {duration_mins} minutes
🎥 Google Meet: {meet_link}

📧 Attendees:
{chr(10).join([f"• {email}" for email in attendees])}

💡 Session Guidelines:
• Join 5 minutes early
• Come prepared with questions
• Take notes during the session
• Follow up on action items

{description}
"""

        event_body = {
            "summary": summary,
            "description": enhanced_description,
            "start": {"dateTime": start_time_ist.isoformat(), "timeZone": "Europe/London"},
            "end": {"dateTime": end_time_ist.isoformat(), "timeZone": "Europe/London"},
            "location": f"Google Meet - {meet_link}",
            "status": "confirmed",
            "colorId": "2",
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 60},
                    {"method": "popup", "minutes": 15},
                ]
            }
        }

        created = service.events().insert(
            calendarId=calendar_id,
            body=event_body,
            sendUpdates="none"
        ).execute()

        print(f"✅ Event created in {mentor_email or 'default'}'s calendar: {created.get('htmlLink')}")
        return {
            "success": True,
            "event_id": created.get("id"),
            "html_link": created.get("htmlLink"),
            "meet_link": meet_link,
            "calendar_link": created.get("htmlLink"),
            "start_time": start_time_ist,
            "end_time": end_time_ist
        }

    except Exception as e:
        print(f"❌ Error creating enhanced event in {mentor_email or 'default'}'s calendar: {e}")
        return {"success": False, "error": str(e)}

def schedule_specific_slot(student_email: str, mentor_email: str, 
                         slot_start: datetime, slot_end: datetime,
                         student_name: str = None, mentor_name: str = None) -> dict:
    """
    Schedule a session for a specific time slot in the mentor's calendar
    """
    try:
        # Get mentor configuration
        mentor_config = get_mentor_config(mentor_email)
        
        # Verify the slot is still available in this mentor's calendar
        busy_slots = get_busy_slots(
            slot_start - timedelta(minutes=15),
            slot_end + timedelta(minutes=15),
            mentor_email
        )
        
        if has_overlap(slot_start, slot_end, busy_slots):
            return {
                "success": False,
                "error": "Selected time slot is no longer available. Please choose another slot."
            }
        
        # Create attendees list
        attendees = [student_email, mentor_email]
        
        # Create calendar event in mentor's calendar
        summary = f"Mentorship Session: {student_name or 'Student'} & {mentor_name or mentor_config['name']}"
        description = f"15-minute mentorship session between {student_name or 'student'} and {mentor_name or mentor_config['name']}"
        
        event_result = create_enhanced_event(
            summary=summary,
            description=description,
            start_time_ist=slot_start,
            end_time_ist=slot_end,
            attendees=attendees,
            mentor_email=mentor_email,
            mentor_name=mentor_name or mentor_config["name"],
            student_name=student_name
        )
        
        if event_result["success"]:
            return {
                "success": True,
                "message": f"✅ Session confirmed for {slot_start.strftime('%A, %B %d at %I:%M %p')} - {slot_end.strftime('%I:%M %p')} UK time",
                "start_time": slot_start,
                "end_time": slot_end,
                "meet_link": event_result["meet_link"],
                "calendar_link": event_result["calendar_link"],
                "event_id": event_result["event_id"],
                "mentor_name": mentor_name or mentor_config["name"]
            }
        else:
            return {
                "success": False,
                "error": event_result["error"]
            }
            
    except Exception as e:
        print(f"❌ Error scheduling specific slot: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e)
        }

def send_enhanced_manual_invitations(attendees, meet_link, start_time, end_time,
                                     student_name, mentor_name, session_type):
    """
    Send email invitations with 'Add to Google Calendar' button.
    """
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    import smtplib
    import ssl

    def generate_google_calendar_url(summary, start_time, end_time, description, location=None):
        start_str = start_time.strftime("%Y%m%dT%H%M%S")
        end_str = end_time.strftime("%Y%m%dT%H%M%S")
        url = (
            "https://www.google.com/calendar/render?action=TEMPLATE"
            f"&text={quote(summary)}"
            f"&dates={start_str}/{end_str}"
            f"&details={quote(description)}"
            f"&location={quote(location or '')}"
            "&sf=true&output=xml"
        )
        return url

    # Validate and clean attendees list
    cleaned_attendees = []
    for email in attendees:
        if email and isinstance(email, str):
            email = email.strip()
            if email and "@" in email and "." in email:
                cleaned_attendees.append(email)
            else:
                print(f"⚠️ Skipping invalid email: {email}")
        else:
            print(f"⚠️ Skipping non-string email: {email}")
    
    if not cleaned_attendees:
        print("❌ No valid email addresses to send to")
        return False

    subject = f"📅 Mentorship Session Confirmation: {session_type}"

    # Prepare calendar URL
    calendar_url = generate_google_calendar_url(
        summary=f"Mentorship Session: {student_name} & {mentor_name}",
        start_time=start_time,
        end_time=end_time,
        description=f"Mentorship session with {mentor_name} & {student_name}. Join via Google Meet: {meet_link}",
        location=meet_link
    )

    # Email HTML body
    body = f"""
    <html>
    <body>
    <p>Hello,</p>
    <p>Your mentorship session has been scheduled!</p>
    
    <p>
    🧑‍🎓 <strong>Student:</strong> {student_name}<br>
    🎓 <strong>Mentor:</strong> {mentor_name}<br>
    🗓 <strong>Date:</strong> {start_time.strftime('%A, %d %B %Y')}<br>
    ⏰ <strong>Time:</strong> {start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')} UK Time<br>
    📍 <strong>Meet Link:</strong> <a href="{meet_link}">{meet_link}</a>
    </p>

    <p>
    <a href="{calendar_url}" 
       style="display:inline-block;padding:10px 20px;background-color:#1a73e8;color:white;text-decoration:none;border-radius:5px;">
    Add to Google Calendar
    </a>
    </p>

    <p>Thank you for booking!</p>
    </body>
    </html>
    """

    # Plain text version
    text_body = f"""
Hello,

Your mentorship session has been scheduled!

Student: {student_name}
Mentor: {mentor_name}
Date: {start_time.strftime('%A, %d %B %Y')}
Time: {start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')} UK Time
Meet Link: {meet_link}

Add to Calendar: {calendar_url}

Thank you for booking!
"""

    # Send email using SMTP
    try:
        # Create SMTP connection - FIXED: removed context parameter from starttls()
        server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT)
        server.ehlo()
        server.starttls()  # No context parameter needed
        server.ehlo()  # Re-identify after starttls
        server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)

        sent_count = 0
        failed_emails = []
        
        for recipient in cleaned_attendees:
            try:
                msg = MIMEMultipart('alternative')
                msg['From'] = settings.EMAIL_HOST_USER
                msg['To'] = recipient
                msg['Subject'] = subject
                
                # Attach both plain text and HTML versions
                part1 = MIMEText(text_body, 'plain')
                part2 = MIMEText(body, 'html')
                msg.attach(part1)
                msg.attach(part2)

                server.send_message(msg)
                sent_count += 1
                print(f"✅ Email sent to: {recipient}")
                
            except Exception as e:
                print(f"❌ Failed to send to {recipient}: {e}")
                failed_emails.append(recipient)

        server.quit()
        
        print(f"📧 Emails sent: {sent_count}/{len(cleaned_attendees)}")
        if failed_emails:
            print(f"⚠️ Failed recipients: {', '.join(failed_emails)}")
        
        return sent_count > 0  # Return True if at least one email was sent

    except Exception as e:
        print(f"❌ SMTP Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def send_via_fallback_smtp(subject, html_body, text_body, recipients, sender_email, sender_password):
    """
    Fallback method to send email using direct SMTP connection
    """
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    import smtplib
    import ssl
    
    try:
        # Connect to Gmail's SMTP server using TLS
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()  # Remove the context parameter
            server.login(sender_email, sender_password)
            
            for recipient in recipients:
                # Create message
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = sender_email
                msg['To'] = recipient
                
                # Attach text and HTML versions
                part1 = MIMEText(text_body, 'plain')
                part2 = MIMEText(html_body, 'html')
                msg.attach(part1)
                msg.attach(part2)
                
                # Send email
                server.send_message(msg)
                print(f"📧 Fallback email sent to {recipient}")
                
        return True
        
    except Exception as e:
        print(f"❌ Fallback SMTP error: {e}")
        return False
    
def get_available_days_for_user(user_email: str, mentor_email: str = None, max_days: int = 7) -> List[dict]:
    """Get list of days that have available slots for a user with specific mentor"""
    if not mentor_email:
        mentor_email = "sunilramtri000@gmail.com"
        
    earliest_allowed = calculate_earliest_next_session(user_email, mentor_email)
    available_days = []
    
    current_date = earliest_allowed.date()
    days_checked = 0
    
    while len(available_days) < max_days and days_checked < 14:
        check_date = current_date + timedelta(days=days_checked)
        
        if check_date.weekday() >= 5:
            days_checked += 1
            continue
        
        day_slots = get_slots_for_specific_day_helper(user_email, check_date, mentor_email)
        if day_slots:
            available_days.append({
                "day": check_date.strftime('%A'),
                "date": check_date.isoformat(),
                "formatted": check_date.strftime('%A, %B %d'),
                "slots_count": len(day_slots)
            })
        
        days_checked += 1
    
    return available_days

def get_slots_for_specific_day_helper(student_email: str, target_date, mentor_email: str):
    earliest_allowed = calculate_earliest_next_session(student_email, mentor_email)

    if not mentor_email:
        mentor_email = "sunilramtri000@gmail.com"
        
    if isinstance(target_date, str):
        days_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 
            'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
        }
        if target_date.lower() in days_map:
            today = datetime.now(UK_TZ)
            target_weekday = days_map[target_date.lower()]
            current_weekday = today.weekday()
            
            days_ahead = target_weekday - current_weekday
            if days_ahead <= 0:
                days_ahead += 7
            target_date = (today + timedelta(days=days_ahead)).date()
    
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    
    print(f"🔍 Checking slots for {target_date} with mentor {mentor_email}")
    
    day_start = datetime.combine(target_date, dt.time(9, 0), tzinfo=UK_TZ)
    day_end = datetime.combine(target_date, dt.time(17, 0), tzinfo=UK_TZ)
    busy_slots = get_busy_slots(day_start, day_end, mentor_email)
    
    available_slots = []
    
    # Loop through fixed available slots
    for start_hour, start_min, end_hour, end_min in AVAILABLE_TIME_SLOTS:
        slot_start = datetime(target_date.year, target_date.month, target_date.day,
                              start_hour, start_min, tzinfo=UK_TZ)
        slot_end = datetime(target_date.year, target_date.month, target_date.day,
                            end_hour, end_min, tzinfo=UK_TZ)
        
        # Respect earliest allowed session
        if slot_start < earliest_allowed:
            continue
        
        if not has_overlap(slot_start, slot_end, busy_slots):
            available_slots.append({
                "start_time": slot_start,
                "end_time": slot_end,
                "formatted_date": slot_start.strftime('%A, %B %d'),
                "formatted_time": f"{slot_start.strftime('%I:%M %p')} - {slot_end.strftime('%I:%M %p')} UK time",
            })
    
    return available_slots

def get_google_calendar_service():
    """Alias for get_calendar_service() for backward compatibility"""
    return get_calendar_service()

def schedule_mentorship_session(student_email, mentor_email, student_name, mentor_name, selected_slot=None):
    """
    Create mentorship session in Google Calendar and send enhanced email invitations.
    """
    try:
        print("📧 Raw Emails =>", student_email, mentor_email)

        # Validate and clean emails
        attendees = [student_email, mentor_email]
        attendees = [e.strip() for e in attendees if e and "@" in e]

        print("📧 Cleaned Attendees =>", attendees)

        if len(attendees) < 2:
            return {
                "success": False,
                "error": f"Invalid attendee emails. Got: {student_email}, {mentor_email}"
            }

        # Use selected slot if given, otherwise find next available
        if selected_slot:
            slot_start = selected_slot["start_time"]
            slot_end = selected_slot["end_time"]
        else:
            slot_start, slot_end = find_next_available_15min_slot(mentor_email)

        # Create calendar event using create_enhanced_event
        summary = f"Mentorship Session: {student_name} & {mentor_name}"
        description = f"15-minute mentorship session between {student_name} and {mentor_name}"
        
        event_result = create_enhanced_event(
            summary=summary,
            description=description,
            start_time_ist=slot_start,
            end_time_ist=slot_end,
            attendees=attendees,
            mentor_email=mentor_email,
            mentor_name=mentor_name,
            student_name=student_name
        )
        
        if not event_result["success"]:
            return event_result

        # Send enhanced invitations
        print("📧 Sending email invitations to:", attendees)
        send_enhanced_manual_invitations(
            attendees=attendees,
            meet_link=event_result["meet_link"],
            start_time=slot_start,
            end_time=slot_end,
            student_name=student_name,
            mentor_name=mentor_name,
            session_type="15-minute mentorship session"
        )

        return {
            "success": True,
            "message": "Session scheduled successfully",
            "start_time": slot_start,
            "end_time": slot_end,
            "meet_link": event_result["meet_link"],
            "calendar_link": event_result["calendar_link"],
            "event_id": event_result["event_id"]
        }

    except Exception as e:
        print("❌ Exception in schedule_mentorship_session:", str(e))
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

MAX_RETRIES = 5
import time
from django.db import transaction, OperationalError
def book_time_slot(slot_id, user, mentor):
    """
    Book a time slot — retry-safe, emails sent after commit.
    """
    for attempt in range(MAX_RETRIES):
        try:
            with transaction.atomic():
                print(f"🔧 Booking attempt {attempt+1} for slot {slot_id}")

                slot = TimeSlot.objects.select_for_update().get(
                    id=slot_id,
                    is_available=True,
                    is_booked=False
                )

                if slot.mentor != mentor:
                    raise ValidationError("Slot does not belong to this mentor.")

                slot_duration = (
                    datetime.combine(slot.date, slot.end_time) -
                    datetime.combine(slot.date, slot.start_time)
                ).total_seconds() / 60
                if slot_duration != 15:
                    raise ValidationError("Slot duration must be 15 minutes.")

                # Create booking
                booking = EnhancedSessionBooking.objects.create(
                    user=user.user,
                    mentor=mentor,
                    start_time=datetime.combine(slot.date, slot.start_time, tzinfo=UK_TZ),
                    end_time=datetime.combine(slot.date, slot.end_time, tzinfo=UK_TZ),
                    duration_minutes=15,
                    meet_link=get_mentor_config(mentor.user.email).get("meet_link", "https://meet.google.com/default"),
                    attendees=[user.user.email, mentor.user.email],
                )

                # Mark slot as booked
                slot.is_booked = True
                slot.is_available = False
                slot.booking = booking
                slot.save()

                # ✅ Schedule emails AFTER commit
                transaction.on_commit(lambda: send_booking_emails(booking, user, mentor))

                print("✅ Slot booked successfully (DB transaction complete).")
                return booking

        except TimeSlot.DoesNotExist:
            raise ValidationError("This slot is already booked.")
        except OperationalError as e:
            if "database is locked" in str(e).lower():
                print(f"⚠️ SQLite locked, retrying ({attempt+1}/{MAX_RETRIES})...")
                time.sleep(0.2 * (attempt + 1))
                continue
            else:
                raise
        except Exception as e:
            print(f"❌ Booking error: {e}")
            raise

    raise ValidationError("System busy. Please try again in a few seconds.")

from django.core.mail import EmailMultiAlternatives
from django.conf import settings

def send_booking_emails(booking, user_profile, mentor):
    """
    Send confirmation emails to student and mentor after booking.
    Runs after transaction commit to avoid DB locks.
    Python 3.11+ compatible - no keyfile parameter.
    """
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from django.conf import settings
        
        attendees = [user_profile.user.email, mentor.user.email]
        meet_link = booking.meet_link
        subject = f"Session Confirmed with {mentor.get_display_name()}"
        from_email = settings.EMAIL_HOST_USER

        text_body = (
            f"Hi {user_profile.user.first_name or user_profile.user.username},\n\n"
            f"Your session with {mentor.get_display_name()} is confirmed.\n\n"
            f"Date: {booking.start_time.strftime('%A, %B %d, %Y')}\n"
            f"Time: {booking.start_time.strftime('%I:%M %p')} UK Time\n"
            f"Meet Link: {meet_link}\n\n"
            f"Best,\nTeam"
        )

        html_body = f"""
        <html>
        <body>
            <p>Hi {user_profile.user.first_name or user_profile.user.username},</p>
            <p>Your session with <b>{mentor.get_display_name()}</b> is confirmed.</p>
            <p>
                <b>Date:</b> {booking.start_time.strftime('%A, %B %d, %Y')}<br>
                <b>Time:</b> {booking.start_time.strftime('%I:%M %p')} UK Time<br>
                <b>Meet Link:</b> <a href="{meet_link}">{meet_link}</a>
            </p>
            <p>Best,<br>Team</p>
        </body>
        </html>
        """

        # Create SMTP connection - Python 3.11+ compatible
        server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT)
        server.ehlo()
        server.starttls()  # No parameters needed
        server.ehlo()  # Re-identify after starttls
        server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)

        sent_count = 0
        for recipient in attendees:
            try:
                msg = MIMEMultipart('alternative')
                msg['From'] = from_email
                msg['To'] = recipient
                msg['Subject'] = subject
                
                msg.attach(MIMEText(text_body, 'plain'))
                msg.attach(MIMEText(html_body, 'html'))
                
                server.send_message(msg)
                sent_count += 1
                print(f"✅ Email sent to: {recipient}")
                
            except Exception as e:
                print(f"❌ Failed to send to {recipient}: {e}")

        server.quit()
        print(f"📧 Emails sent: {sent_count}/{len(attendees)}")
        return sent_count > 0

    except Exception as e:
        print(f"❌ Failed to send booking emails: {e}")
        import traceback
        traceback.print_exc()
        return False

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from django.conf import settings

def send_booking_emails_smtp(booking, user_profile, mentor):
    """
    Send confirmation emails to student and mentor using smtplib.
    Fully compatible with Python 3.11+ (no keyfile error).
    """
    try:
        attendees = [user_profile.user.email, mentor.user.email]
        meet_link = booking.meet_link

        subject = f"Session Confirmed with {mentor.get_display_name()}"
        from_email = settings.EMAIL_HOST_USER

        # Plain text body
        text_body = (
            f"Hi {user_profile.user.first_name or user_profile.user.username},\n\n"
            f"Your session with {mentor.get_display_name()} is confirmed.\n\n"
            f"Date: {booking.start_time.strftime('%A, %B %d, %Y')}\n"
            f"Time: {booking.start_time.strftime('%I:%M %p')} UK Time\n"
            f"Meet Link: {meet_link}\n\n"
            f"Best,\nTeam"
        )

        # HTML body
        html_body = f"""
        <html>
        <body>
        <p>Hi {user_profile.user.first_name or user_profile.user.username},</p>
        <p>Your session with <b>{mentor.get_display_name()}</b> is confirmed.</p>
        <p>
            <b>Date:</b> {booking.start_time.strftime('%A, %B %d, %Y')}<br>
            <b>Time:</b> {booking.start_time.strftime('%I:%M %p')} UK Time<br>
            <b>Meet Link:</b> <a href="{meet_link}">{meet_link}</a>
        </p>
        <p>Best,<br>Team</p>
        </body>
        </html>
        """

        # Create email message
        msg = MIMEMultipart('alternative')
        msg['From'] = from_email
        msg['To'] = ", ".join(attendees)
        msg['Subject'] = subject
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))

        # Setup SMTP with TLS context (Python 3.11+ safe)
        context = ssl.create_default_context()
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.starttls(context=context)  # ✅ TLS without keyfile
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.send_message(msg)

        print(f"✅ Emails sent to: {attendees}")
        return True

    except Exception as e:
        print(f"❌ Failed to send booking emails: {e}")
        import traceback
        traceback.print_exc()
        return False

# In calendar_client.py

def send_cancellation_notifications(attendees, student_name, mentor_name, formatted_time):
    """
    Send cancellation email notifications to attendees
    Uses the same SMTP setup as send_enhanced_manual_invitations
    """
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from django.conf import settings
        
        print(f"📧 [CANCEL EMAIL] Sending to: {attendees}")
        
        # Connect to SMTP server (same as booking emails)
        server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT)
        server.starttls()
        server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
        
        sent_count = 0
        
        for recipient in attendees:
            try:
                msg = MIMEMultipart('alternative')
                msg['From'] = settings.EMAIL_HOST_USER
                msg['To'] = recipient
                msg['Subject'] = f"🚫 Session Cancelled - {student_name} & {mentor_name}"
                
                # Determine if recipient is student or mentor
                is_student = recipient == attendees[0] if len(attendees) > 0 else True
                recipient_name = student_name if is_student else mentor_name
                other_person = mentor_name if is_student else student_name
                
                # Email body
                text_body = f"""Hi {recipient_name},

Your mentorship session on {formatted_time} with {other_person} has been cancelled.

If you want to reschedule, please login to your account and book a new slot.

Thanks,
UK Jobs Mentorship Team"""
                
                html_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 10px;">
                        <h2 style="color: #d9534f;">🚫 Session Cancelled</h2>
                        <p>Hi {recipient_name},</p>
                        <p>Your mentorship session on <strong>{formatted_time}</strong> with <strong>{other_person}</strong> has been cancelled.</p>
                        <p>If you want to reschedule, please login to your account and book a new slot.</p>
                        <hr style="border: 1px solid #eee; margin: 20px 0;">
                        <p style="color: #666; font-size: 12px;">
                            Thanks,<br>
                            UK Jobs Mentorship Team
                        </p>
                    </div>
                </body>
                </html>
                """
                
                msg.attach(MIMEText(text_body, 'plain'))
                msg.attach(MIMEText(html_body, 'html'))
                
                server.send_message(msg)
                print(f"✅ Cancellation email sent to: {recipient}")
                sent_count += 1
                
            except Exception as recipient_error:
                print(f"❌ Failed to send to {recipient}: {recipient_error}")
        
        server.quit()
        print(f"📧 Cancellation emails sent: {sent_count}/{len(attendees)}")
        
        return sent_count > 0
        
    except Exception as e:
        print(f"❌ [CANCEL EMAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False