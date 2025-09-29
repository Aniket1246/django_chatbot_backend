# Calendar Event Debug & Verification Script
# Save as: calendar_debug.py
# Run: python calendar_debug.py

import os
import sys
import json
from datetime import datetime, timedelta, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Add your Django project path
sys.path.append(r'C:\Users\DELL\Documents\django_chatbot_backend')

# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

def debug_kapil_calendar():
    """Debug Kapil mentor's calendar setup and recent events"""
    
    print("🔍 DEBUGGING KAPIL CALENDAR SETUP")
    print("=" * 50)
    
    # Configuration from your calendar_client.py
    MENTOR_EMAIL = "kapilsanjaykanjani@gmail.com"
    CREDENTIALS_FILE = r"C:\Users\DELL\Documents\django_chatbot_backend\credentials_kapil.json"
    EVENT_ID = "uqu1am0psloa49uoj7vhiqpsrc"  # From your terminal log
    
    # Step 1: Check credentials file
    print("📁 STEP 1: Credentials File Check")
    print("-" * 30)
    
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"❌ Credentials file not found: {CREDENTIALS_FILE}")
        return False
    
    print(f"✅ Credentials file exists: {CREDENTIALS_FILE}")
    
    try:
        with open(CREDENTIALS_FILE, 'r') as f:
            cred_data = json.load(f)
            service_account_email = cred_data.get('client_email', 'Unknown')
            project_id = cred_data.get('project_id', 'Unknown')
        
        print(f"🔑 Service Account Email: {service_account_email}")
        print(f"🏗️ Project ID: {project_id}")
        
    except Exception as e:
        print(f"❌ Error reading credentials: {e}")
        return False
    
    # Step 2: Test Calendar API Access
    print(f"\n📅 STEP 2: Calendar API Access Test")
    print("-" * 30)
    
    try:
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        credentials = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=credentials)
        
        print("✅ Calendar service created successfully")
        
        # Test access to Kapil's calendar
        calendar = service.calendars().get(calendarId=MENTOR_EMAIL).execute()
        print(f"✅ Calendar access successful")
        print(f"📅 Calendar Name: {calendar.get('summary', 'No name')}")
        print(f"🕒 Timezone: {calendar.get('timeZone', 'No timezone')}")
        
    except Exception as e:
        print(f"❌ Calendar API access failed: {e}")
        print("🔧 Possible fixes:")
        print("   - Check if Google Calendar API is enabled in Google Console")
        print("   - Verify service account has calendar access permissions")
        print(f"   - Ensure {service_account_email} is added to calendar sharing")
        return False
    
    # Step 3: Search for the specific event
    print(f"\n🔍 STEP 3: Event Search (ID: {EVENT_ID})")
    print("-" * 30)
    
    try:
        # Method 1: Direct event lookup
        event = service.events().get(
            calendarId=MENTOR_EMAIL, 
            eventId=EVENT_ID
        ).execute()
        
        print("🎉 SUCCESS! Event found by ID:")
        print(f"📋 Title: {event.get('summary', 'No title')}")
        print(f"📅 Start: {event.get('start', {}).get('dateTime', 'No start')}")
        print(f"📅 End: {event.get('end', {}).get('dateTime', 'No end')}")
        print(f"🔗 Calendar Link: {event.get('htmlLink', 'No link')}")
        print(f"📍 Meet Link: {event.get('hangoutLink', 'No meet link')}")
        print(f"👥 Attendees:")
        
        attendees = event.get('attendees', [])
        for attendee in attendees:
            status = attendee.get('responseStatus', 'unknown')
            email = attendee.get('email', 'no-email')
            print(f"   - {email} ({status})")
        
        return True
        
    except Exception as e:
        print(f"❌ Event not found by ID: {e}")
        
        # If direct lookup fails, search recent events
        print("\n🔍 Searching recent events...")
        try:
            now = datetime.now(IST)
            time_min = (now - timedelta(days=1)).isoformat()
            time_max = (now + timedelta(days=7)).isoformat()
            
            events_result = service.events().list(
                calendarId=MENTOR_EMAIL,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=20,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            events = events_result.get('items', [])
            print(f"📋 Found {len(events)} events in recent timeframe:")
            
            for i, event in enumerate(events, 1):
                event_id = event.get('id', 'no-id')
                summary = event.get('summary', 'No title')
                start = event.get('start', {}).get('dateTime', 'No start')
                
                print(f"{i}. {summary}")
                print(f"   ID: {event_id}")
                print(f"   Start: {start}")
                
                # Check if this matches our target event
                if event_id == EVENT_ID:
                    print("   ✅ This is our target event!")
                    return True
            
            if not events:
                print("❌ No events found in the timeframe")
                
        except Exception as search_error:
            print(f"❌ Error searching events: {search_error}")
    
    return False

def test_calendar_permissions():
    """Test if service account can create/modify events"""
    
    print(f"\n🛠️ STEP 4: Permission Test")
    print("-" * 30)
    
    MENTOR_EMAIL = "kapilsanjaykanjani@gmail.com"
    CREDENTIALS_FILE = r"C:\Users\DELL\Documents\django_chatbot_backend\credentials_kapil.json"
    
    try:
        SCOPES = ['https://www.googleapis.com/auth/calendar']
        credentials = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=credentials)
        
        # Try to create a test event (in the future to avoid conflicts)
        test_time = datetime.now(IST) + timedelta(days=30)
        test_start = test_time.replace(hour=10, minute=0, second=0, microsecond=0)
        test_end = test_start + timedelta(hours=1)
        
        test_event = {
            'summary': '🧪 TEST EVENT - DELETE ME',
            'description': 'This is a test event created by calendar verification script. Please delete.',
            'start': {
                'dateTime': test_start.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': test_end.isoformat(),
                'timeZone': 'Asia/Kolkata',
            },
            'colorId': '3',  # Different color to make it obvious
        }
        
        created_event = service.events().insert(
            calendarId=MENTOR_EMAIL, 
            body=test_event
        ).execute()
        
        event_id = created_event.get('id')
        print(f"✅ Test event created successfully!")
        print(f"🆔 Test Event ID: {event_id}")
        print(f"🔗 Link: {created_event.get('htmlLink', 'No link')}")
        
        # Clean up - delete the test event
        try:
            service.events().delete(
                calendarId=MENTOR_EMAIL, 
                eventId=event_id
            ).execute()
            print("✅ Test event deleted successfully")
            
        except Exception as delete_error:
            print(f"⚠️ Could not delete test event: {delete_error}")
            print(f"🗑️ Please manually delete test event with ID: {event_id}")
        
        return True
        
    except Exception as e:
        print(f"❌ Permission test failed: {e}")
        
        if "403" in str(e):
            print("🔧 PERMISSION ERROR - Possible fixes:")
            print("   1. Add service account email to calendar sharing")
            print("   2. Give 'Make changes to events' permission")
            print("   3. Make calendar public or properly shared")
        elif "404" in str(e):
            print("🔧 CALENDAR NOT FOUND - Possible fixes:")
            print("   1. Check if calendar email is correct")
            print("   2. Verify calendar exists and is accessible")
        
        return False

