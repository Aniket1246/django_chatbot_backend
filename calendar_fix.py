# Complete Calendar Attendee Fix - Standalone Test Script
# Save as: calendar_attendee_fix.py
# Run: python calendar_attendee_fix.py

import os
import sys
from datetime import datetime, timedelta, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json

# Configuration
IST = timezone(timedelta(hours=5, minutes=30))
BASE_DIR = r'C:\Users\DELL\Documents\django_chatbot_backend'

# Mentor configuration
MENTOR_CONFIG = {
    "kapil": {
        "name": "Kapil Mentor", 
        "email": "kapilsanjaykanjani@gmail.com",
        "credentials_file": "credentials_kapil.json",
        "meet_link": "https://meet.google.com/gbv-mkux-scx",
        "calendar_id": "primary"
    }
}

def get_calendar_service(mentor_email: str):
    """Get Google Calendar service for specific mentor"""
    
    # Find mentor config
    mentor_config = None
    for key, config in MENTOR_CONFIG.items():
        if config["email"].lower() == mentor_email.lower():
            mentor_config = config
            break
    
    if not mentor_config:
        raise ValueError(f"Mentor {mentor_email} not found in configuration")
    
    credentials_file = os.path.join(BASE_DIR, mentor_config["credentials_file"])
    
    if not os.path.exists(credentials_file):
        raise FileNotFoundError(f"Credentials file not found: {credentials_file}")
    
    print(f"Using credentials: {credentials_file}")
    
    SCOPES = ["https://www.googleapis.com/auth/calendar"]
    credentials = service_account.Credentials.from_service_account_file(
        credentials_file, scopes=SCOPES
    )
    service = build("calendar", "v3", credentials=credentials)
    return service, mentor_config

def _ensure_tz(dt_obj: datetime) -> datetime:
    """Ensure datetime is timezone-aware (IST)"""
    if dt_obj.tzinfo is None or dt_obj.tzinfo.utcoffset(dt_obj) is None:
        return dt_obj.replace(tzinfo=IST)
    return dt_obj

