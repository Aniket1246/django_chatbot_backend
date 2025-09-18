# chatbot/services.py - COMPLETE UPDATED VERSION

import datetime
from .models import Mentor
from .calendar_client import (
    schedule_mentorship_session, 
    find_next_available_2hour_slot,
    create_enhanced_event,
    send_enhanced_manual_invitations,
    IST
)

def schedule_between_two_users(organizer_user, duration_minutes=120, fixed_mentor=None):
    """
    Updated service function to work with new scheduling system.
    Maintains backward compatibility while using new 2-hour slot logic.
    """
    try:
        if not fixed_mentor:
            return {
                "success": False,
                "error": "Mentor is required for session booking"
            }
        
        print(f"Scheduling session for {organizer_user.username} with {fixed_mentor.user.username}")
        
        # Use the new enhanced scheduling
        result = schedule_mentorship_session(
            student_email=organizer_user.email,
            mentor_email=fixed_mentor.user.email,
            student_name=organizer_user.username,
            mentor_name=fixed_mentor.user.username
        )
        
        if result["success"]:
            return {
                "success": True,
                "message": result["message"],
                "organizer": "UK Jobs Mentorship",
                "mentor": fixed_mentor.user.username,
                "mentor_id": fixed_mentor.id,
                "start_time": result["start_time"],
                "end_time": result["end_time"],
                "meet_link": result["meet_link"],
                "calendar_link": result["calendar_link"],
                "attendees": [organizer_user.email, fixed_mentor.user.email],
                "event_id": result.get("event_id")
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Scheduling failed")
            }
            
    except Exception as e:
        print(f"Error in schedule_between_two_users: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# Backward compatibility functions (if needed elsewhere)
def send_manual_invitations(*args, **kwargs):
    """Backward compatibility wrapper"""
    return send_enhanced_manual_invitations(*args, **kwargs)

def create_event(*args, **kwargs):
    """Backward compatibility wrapper"""  
    return create_enhanced_event(*args, **kwargs)

def find_next_available_slot(duration_minutes=120):
    """Backward compatibility wrapper"""
    return find_next_available_2hour_slot()