def main():
    """Main debugging function"""
    print("🚀 STARTING CALENDAR DEBUG SESSION")
    print("=" * 50)
    print("Target Event ID: uqu1am0psloa49uoj7vhiqpsrc")
    print("Mentor Email: kapilsanjaykanjani@gmail.com")
    print("Expected Date: September 29, 2025, 11:00 AM - 1:00 PM IST")
    print()
    
    # Run all debug steps
    event_found = debug_kapil_calendar()
    
    if event_found:
        print("\n🎉 RESULT: Event exists in calendar!")
        print("🔧 If you can't see it in Google Calendar web interface:")
        print("   1. Refresh the calendar page")
        print("   2. Check calendar visibility settings")  
        print("   3. Make sure correct calendar is selected")
        print("   4. Try different view (Day/Week/Month)")
        print("   5. Check timezone settings")
    else:
        print("\n😕 RESULT: Event not found")
        print("🔧 Testing permissions...")
        
        permissions_ok = test_calendar_permissions()
        
        if permissions_ok:
            print("\n✅ Permissions are OK - event should have been created")
            print("🤔 Possible issues:")
            print("   1. Event was created but in different time")
            print("   2. Calendar sync delay")
            print("   3. Event ID mismatch")
        else:
            print("\n❌ Permission issues detected - fix these first")

if __name__ == "__main__":
    main()

# ADDITIONAL MANUAL CHECKS:
print("\n" + "=" * 50)
print("🔍 MANUAL CHECKS TO PERFORM:")
print("=" * 50)
print("1. Go to Google Calendar (calendar.google.com)")
print("2. Look for 'kapilsanjaykanjani@gmail.com' in left sidebar")
print("3. Make sure this calendar is checked/visible")
print("4. Navigate to September 29, 2025")
print("5. Look for event at 11:00 AM - 1:00 PM slot")
print("6. Try this direct link:")
print("   https://www.google.com/calendar/event?eid=dXF1MWFtMHBzbG9hNDl1b2o3dmhpcXBzcmMgcHJvamVjdDJAa2FwaWwtNDYyOTE1LmlhbS5nc2VydmljZWFjY291bnQuY29t")
print()
print("🔧 IF EVENT STILL NOT VISIBLE:")
print("- Service account email should be: project2@kapil-462915.iam.gserviceaccount.com")
print("- This email must be added to calendar sharing with 'Make changes to events'")
print("- Calendar API must be enabled in Google Cloud Console")
print("- Check Google Calendar Settings > Access permissions")