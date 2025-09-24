from django.conf import settings
from typing import List, Tuple, Optional
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone
import datetime as dt  # Add this for type a # Add this import for type annotations
from django.core.mail import EmailMessage
from typing import List,Tuple
import ssl
from urllib.parse import quote
from .utils import cancel_calendar_event  # agar aapne utility function banaya hai

BASE_DIR = Path(__file__).resolve().parent.parent
SERVICE_ACCOUNT_FILE = BASE_DIR / "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_ID = "sunilramtri000@gmail.com"  # organizer email
IST = timezone(timedelta(hours=5, minutes=30))

# Fixed Meet link
FIXED_MEET_LINK = "https://meet.google.com/zui-xrya-abg"

# 2-hour time slots (9 AM - 5 PM)
AVAILABLE_TIME_SLOTS = [
    (9, 0, 11, 0),   # 9:00 AM - 11:00 AM
    (11, 0, 13, 0),  # 11:00 AM - 1:00 PM  
    (13, 0, 15, 0),  # 1:00 PM - 3:00 PM
    (15, 0, 17, 0),  # 3:00 PM - 5:00 PM
]

# Minimum gap between sessions (7 days)
MIN_SESSION_GAP_DAYS = 7

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

def send_calendar_invite(attendees: list, subject: str, start_time: datetime, end_time: datetime, description: str, meet_link: str):
    """
    Send an email with Google Calendar event link to all attendees.
    """
    try:
        # Format times in ISO for Google Calendar
        start_utc = start_time.strftime('%Y%m%dT%H%M%SZ')
        end_utc = end_time.strftime('%Y%m%dT%H%M%SZ')

        # Google Calendar link
        calendar_url = (
            f"https://www.google.com/calendar/render?action=TEMPLATE"
            f"&text={quote(subject)}"
            f"&dates={start_utc}/{end_utc}"
            f"&details={quote(description)}"
            f"&location={quote(meet_link)}"
            f"&trp=true"
        )

        # Email body
        body = f"""
Hi,

You have a mentorship session scheduled.

🗓 Date & Time: {start_time.strftime('%A, %B %d at %I:%M %p')} - {end_time.strftime('%I:%M %p')} IST
👥 Attendees: {', '.join(attendees)}
🔗 Meet Link: {meet_link}

Add to your calendar: {calendar_url}

Thanks,
Mentorship Team
        """

        email = EmailMessage(
            subject=subject,
            body=body,
            from_email=None,  # will use settings.EMAIL_HOST_USER
            to=attendees
        )
        email.send(fail_silently=False)
        return True
    except Exception as e:
        print("Error sending calendar invite:", e)
        return False
    
def _ensure_tz(dt_obj: datetime) -> datetime:
    """Ensure datetime is timezone-aware (IST)"""
    if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
        return dt_obj.replace(tzinfo=IST)
    return dt_obj

def generate_google_calendar_url(summary, start_time, end_time, description, location=None):
    """
    Returns a Google Calendar URL for 'Add to Calendar'.
    """
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

def get_calendar_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(f"Credentials file not found: {SERVICE_ACCOUNT_FILE}")
    
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
    )
    service = build("calendar", "v3", credentials=credentials)
    return service


def get_user_last_session_date(user_email: str) -> Optional[datetime]:
    """
    Get the most recent confirmed session date for a user.
    Returns the end time of their last session.
    """
    try:
        service = get_calendar_service()
        
        # Search for past events where this user was an attendee
        now = datetime.now(IST)
        # Look back 6 months to find recent sessions
        start_search = now - timedelta(days=180)
        
        events = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start_search.isoformat(),
            timeMax=now.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            q=user_email  # Search for events containing user's email
        ).execute().get("items", [])
        
        user_sessions = []
        for event in events:
            # Check if user is in attendees and event is confirmed
            attendees = event.get('attendees', [])
            if any(att.get('email') == user_email and att.get('responseStatus') == 'accepted' 
                   for att in attendees):
                
                end_time_str = event.get("end", {}).get("dateTime")
                if end_time_str:
                    end_time = dt.datetime.fromisoformat(
                        end_time_str.replace("Z", "+00:00")
                    ).astimezone(IST)
                    user_sessions.append(end_time)
        
        if user_sessions:
            # Return the most recent session end time
            last_session = max(user_sessions)
            print(f"📅 Found last session for {user_email}: {last_session}")
            return last_session
        else:
            print(f"📅 No previous sessions found for {user_email}")
            return None
            
    except Exception as e:
        print(f"❌ Error getting last session date: {e}")
        return None


