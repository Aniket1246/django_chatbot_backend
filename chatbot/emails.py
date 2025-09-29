# chatbot/emails.py
from django.core.mail import send_mail
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from django.conf import settings
from .utils import cancel_calendar_event
import pytz
UK_TIMEZONE = pytz.timezone('Europe/London')

def send_booking_email(to_emails, session):
    # placeholder implementation
    send_mail(
        subject=f"Booking Confirmed: {session.mentor_name}",
        message=f"Your session is confirmed for {session.start_time}.",
        from_email="no-reply@example.com",
        recipient_list=to_emails,
    )

def send_cancellation_email(session, attendee_email, attendee_name, mentor_email, mentor_name):
    """
    Send cancellation email to both attendee and mentor
    and remove the session from Google Calendar
    
    Args:
        session: SessionBooking object
        attendee_email: str
        attendee_name: str
        mentor_email: str
        mentor_name: str
    """
    
    # Format session time with better error handling
    try:
        if hasattr(session.start_time, 'strftime'):
            formatted_time = session.start_time.strftime('%A, %B %d, %Y at %I:%M %p UK Time')
        else:
            # Handle string datetime
            from django.utils.dateparse import parse_datetime
            from django.utils import timezone
            
            start_time = session.start_time
            if isinstance(start_time, str):
                start_time = parse_datetime(start_time)
            
            if start_time:
                if start_time.tzinfo is None:
                    start_time = UK_TIMEZONE.localize(start_time)
                formatted_time = start_time.astimezone(UK_TIMEZONE).strftime('%A, %B %d, %Y at %I:%M %p UK Time')
            else:
                formatted_time = str(session.start_time)
    except Exception as e:
        print(f"⚠️ Error formatting session time: {e}")
        formatted_time = str(session.start_time)

    # Subjects
    subject_attendee = f"🚫 Your session with {mentor_name} has been cancelled"
    subject_mentor = f"🚫 Your session with {attendee_name} has been cancelled"

    # Messages
    attendee_msg = f"""Hi {attendee_name},

Your scheduled mentorship session on {formatted_time} with {mentor_name} has been cancelled.

If you want to reschedule, please login to your account and book a new slot.

Thanks,
UK Jobs Mentorship Team"""

    mentor_msg = f"""Hi {mentor_name},

The mentorship session scheduled on {formatted_time} with {attendee_name} has been cancelled.

You are now free for this time slot.

Thanks,
UK Jobs Mentorship Team"""

    try:
        # Method 1: Try using Django's send_mail (recommended)
        try:
            # Send email to attendee
            send_mail(
                subject_attendee,
                attendee_msg,
                settings.EMAIL_HOST_USER,
                [attendee_email],
                fail_silently=False,
            )
            print(f"✅ Django send_mail: Attendee email sent to {attendee_email}")

            # Send email to mentor
            send_mail(
                subject_mentor,
                mentor_msg,
                settings.EMAIL_HOST_USER,
                [mentor_email],
                fail_silently=False,
            )
            print(f"✅ Django send_mail: Mentor email sent to {mentor_email}")
            
        except Exception as django_email_error:
            print(f"⚠️ Django send_mail failed, trying direct SMTP: {django_email_error}")
            
            # Method 2: Fallback to direct SMTP
            send_via_direct_smtp(
                subject_attendee, attendee_msg, attendee_email,
                subject_mentor, mentor_msg, mentor_email
            )

        # Cancel from calendar with improved error handling
        if hasattr(session, 'event_id') and session.event_id:
            try:
                from .calendar_client import cancel_calendar_event
                cancel_result = cancel_calendar_event(session.event_id)
                if cancel_result:
                    print(f"✅ Calendar event {session.event_id} cancelled successfully")
                else:
                    print(f"⚠️ Calendar event {session.event_id} cancellation had issues (check logs)")
            except ImportError:
                print("⚠️ Could not import cancel_calendar_event function")
            except Exception as cal_error:
                print(f"⚠️ Calendar cancellation error: {cal_error}")
        else:
            print("ℹ️ No event_id found for calendar cancellation")

        print(f"✅ Cancellation process completed for session between {attendee_email} and {mentor_email}")
        return True
        
    except Exception as e:
        print(f"❌ Failed to send cancellation emails: {e}")
        import traceback
        traceback.print_exc()
        return False

def send_via_direct_smtp(subject_attendee, attendee_msg, attendee_email, 
                        subject_mentor, mentor_msg, mentor_email):
    """
    Send emails using direct SMTP connection (fallback method)
    """
    import ssl
    
    try:
        # Create secure connection
        context = ssl.create_default_context()
        
        with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as server:
            server.ehlo()
            server.starttls(context=context)  # Use context parameter only
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            
            # Send attendee email
            msg1 = MIMEText(attendee_msg)
            msg1['Subject'] = subject_attendee
            msg1['From'] = settings.EMAIL_HOST_USER
            msg1['To'] = attendee_email
            
            server.send_message(msg1)
            print(f"✅ Direct SMTP: Attendee email sent to {attendee_email}")
            
            # Send mentor email
            msg2 = MIMEText(mentor_msg)
            msg2['Subject'] = subject_mentor
            msg2['From'] = settings.EMAIL_HOST_USER
            msg2['To'] = mentor_email
            
            server.send_message(msg2)
            print(f"✅ Direct SMTP: Mentor email sent to {mentor_email}")
            
    except Exception as smtp_error:
        print(f"❌ Direct SMTP also failed: {smtp_error}")
        raise  # Re-raise to be caught by parent function