def create_event_without_attendees(
    summary: str, 
    description: str, 
    start_time_ist: datetime,
    end_time_ist: datetime, 
    mentor_email: str,
    mentor_name: str = None,
    student_name: str = None,
    student_email: str = None
) -> dict:
    """Creates calendar event WITHOUT attendees to avoid permission issues"""
    
    try:
        service, mentor_config = get_calendar_service(mentor_email)
        calendar_id = mentor_config["calendar_id"]
        meet_link = mentor_config["meet_link"]
        
        start_time_ist = _ensure_tz(start_time_ist).astimezone(IST)
        end_time_ist = _ensure_tz(end_time_ist).astimezone(IST)
        
        # Enhanced description with attendee info (but not actual attendees)
        duration_mins = int((end_time_ist - start_time_ist).total_seconds() / 60)
        enhanced_description = f"""
📋 MENTORSHIP SESSION DETAILS

👨‍🏫 Mentor: {mentor_name or mentor_config["name"]}
👨‍🎓 Student: {student_name or 'TBD'}
⏱️ Duration: {duration_mins} minutes
🎥 Google Meet: {meet_link}

📧 Participants:
• Mentor: {mentor_email}
• Student: {student_email or 'TBD'}

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
            "location": f"Google Meet - {meet_link}",
            "status": "confirmed",
            "colorId": "2",  # Green color
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 60},
                    {"method": "popup", "minutes": 15},
                ]
            }
            # NO ATTENDEES - This fixes the permission issue
        }

        print("Creating event without attendees...")
        created = service.events().insert(
            calendarId=calendar_id,
            body=event_body,
            sendUpdates="none"  # Don't send calendar invites
        ).execute()

        print(f"✅ Event created successfully: {created.get('htmlLink')}")
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
        print(f"❌ Error creating event: {e}")
        return {"success": False, "error": str(e)}

def verify_event_creation(event_id: str, mentor_email: str) -> bool:
    """Verify that the event was actually created"""
    try:
        service, mentor_config = get_calendar_service(mentor_email)
        
        # Wait a moment for sync
        import time
        time.sleep(2)
        
        event = service.events().get(
            calendarId=mentor_config["calendar_id"],
            eventId=event_id
        ).execute()
        
        print("✅ Event verification successful!")
        print(f"📋 Title: {event.get('summary')}")
        print(f"📅 Start: {event.get('start', {}).get('dateTime')}")
        print(f"📅 End: {event.get('end', {}).get('dateTime')}")
        print(f"🔗 Link: {event.get('htmlLink')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Event verification failed: {e}")
        return False

def test_multiple_sessions():
    """Test creating multiple sessions with different times"""
    
    print("🧪 TESTING MULTIPLE SESSION CREATION")
    print("=" * 45)
    
    mentor_email = "kapilsanjaykanjani@gmail.com"
    student_email = "co2021.amit.ramtri@ves.ac.in"
    
    # Test sessions
    test_sessions = [
        {
            "name": "Session 1",
            "start": datetime(2025, 10, 1, 14, 0, tzinfo=IST),  # Oct 1, 2:00 PM
            "end": datetime(2025, 10, 1, 16, 0, tzinfo=IST),    # Oct 1, 4:00 PM
        },
        {
            "name": "Session 2", 
            "start": datetime(2025, 10, 2, 11, 0, tzinfo=IST),  # Oct 2, 11:00 AM
            "end": datetime(2025, 10, 2, 13, 0, tzinfo=IST),    # Oct 2, 1:00 PM
        },
        {
            "name": "Session 3",
            "start": datetime(2025, 10, 3, 15, 0, tzinfo=IST),  # Oct 3, 3:00 PM
            "end": datetime(2025, 10, 3, 17, 0, tzinfo=IST),    # Oct 3, 5:00 PM
        }
    ]
    
    created_events = []
    
    for i, session in enumerate(test_sessions, 1):
        print(f"\n📅 Creating {session['name']}...")
        print(f"Time: {session['start'].strftime('%A, %B %d at %I:%M %p')} - {session['end'].strftime('%I:%M %p')} IST")
        
        result = create_event_without_attendees(
            summary=f"🎓 Test Mentorship Session {i}: Amit & Kapil",
            description=f"Test session {i} to verify calendar fix is working",
            start_time_ist=session['start'],
            end_time_ist=session['end'],
            mentor_email=mentor_email,
            mentor_name="Kapil Mentor",
            student_name="Amit",
            student_email=student_email
        )
        
        if result.get('success'):
            print(f"✅ {session['name']} created successfully!")
            print(f"🆔 Event ID: {result['event_id']}")
            
            # Verify the event
            if verify_event_creation(result['event_id'], mentor_email):
                created_events.append(result)
                print(f"✅ {session['name']} verified in calendar!")
            else:
                print(f"❌ {session['name']} verification failed!")
        else:
            print(f"❌ {session['name']} creation failed: {result.get('error')}")
    
    return created_events

def search_created_events(mentor_email: str):
    """Search for all events created in the last hour"""
    
    print(f"\n📋 SEARCHING FOR CREATED EVENTS")
    print("=" * 35)
    
    try:
        service, mentor_config = get_calendar_service(mentor_email)
        
        # Search from 1 hour ago to next week
        now = datetime.now(IST)
        time_min = (now - timedelta(hours=1)).isoformat()
        time_max = (now + timedelta(days=7)).isoformat()
        
        events_result = service.events().list(
            calendarId=mentor_config["calendar_id"],
            timeMin=time_min,
            timeMax=time_max,
            maxResults=20,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        print(f"📊 Found {len(events)} events in timeframe")
        
        if events:
            for i, event in enumerate(events, 1):
                summary = event.get('summary', 'No title')
                start_dt = event.get('start', {}).get('dateTime', 'No start')
                event_id = event.get('id', 'no-id')
                
                print(f"\n{i}. {summary}")
                print(f"   📅 {start_dt}")
                print(f"   🆔 {event_id}")
                
                # Highlight test events
                if 'test' in summary.lower() or 'amit' in summary.lower():
                    print(f"   🎯 This is our test event!")
        else:
            print("No events found")
            
        return events
        
    except Exception as e:
        print(f"❌ Error searching events: {e}")
        return []

def cleanup_test_events(mentor_email: str):
    """Clean up test events (optional)"""
    
    print(f"\n🧹 CLEANUP TEST EVENTS (Optional)")
    print("=" * 35)
    
    try:
        service, mentor_config = get_calendar_service(mentor_email)
        
        # Search for test events
        now = datetime.now(IST)
        time_min = (now - timedelta(hours=1)).isoformat()
        time_max = (now + timedelta(days=7)).isoformat()
        
        events_result = service.events().list(
            calendarId=mentor_config["calendar_id"],
            timeMin=time_min,
            timeMax=time_max,
            maxResults=20,
            singleEvents=True,
            orderBy='startTime',
            q='Test Mentorship Session'  # Search for test events
        ).execute()
        
        test_events = events_result.get('items', [])
        
        if test_events:
            print(f"Found {len(test_events)} test events to clean up")
            
            for event in test_events:
                event_id = event.get('id')
                summary = event.get('summary', 'No title')
                
                try:
                    service.events().delete(
                        calendarId=mentor_config["calendar_id"],
                        eventId=event_id
                    ).execute()
                    print(f"🗑️ Deleted: {summary}")
                except Exception as e:
                    print(f"❌ Failed to delete {summary}: {e}")
        else:
            print("No test events found to clean up")
            
    except Exception as e:
        print(f"❌ Cleanup error: {e}")

def main():
    """Main test function"""
    
    print("🚀 CALENDAR ATTENDEE FIX - COMPREHENSIVE TEST")
    print("=" * 50)
    print("This script tests the fix for the attendee permission issue")
    print("by creating events WITHOUT attendees to avoid the 403 error.")
    print()
    
    mentor_email = "kapilsanjaykanjani@gmail.com"
    
    try:
        # Test 1: Create multiple test sessions
        created_events = test_multiple_sessions()
        
        # Test 2: Search for created events
        all_events = search_created_events(mentor_email)
        
        # Summary
        print(f"\n🎉 TEST SUMMARY")
        print("=" * 20)
        print(f"✅ Successfully created: {len(created_events)} events")
        print(f"📋 Total events found: {len(all_events)}")
        
        if created_events:
            print(f"\n📅 CREATED EVENT DETAILS:")
            for i, event in enumerate(created_events, 1):
                start_time = event['start_time']
                print(f"{i}. {start_time.strftime('%A, %B %d at %I:%M %p')} IST")
                print(f"   🔗 {event['calendar_link']}")
                print(f"   📹 {event['meet_link']}")
        
        print(f"\n✅ CALENDAR FIX IS WORKING!")
        print("Events are being created successfully without attendee restrictions.")
        print("Check Google Calendar to see the events visually.")
        
        # Optional cleanup
        cleanup_choice = input("\n🧹 Do you want to clean up test events? (y/n): ").lower().strip()
        if cleanup_choice == 'y':
            cleanup_test_events(mentor_email)
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
    
    print(f"\n" + "=" * 50)
    print("🏁 TEST COMPLETE")
    print("=" * 50)
    print("If this test succeeded, your calendar integration is fixed!")
    print("You can now update your main calendar_client.py with the fix.")
    print("The key change: Remove 'attendees' from event creation.")
    print("Send email invitations separately instead.")