def calculate_earliest_next_session(user_email: str) -> datetime:
    """
    Calculate the earliest date a user can book their next session
    based on the 7-day gap rule.
    """
    last_session_end = get_user_last_session_date(user_email)
    now = datetime.now(IST)
    
    if last_session_end is None:
        # First-time user - can book anytime from today
        return now
    
    # Add 7-day gap to last session date
    earliest_next = last_session_end + timedelta(days=MIN_SESSION_GAP_DAYS)
    
    # If earliest_next is in the past, use current time
    if earliest_next < now:
        return now
    
    print(f"📅 7-day gap enforcement: earliest next session for {user_email} is {earliest_next}")
    return earliest_next


def get_busy_slots(start_ist: datetime, end_ist: datetime) -> List[Tuple[datetime, datetime]]:
    """Get busy time slots from Google Calendar (all tz-aware)"""
    service = get_calendar_service()  # your existing function
    start_ist = _ensure_tz(start_ist)
    end_ist = _ensure_tz(end_ist)

    events = service.events().list(
        calendarId=CALENDAR_ID,
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
        sdt = dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(IST)
        edt = dt.datetime.fromisoformat(e_.replace("Z", "+00:00")).astimezone(IST)
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


def find_next_available_2hour_slot(after: datetime = None) -> Tuple[datetime, datetime]:
    """Find next available 2-hour slot after given datetime."""
    now = after or datetime.now(IST)
    
    # Scan today and next 3 days
    for day_offset in range(0, 4):
        scan_date = (now + timedelta(days=day_offset)).date()
        
        # Skip if it's today but current time is past 3 PM (last slot start)
        if day_offset == 0 and now.hour >= 15:
            continue
            
        print(f"🔍 Scanning {scan_date} for available slots...")
        
        # Get busy slots for the entire day
        day_start = datetime.combine(scan_date, dt.time(9, 0), tzinfo=IST)
        day_end = datetime.combine(scan_date, dt.time(17, 0), tzinfo=IST)
        busy_slots = get_busy_slots(day_start, day_end)
        
        # Check each 2-hour slot
        for start_hour, start_min, end_hour, end_min in AVAILABLE_TIME_SLOTS:
            slot_start = datetime(
                year=scan_date.year, 
                month=scan_date.month, 
                day=scan_date.day,
                hour=start_hour, 
                minute=start_min, 
                tzinfo=IST
            )
            slot_end = datetime(
                year=scan_date.year, 
                month=scan_date.month, 
                day=scan_date.day,
                hour=end_hour, 
                minute=end_min, 
                tzinfo=IST
            )
            
            # Skip if slot is in the past
            if slot_start <= now:
                continue
                
            # Check if slot is free
            if not has_overlap(slot_start, slot_end, busy_slots):
                print(f"✅ Found free slot: {slot_start.strftime('%Y-%m-%d %I:%M %p')} - {slot_end.strftime('%I:%M %p')}")
                return slot_start, slot_end
            else:
                print(f"❌ Slot busy: {slot_start.strftime('%Y-%m-%d %I:%M %p')} - {slot_end.strftime('%I:%M %p')}")
    
    # Fallback - schedule for next week Monday 9 AM
    next_monday = now + timedelta(days=(7 - now.weekday()))
    fallback_start = datetime.combine(next_monday.date(), dt.time(9, 0), tzinfo=IST)
    fallback_end = fallback_start + timedelta(hours=2)
    
    print(f"⚠️ No slots available this week. Fallback: {fallback_start}")
    return fallback_start, fallback_end

def get_google_calendar_service():
    """Alias for get_calendar_service() for backward compatibility"""
    return get_calendar_service()

def cancel_calendar_event(event_id):
    """Cancel a Google Calendar event by its ID"""
    try:
        service = get_calendar_service()
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        return True
    except Exception as e:
        print(f"Error cancelling event {event_id}: {e}")
        return False
    
def get_next_available_slots_for_user(user_email: str, count: int = 5) -> List[dict]:
    """
    Get multiple available slot options for a user across different days,
    respecting the 7-day gap from their last session.
    """
    earliest_allowed = calculate_earliest_next_session(user_email)
    slots = []
    
    # Start from earliest allowed date
    current_date = earliest_allowed.date()
    days_checked = 0
    max_days_to_check = 30  # Check up to 30 days
    
    print(f"📅 Finding {count} slots for {user_email} starting from {current_date}")
    
    while len(slots) < count and days_checked < max_days_to_check:
        check_date = current_date + timedelta(days=days_checked)
        
        # Skip weekends (optional - remove if you want weekend slots)
        if check_date.weekday() >= 5:  # Saturday=5, Sunday=6
            days_checked += 1
            continue
        
        print(f"🔍 Checking {check_date} for available slots...")
        
        # Get busy slots for this entire day
        day_start = datetime.combine(check_date, dt.time(9, 0), tzinfo=IST)
        day_end = datetime.combine(check_date, dt.time(17, 0), tzinfo=IST)
        busy_slots = get_busy_slots(day_start, day_end)
        
        # Track slots found for this day
        day_slots_found = 0
        max_slots_per_day = 2  # Limit slots per day to get variety
        
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
                tzinfo=IST
            )
            slot_end = datetime(
                year=check_date.year,
                month=check_date.month,
                day=check_date.day,
                hour=end_hour,
                minute=end_min,
                tzinfo=IST
            )
            
            # Skip if before earliest allowed time
            if slot_start < earliest_allowed:
                continue
            
            # Check if slot is available
            if not has_overlap(slot_start, slot_end, busy_slots):
                print(f"✅ Found available slot: {slot_start.strftime('%Y-%m-%d %I:%M %p')} - {slot_end.strftime('%I:%M %p')}")
                
                slots.append({
                    "start_time": slot_start,
                    "end_time": slot_end,
                    "formatted_date": slot_start.strftime('%A, %B %d'),
                    "formatted_time": f"{slot_start.strftime('%I:%M %p')} - {slot_end.strftime('%I:%M %p')} IST",
                    "date_iso": slot_start.date().isoformat(),
                    "is_gap_compliant": slot_start >= earliest_allowed,
                    "day_name": slot_start.strftime('%A'),
                    "full_datetime": slot_start.strftime('%A, %B %d, %Y at %I:%M %p IST')
                })
                
                day_slots_found += 1
            else:
                print(f"❌ Slot busy: {slot_start.strftime('%Y-%m-%d %I:%M %p')} - {slot_end.strftime('%I:%M %p')}")
        
        days_checked += 1
    
    print(f"📅 Found {len(slots)} available slots for {user_email}")
    return slots


