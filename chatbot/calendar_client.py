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

BASE_DIR = Path(__file__).resolve().parent.parent
from zoneinfo import ZoneInfo
UK_TZ = ZoneInfo("Europe/London")
# MENTOR CONFIGURATION - Add new mentors here
MENTOR_CONFIG = {
    "head": {
        "name": "Vardaan (Head Mentor)",
        "email": "vardaan@ukjobsinsider.com",
        "credentials_file": "credentials_vardaan.json",
        "meet_link": "https://meet.google.com/head-mentor-link",
        "calendar_id": "vardaan@ukjobsinsider.com"
    },
    #  "vaidaansh": {
    #     "name": "Vaidaansh Mentor", 
    #     "email": "vaidaansh1shekhawat@gmail.com",
    #     "credentials_file": "credentials_vaidaansh.json",
    #     "meet_link": "https://meet.google.com/gbv-mkux-scx",
    #     "calendar_id": "vaidaansh1shekhawat@gmail.com"
    # },
    "kapil": {
        "name": "kapil Mentor", 
        "email": "kapilsanjaykanjani@gmail.com",
        "credentials_file": "credentials_kapil.json",
        "meet_link": "https://meet.google.com/gbv-mkux-scx",
        "calendar_id": "kapilsanjaykanjani@gmail.com"
    },
    "meena": {
        "name": "Meena Mentor", 
        "email": "meenavalavala@gmail.com",  # Updated with actual email
        "credentials_file": "credentials1.json",
        "meet_link": "https://meet.google.com/csx-bkoy-sct",
        "calendar_id": "meenavalavala@gmail.com"  # Updated with actual email
    },
        "amit": {
        "name": "amit Mentor", 
        "email": "sunilramtri000@gmail.com",  # Updated with actual email
        "credentials_file": "credentials.json",
        "meet_link": "https://meet.google.com/csx-bkoy-sct",
        "calendar_id": "sunilramtri000@gmail.com"  # Updated with actual email
    },
        "Simran": {
        "name": "Simran Mentor", 
        "email": "simranchetanshah98@gmail.com",  # Updated with actual email
        "credentials_file": "credentials_simran.json",
        "meet_link": "https://meet.google.com/vbu-xbhk-dji",
        "calendar_id": "simranchetanshah98@gmail.com"  # Updated with actual email
    }
}

# Fallback configuration (your original setup)
DEFAULT_MENTOR_CONFIG = {
    "credentials_file": "credentials1.json",
    "meet_link": "https://meet.google.com/csx-bkoy-sct",
    "calendar_id": "meenavalavala@gmail.com"
}

# 2-hour time slots (9 AM - 5 PM)
AVAILABLE_TIME_SLOTS = [
    (9, 0, 11, 0),   # 9:00 AM - 11:00 AM
    (11, 0, 13, 0),  # 11:00 AM - 1:00 PM  
    (13, 0, 15, 0),  # 1:00 PM - 3:00 PM
    (15, 0, 17, 0),  # 3:00 PM - 5:00 PM
]

# Minimum gap between sessions (7 days)
MIN_SESSION_GAP_DAYS = 7

# Add this debug function in calendar_client.py
# def debug_mentor_matching(mentor_email: str):
#     """Debug mentor configuration matching"""
#     print(f"🔍 [DEBUG] Looking for mentor: '{mentor_email}'")
#     print(f"🔍 [DEBUG] Available mentors:")
    
#     for mentor_key, config in MENTOR_CONFIG.items():
#         config_email = config["email"]
#         print(f"  - {mentor_key}: '{config_email}' (match: {config_email.lower() == mentor_email.lower()})")


# Test this in Django shell:

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
        "calendar_id": DEFAULT_MENTOR_CONFIG["calendar_id"]
    }