def cancel_google_calendar_event(event_id):
    """
    Cancels a Google Calendar event using its ID.
    
    Args:
        event_id (str): The ID of the event to cancel
        
    Returns:
        bool: True if cancellation was successful, False otherwise
    """
    try:
        # Get the Google Calendar service
        service = get_google_calendar_service()
        
        # Delete the event
        service.events().delete(
            calendarId='primary',
            eventId=event_id
        ).execute()
        
        print(f"✅ Successfully cancelled calendar event: {event_id}")
        return True
        
    except Exception as e:
        print(f"❌ Error cancelling calendar event: {e}")
        return False

def send_enhanced_manual_invitations(attendees, meet_link, start_time, end_time,
                                     student_name, mentor_name, session_type):
    """
    Send email invitations with 'Add to Google Calendar' button instead of broken calendar link.
    """
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    import smtplib
    import ssl
    from urllib.parse import quote

    # Generate Google Calendar URL
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
    ⏰ Time: {start_time.strftime('%I:%M %p')} - {end_time.strftime('%I:%M %p')} IST<br>
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
            msg.attach(MIMEText(body, 'html'))  # Use HTML format

            server.sendmail(settings.EMAIL_HOST_USER, recipient, msg.as_string())
            sent_count += 1

        server.quit()
        print(f"📧 Emails sent: {sent_count}/{len(attendees)}")
        return sent_count == len(attendees)

    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False



def create_enhanced_event(
    summary: str, 
    description: str, 
    start_time_ist: datetime,
    end_time_ist: datetime, 
    attendees: List[str],
    mentor_name: str = None,
    student_name: str = None
) -> dict:
    """Creates enhanced calendar event with detailed information"""
    
    service = get_calendar_service()
    start_time_ist = _ensure_tz(start_time_ist).astimezone(IST)
    end_time_ist = _ensure_tz(end_time_ist).astimezone(IST)
    
    # Enhanced description
    duration_mins = int((end_time_ist - start_time_ist).total_seconds() / 60)
    enhanced_description = f"""
📋 MENTORSHIP SESSION DETAILS

👨‍🏫 Mentor: {mentor_name or 'TBD'}
👨‍🎓 Student: {student_name or 'TBD'}
⏱️ Duration: {duration_mins} minutes
🎥 Google Meet: {FIXED_MEET_LINK}

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
        "start": {"dateTime": start_time_ist.isoformat(), "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end_time_ist.isoformat(), "timeZone": "Asia/Kolkata"},
        "location": f"Google Meet - {FIXED_MEET_LINK}",
        "status": "confirmed",
        "colorId": "2",
        # 🔴 REMOVE ATTENDEES FROM GOOGLE CALENDAR EVENT
        # "attendees": [{"email": email} for email in attendees],
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
            calendarId=CALENDAR_ID,
            body=event_body,
            sendUpdates="none"  # Changed from "all" to prevent automatic emails
        ).execute()

        print(f"✅ Event created: {created.get('htmlLink')}")
        return {
            "success": True,
            "event_id": created.get("id"),
            "html_link": created.get("htmlLink"),
            "meet_link": FIXED_MEET_LINK,
            "calendar_link": created.get("htmlLink"),
            "start_time": start_time_ist,
            "end_time": end_time_ist
        }

    except Exception as e:
        print(f"❌ Error creating enhanced event: {e}")
        return {"success": False, "error": str(e)}


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
            slot_start, slot_end = find_next_available_2hour_slot()

        # Create calendar event using create_enhanced_event
        summary = f"Mentorship Session: {student_name} & {mentor_name}"
        description = f"2-hour mentorship session between {student_name} and {mentor_name}"
        
        event_result = create_enhanced_event(
            summary=summary,
            description=description,
            start_time_ist=slot_start,
            end_time_ist=slot_end,
            attendees=attendees,
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


def schedule_specific_slot(student_email: str, mentor_email: str, 
                         slot_start: datetime, slot_end: datetime,
                         student_name: str = None, mentor_name: str = None) -> dict:
    """
    Schedule a session for a specific time slot (used when user confirms a suggested slot)
    """
    try:
        # Verify the slot is still available
        busy_slots = get_busy_slots(
            slot_start - timedelta(hours=1),
            slot_end + timedelta(hours=1)
        )
        
        if has_overlap(slot_start, slot_end, busy_slots):
            return {
                "success": False,
                "error": "Selected time slot is no longer available. Please choose another slot."
            }
        
        # Create attendees list
        attendees = [student_email, mentor_email, CALENDAR_ID]
        
        # Create calendar event
        summary = f"Mentorship Session: {student_name or 'Student'} & {mentor_name or 'Mentor'}"
        description = f"2-hour mentorship session between {student_name or 'student'} and {mentor_name or 'mentor'}"
        
        event_result = create_enhanced_event(
            summary=summary,
            description=description,
            start_time_ist=slot_start,
            end_time_ist=slot_end,
            attendees=attendees,
            mentor_name=mentor_name,
            student_name=student_name
        )
        
        if event_result["success"]:
            # Send enhanced invitations
            print("📧 Sending email invitations to:", [student_email, mentor_email])
            send_enhanced_manual_invitations(
                attendees=[student_email, mentor_email],
                meet_link=event_result["meet_link"],
                start_time=slot_start,
                end_time=slot_end,
                student_name=student_name,
                mentor_name=mentor_name,
                session_type="1-on-1 Mentorship"
            )
            
            return {
                "success": True,
                "message": f"✅ Session confirmed for {slot_start.strftime('%A, %B %d at %I:%M %p')} - {slot_end.strftime('%I:%M %p')} IST",
                "start_time": slot_start,
                "end_time": slot_end,
                "meet_link": event_result["meet_link"],
                "calendar_link": event_result["calendar_link"],
                "event_id": event_result["event_id"]
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


# Backward compatibility functions
# Add these functions to your existing calendar_client.py (after your existing functions)

def get_available_days_for_user(user_email: str, max_days: int = 7) -> List[dict]:
    """
    Get list of days that have available slots for a user
    """
    earliest_allowed = calculate_earliest_next_session(user_email)
    available_days = []
    
    current_date = earliest_allowed.date()
    days_checked = 0
    
    while len(available_days) < max_days and days_checked < 14:  # Check up to 14 days
        check_date = current_date + timedelta(days=days_checked)
        
        # Skip weekends (optional)
        if check_date.weekday() >= 5:
            days_checked += 1
            continue
        
        # Check if this day has any available slots
        day_slots = get_slots_for_specific_day_helper(user_email, check_date)
        if day_slots:
            available_days.append({
                "day": check_date.strftime('%A'),
                "date": check_date.isoformat(),
                "formatted": check_date.strftime('%A, %B %d'),
                "slots_count": len(day_slots)
            })
        
        days_checked += 1
    
    return available_days

def get_slots_for_specific_day_helper(user_email: str, target_date) -> List[dict]:
    """
    Get available slots for a specific date (helper function)
    """
    if isinstance(target_date, str):
        # If it's a day name like "monday", convert to actual date
        days_map = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        
        if target_date.lower() in days_map:
            today = datetime.now(IST)
            target_weekday = days_map[target_date.lower()]
            current_weekday = today.weekday()
            
            days_ahead = target_weekday - current_weekday
            if days_ahead <= 0:
                days_ahead += 7
            
            target_date = (today + timedelta(days=days_ahead)).date()
    
    # Ensure we have a date object
    if isinstance(target_date, datetime):
        target_date = target_date.date()
    
    print(f"🔍 Checking slots for {target_date}")
    
    # Get busy slots for this entire day
    day_start = datetime.combine(target_date, dt.time(9, 0), tzinfo=IST)
    day_end = datetime.combine(target_date, dt.time(17, 0), tzinfo=IST)
    busy_slots = get_busy_slots(day_start, day_end)
    
    available_slots = []
    earliest_allowed = calculate_earliest_next_session(user_email)
    
    # Check each time slot for this day
    for start_hour, start_min, end_hour, end_min in AVAILABLE_TIME_SLOTS:
        slot_start = datetime(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
            hour=start_hour,
            minute=start_min,
            tzinfo=IST
        )
        slot_end = datetime(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
            hour=end_hour,
            minute=end_min,
            tzinfo=IST
        )
        
        # Skip if before earliest allowed time
        if slot_start < earliest_allowed:
            continue
        
        # Check if slot is available
        if not has_overlap(slot_start, slot_end, busy_slots):
            available_slots.append({
                "start_time": slot_start,
                "end_time": slot_end,
                "formatted_date": slot_start.strftime('%A, %B %d'),
                "formatted_time": f"{slot_start.strftime('%I:%M %p')} - {slot_end.strftime('%I:%M %p')} IST"
            })
    
    return available_slots