def get_calendar_service(mentor_email: str = None):
    """
    Get Google Calendar service for specific mentor.
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
                print(f"[DEBUG] get_user_last_session_date(student={user_email}, mentor={mentor_email})")

                
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

def find_next_available_2hour_slot(mentor_email: str = None, after: datetime = None) -> Tuple[datetime, datetime]:
    """Find next available 2-hour slot for specific mentor after given datetime."""
    now = after or datetime.now(UK_TZ)
    
    # Scan today and next 3 days
    for day_offset in range(0, 4):
        scan_date = (now + timedelta(days=day_offset)).date()
        
        # Skip if it's today but current time is past 3 PM (last slot start)
        if day_offset == 0 and now.hour >= 15:
            continue
            
        print(f"🔍 Scanning {scan_date} for {mentor_email or 'default'} available slots...")
        
        # Get busy slots for the entire day for this mentor
        day_start = datetime.combine(scan_date, dt.time(9, 0), tzinfo=UK_TZ)
        day_end = datetime.combine(scan_date, dt.time(17, 0), tzinfo=UK_TZ)
        busy_slots = get_busy_slots(day_start, day_end, mentor_email)
        
        # Check each 2-hour slot
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
    fallback_end = fallback_start + timedelta(hours=2)
    
    print(f"⚠️ No slots available this week for {mentor_email or 'default'}. Fallback: {fallback_start}")
    return fallback_start, fallback_end

def get_next_available_slots_for_user(user_email: str, count: int = 5, mentor_email: str = None) -> List[dict]:
    """
    Get multiple available slot options for a user across different days for a specific mentor,
    respecting the 7-day gap from their last session.
    """
    # Use head mentor as default if not specified
    if not mentor_email:
        mentor_email = "vardaan@ukjobsinsider.com"
    
    # FIXED: Pass mentor_email to calculate earliest session
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
        max_slots_per_day = 2
        
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
                    "full_datetime": slot_start.strftime('%A, %B %d, %Y at %I:%M %p UK_TZ')
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
    
    service, mentor_config = get_calendar_service(mentor_email)
    calendar_id = mentor_config["calendar_id"]
    meet_link = mentor_config["meet_link"]
    
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
        "start": {"dateTime": start_time_ist.isoformat(), "timeZone": "Europe/London"},  # FIXED: Changed from start_time_uk
        "end": {"dateTime": end_time_ist.isoformat(), "timeZone": "Europe/London"},      # FIXED: Changed from end_time_uk
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

    try:
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
            slot_start - timedelta(hours=1),
            slot_end + timedelta(hours=1),
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
        description = f"2-hour mentorship session between {student_name or 'student'} and {mentor_name or mentor_config['name']}"
        
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
                "message": f"✅ Session confirmed for {slot_start.strftime('%A, %B %d at %I:%M %p')} - {slot_end.strftime('%I:%M %p')} UK Tine",
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
    Hello,<br><br>
    Your mentorship session has been scheduled!<br><br>

    🧑‍🎓 Student: {student_name}<br>
    🎓 Mentor: {mentor_name}<br>
    🗓 Date: {start_time.strftime('%A, %d %B %Y')}<br>
    ⏰ Time: {start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')} UK Time<br>
    📍 Meet Link: <a href="{meet_link}">{meet_link}</a><br><br>

    <a href="{calendar_url}" 
       style="display:inline-block;padding:10px 20px;background-color:#1a73e8;color:white;text-decoration:none;border-radius:5px;">
    Add to Google Calendar
    </a><br><br>

    Thank you for booking!
    """

    # Send email
    try:
        server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT)
        server.ehlo()
        context = ssl.create_default_context()
        server.starttls(context=context)
        server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)

        sent_count = 0
        for recipient in attendees:
            msg = MIMEMultipart()
            msg['From'] = settings.EMAIL_HOST_USER
            msg['To'] = recipient
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'html'))

            server.sendmail(settings.EMAIL_HOST_USER, recipient, msg.as_string())
            sent_count += 1

        server.quit()
        print(f"📧 Emails sent: {sent_count}/{len(attendees)}")
        return sent_count == len(attendees)

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False

# Helper functions for specific day/calendar operations
def get_available_days_for_user(user_email: str, mentor_email: str = None, max_days: int = 7) -> List[dict]:
    """Get list of days that have available slots for a user with specific mentor"""
    if not mentor_email:
        mentor_email = "vardaan@ukjobsinsider.com"
        
    # FIX 3: Pass mentor_email to calculate_earliest_next_session    
    earliest_allowed = calculate_earliest_next_session(user_email, mentor_email)
    available_days = []
    
    current_date = earliest_allowed.date()
    days_checked = 0
    
    while len(available_days) < max_days and days_checked < 14:
        check_date = current_date + timedelta(days=days_checked)
        
        if check_date.weekday() >= 5:
            days_checked += 1
            continue
        
        # FIX 4: Pass mentor_email to the helper function
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
    # FIX 1: Pass mentor_email to calculate_earliest_next_session
    earliest_allowed = calculate_earliest_next_session(student_email, mentor_email)

    if not mentor_email:
        mentor_email = "vardaan@ukjobsinsider.com"
        
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
    
    # FIX 2: Use the correct mentor_email for busy slots check
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

# Backward compatibility functions
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
            slot_start, slot_end = find_next_available_2hour_slot(mentor_email)

        # Create calendar event using create_enhanced_event
        summary = f"Mentorship Session: {student_name} & {mentor_name}"
        description = f"2-hour mentorship session between {student_name} and {mentor_name}"
        
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
            session_type="1-on-1 Mentorship"
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