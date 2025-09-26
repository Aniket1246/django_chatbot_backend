import traceback
import random
from .models import SessionBooking, UserProfile
from .utils import cancel_calendar_event
from config.settings import BASE_DIR
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from .models import Mentor, UserProfile, ChatHistory, SessionBooking
from .services import schedule_between_two_users
import json
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import csv
import os
from django.conf import settings
from .gemini_client import ask_gemini
from .utils import is_meeting_request, extract_duration
from datetime import datetime, timedelta
from .calendar_client import (
    schedule_specific_slot,
    get_next_available_slots_for_user,
    send_enhanced_manual_invitations,
     cancel_calendar_event
)
from django.utils import timezone
from .emails import send_cancellation_email
from django.utils.dateparse import parse_datetime
try:
    from dateutil import parser as dateutil_parser
except ImportError:
    dateutil_parser = None

  # ensure import
IST = timezone.get_fixed_timezone(5*60 + 30)

# Domain mappings for mentors - Based on your actual mentor expertise
DOMAIN_KEYWORDS = {
    'marketing': ['marketing', 'digital marketing', 'seo', 'social media', 'content', 'campaigns', 'ads', 'promotion'],
    'cv': ['cv', 'resume', 'curriculum vitae', 'profile', 'career document', 'job application'],
    'linkedin': ['linkedin', 'professional network', 'social networking', 'profile optimization', 'connections'],
    'testing': ['test', 'qa', 'quality assurance', 'automation', 'selenium', 'cypress'],
    'data': ['data', 'analytics', 'data science', 'machine learning', 'statistics', 'python', 'sql'],
    'development': ['developer', 'programming', 'coding', 'software', 'web development', 'frontend', 'backend'],
    'design': ['design', 'ui', 'ux', 'graphic', 'visual', 'creative', 'figma', 'photoshop'],
    'finance': ['finance', 'accounting', 'investment', 'banking', 'financial analysis'],
    'hr': ['hr', 'human resources', 'recruitment', 'talent', 'people management']
}
def is_cancel_request(message: str) -> bool:
    """Check if the message is a cancellation request"""
    lower = message.lower()
    cancel_keywords = [
        'cancel', 'cancel my', 'cancel session', 'cancel call', 'cancel meeting',
        'cancel appointment', 'cancel booking', 'dont want', 'don\'t want',
        'remove session', 'delete session', 'cancel last session',
        'cancel my session', 'cancel my last session'
    ]
    
    return any(keyword in lower for keyword in cancel_keywords)

def ensure_timezone_aware(dt_obj):
    """Ensure datetime object is timezone-aware in IST"""
    from django.utils import timezone
    
    if dt_obj is None:
        return None
        
    IST = timezone.get_fixed_timezone(5*60 + 30)
    
    if isinstance(dt_obj, str):
        from django.utils.dateparse import parse_datetime
        dt_obj = parse_datetime(dt_obj)
        if dt_obj is None:
            raise ValueError(f"Cannot parse datetime: {dt_obj}")
    
    if dt_obj.tzinfo is None:
        dt_obj = timezone.make_aware(dt_obj, IST)
    
    return dt_obj

def detect_domain_from_message(message: str) -> str:
    """
    Detect the domain based on keywords in the user's message
    Returns the domain name or 'general' if no specific domain detected
    """
    message_lower = message.lower()
    
    for domain, keywords in DOMAIN_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                return domain
    
    return 'general'

# Temporary dummy function for testing



def get_random_mentor_by_domain(domain: str) -> Mentor:
    """
    Get a random mentor from the specified domain based on exact expertise match
    If no mentors found in domain, return a random mentor from any domain
    """
    try:
        print(f"🔍 Looking for mentors in domain: {domain}")
        
        # Direct expertise match (case insensitive)
        domain_mentors = Mentor.objects.filter(
            is_active=True,
            expertise__iexact=domain
        ).select_related('user')
        
        if domain_mentors.exists():
            selected = random.choice(list(domain_mentors))
            print(f"✅ Found {domain_mentors.count()} mentors for '{domain}', selected: {selected.user.username}")
            return selected
        
        # If no exact match, try case-insensitive contains
        domain_mentors = Mentor.objects.filter(
            is_active=True,
            expertise__icontains=domain
        ).select_related('user')
        
        if domain_mentors.exists():
            selected = random.choice(list(domain_mentors))
            print(f"✅ Found {domain_mentors.count()} mentors containing '{domain}', selected: {selected.user.username}")
            return selected
        
        # Try keyword-based search
        for keyword in DOMAIN_KEYWORDS.get(domain, []):
            keyword_mentors = Mentor.objects.filter(
                is_active=True,
                expertise__icontains=keyword
            ).select_related('user')
            
            if keyword_mentors.exists():
                selected = random.choice(list(keyword_mentors))
                print(f"✅ Found {keyword_mentors.count()} mentors for keyword '{keyword}', selected: {selected.user.username}")
                return selected
        
        # Fallback: return any active mentor
        all_mentors = Mentor.objects.filter(is_active=True).select_related('user')
        if all_mentors.exists():
            selected = random.choice(list(all_mentors))
            print(f"⚠️ No domain-specific mentor found, selected random: {selected.user.username}")
            return selected
        
        print("❌ No active mentors found at all")
        return None
        
    except Exception as e:
        print(f"❌ Error getting mentor by domain: {e}")
        # Fallback: return any active mentor
        try:
            all_mentors = Mentor.objects.filter(is_active=True).select_related('user')
            if all_mentors.exists():
                return random.choice(list(all_mentors))
        except:
            pass
        return None

def is_first_time_user(user):
    """Check if user has any previous confirmed sessions"""
    try:
        previous_bookings = SessionBooking.objects.filter(
            user=user, 
            status='confirmed'
        ).count()
        
        return previous_bookings == 0
    except:
        return True  # Assume first time if error

def get_user_data(email: str) -> dict | None:
    csv_path = os.path.join(settings.BASE_DIR, "users.csv")
    try:
        with open(csv_path, newline="") as csvfile:
            sample = csvfile.read(1024)
            csvfile.seek(0)

            # Detect if file has header
            has_header = csv.Sniffer().has_header(sample)

            if has_header:
                reader = csv.DictReader(csvfile)
                reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
            else:
                reader = csv.reader(csvfile)
                for row in reader:
                    if row[0].strip().lower() == email.strip().lower():
                        return {"email": row[0].strip(), "type": row[1].strip().lower()}

            for row in reader:
                row = {k.strip().lower(): (v.strip() if v else v) for k, v in row.items()}
                if row.get("email", "").lower() == email.strip().lower():
                    return {"email": row["email"], "type": row.get("type", "").lower()}
    except Exception as e:
        print(f"❌ Error reading users.csv: {e}")
    return None


def is_email_allowed(email: str) -> bool:
    """Check if email exists in users.csv"""
    return get_user_data(email) is not None

def is_email_premium(email: str) -> bool:
    """Check if email has premium status in users.csv"""
    user_data = get_user_data(email)
    return user_data and user_data["type"] == "premium"

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_email_send(request):
    """Test email sending functionality"""
    try:
        success = send_enhanced_manual_invitations(
            attendees=[request.user.email, "test@example.com"],
            meet_link="https://meet.google.com/test",
            calendar_link="https://calendar.google.com/test",
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(hours=2),
            student_name=request.user.username,
            mentor_name="Test Mentor",
            session_type="Test Session"
        )
        
        return Response({
            "success": success,
            "message": "Test email sent" if success else "Failed to send email"
        })
        
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@method_decorator(csrf_exempt, name="dispatch")
class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            # Add this debug code
            csv_path = os.path.join(settings.BASE_DIR, "users.csv")
            print(f"🔍 CSV exists: {os.path.exists(csv_path)}")
            if os.path.exists(csv_path):
                print(f"📋 CSV is readable: {os.access(csv_path, os.R_OK)}")
                with open(csv_path, 'r') as f:
                    print(f"📝 CSV content:\n{f.read()}")
            
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.data

            email = data.get("email")
            password = data.get("password")
            username = data.get("username")

            if not email or not password:
                return Response({"error": "Email and password are required"},
                                status=status.HTTP_400_BAD_REQUEST)

            # Debug email check
            print(f"🔍 Checking if email is allowed: {email}")
            is_allowed = is_email_allowed(email)
            print(f"✅ Email allowed result: {is_allowed}")
            
            if not is_allowed:
                return Response({
                    "error": "This email is not allowed to signup. Please contact support."
                }, status=status.HTTP_403_FORBIDDEN)

            # Rest of your code...

            if User.objects.filter(email=email).exists():
                return Response({"error": "User already exists"},
                                status=status.HTTP_400_BAD_REQUEST)

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            # Create UserProfile with correct type
            user_data = get_user_data(email)
            is_premium = user_data and user_data["type"] == "premium"
            
            UserProfile.objects.create(
                user=user,
                is_premium=is_premium
            )

            token, _ = Token.objects.get_or_create(user=user)

            return Response({
                "message": "User created successfully",
                "token": token.key,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "is_premium": is_premium
                }
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        data = request.data
        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return Response({"error": "Email and password required"}, status=400)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "Invalid email or password"}, status=401)

        if not user.check_password(password):
            return Response({"error": "Invalid email or password"}, status=401)

        # Sync premium status with CSV
        user_data = get_user_data(email)
        is_premium = user_data and user_data["type"] == "premium"
        
        # Update UserProfile if exists
        profile, created = UserProfile.objects.get_or_create(user=user)
        if profile.is_premium != is_premium:
            profile.is_premium = is_premium
            profile.save()

        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            "message": "Login successful",
            "token": token.key,
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "is_premium": is_premium
            }
        }, status=200)
def to_aware_datetime(dt_str_or_dt):
    IST = timezone.get_fixed_timezone(5*60 + 30)
    
    if isinstance(dt_str_or_dt, str):
        dt = parse_datetime(dt_str_or_dt)
        if dt is None:
            raise ValueError(f"Invalid datetime string: {dt_str_or_dt}")
    else:
        dt = dt_str_or_dt

    if dt.tzinfo is None:
        dt = timezone.make_aware(dt, IST)
    return dt

@method_decorator(csrf_exempt, name="dispatch")  
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            request.user.auth_token.delete()
            return Response({
                "message": "Logged out successfully"
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                "error": "Logout failed"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@method_decorator(csrf_exempt, name="dispatch")
class TestView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request):
        return Response({
            "message": "API is working!",
            "method": "GET",
            "user_authenticated": request.user.is_authenticated
        })
    
    def post(self, request):
        return Response({
            "message": "POST request received",
            "data": request.data,
            "user_authenticated": request.user.is_authenticated
        })

class UserProfileView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # Sync with CSV to ensure latest status
            user_data = get_user_data(request.user.email)
            is_premium = user_data and user_data["type"] == "premium"
            
            profile, created = UserProfile.objects.get_or_create(user=request.user)
            if profile.is_premium != is_premium:
                profile.is_premium = is_premium
                profile.save()
            
            return Response({
                "user": {
                    "id": request.user.id,
                    "email": request.user.email,
                    "username": request.user.username,
                    "is_premium": profile.is_premium,
                    "session_count": profile.session_count
                }
            }, status=status.HTTP_200_OK)
        except UserProfile.DoesNotExist:
            return Response({
                "error": "Profile not found"
            }, status=status.HTTP_404_NOT_FOUND)

@api_view(['GET'])
def list_mentors(request):
    # Sirf premium users ko mentors dikhne chahiye
    if not request.user.is_authenticated:
        return Response({"error": "Authentication required"}, status=401)

    try:
        profile = UserProfile.objects.get(user=request.user)
        if not profile.is_premium:
            return Response({"error": "Only premium users can access mentors"}, status=403)
    except UserProfile.DoesNotExist:
        return Response({"error": "Profile not found"}, status=404)

    # Active mentors sorted by username
    mentors = Mentor.objects.filter(is_active=True).select_related("user").order_by("user__username")

    data = [
        {
            "id": m.id,
            "username": m.user.username,
            "email": m.user.email,
            "expertise": m.expertise,
        }
        for m in mentors
    ]
    return Response(data, status=200)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def test_email_config(request):
    """Test email configuration with detailed debugging"""
    try:
        import smtplib
        
        print("📧 [EMAIL TEST] Starting email configuration test...")
        
        # Print current settings
        email_settings = {
            'EMAIL_BACKEND': getattr(settings, 'EMAIL_BACKEND', 'NOT_SET'),
            'EMAIL_HOST': getattr(settings, 'EMAIL_HOST', 'NOT_SET'),
            'EMAIL_PORT': getattr(settings, 'EMAIL_PORT', 'NOT_SET'),
            'EMAIL_USE_TLS': getattr(settings, 'EMAIL_USE_TLS', 'NOT_SET'),
            'EMAIL_HOST_USER': getattr(settings, 'EMAIL_HOST_USER', 'NOT_SET'),
            'EMAIL_HOST_PASSWORD': '***' if getattr(settings, 'EMAIL_HOST_PASSWORD', None) else 'NOT_SET'
        }
        
        print("📧 [EMAIL TEST] Current settings:")
        for key, value in email_settings.items():
            print(f"  {key}: {value}")
        
        # Test SMTP connection directly
        try:
            print("📧 [EMAIL TEST] Testing SMTP connection...")
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            server.quit()
            print("✅ [EMAIL TEST] SMTP connection successful")
            smtp_status = "SUCCESS"
        except Exception as smtp_err:
            print(f"❌ [EMAIL TEST] SMTP connection failed: {smtp_err}")
            smtp_status = f"FAILED: {str(smtp_err)}"
        
        # Test Django send_mail
        try:
            print(f"📧 [EMAIL TEST] Sending test email to {request.user.email}...")
            
            result = send_mail(
                subject='🔥 Django Email Test - Session Booking System',
                message=f'''
Hi {request.user.username}!

This is a test email from your Django mentorship booking system.

If you receive this email, your email configuration is working perfectly! ✅

Test Details:
- Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}  
- From: {settings.EMAIL_HOST_USER}
- To: {request.user.email}

Next step: Book a mentorship session and you'll get proper confirmation emails.

Thanks!
UK Jobs Team
                ''',
                from_email=settings.EMAIL_HOST_USER,
                recipient_list=[request.user.email],
                fail_silently=False,
            )
            
            print(f"✅ [EMAIL TEST] Django send_mail result: {result}")
            django_status = "SUCCESS" if result == 1 else "FAILED"
            
        except Exception as django_err:
            print(f"❌ [EMAIL TEST] Django send_mail failed: {django_err}")
            django_status = f"FAILED: {str(django_err)}"
        
        return Response({
            "email_settings": email_settings,
            "smtp_test": smtp_status,
            "django_send_mail_test": django_status,
            "recipient": request.user.email,
            "message": "Check your email inbox and console logs for detailed results"
        })
        
    except Exception as e:
        print(f"❌ [EMAIL TEST] Major error: {e}")
        import traceback
        traceback.print_exc()
        return Response({"error": str(e)}, status=500)
    
# IST timezone

class CancelRescheduleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        # 1. Check if user has ever booked a session
        last_session_any = (
            SessionBooking.objects.filter(user=user)
            .select_related('mentor', 'mentor__user')
            .order_by("-created_at")
            .first()
        )
        if not last_session_any:
            return Response(
                {"message": "❌ No booked sessions found."},
                status=status.HTTP_404_NOT_FOUND
            )

        # 2. Get last active (non-cancelled) session
        last_session = (
            SessionBooking.objects.filter(user=user)
            .exclude(status="cancelled")
            .select_related('mentor', 'mentor__user')
            .order_by("-created_at")
            .first()
        )
        if not last_session:
            return Response(
                {"message": "❌ No active sessions found to cancel. All your sessions are already cancelled."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Store session info before cancelling
        session_info = {
            'event_id': getattr(last_session, 'event_id', None),
            'start_time': last_session.start_time,
            'mentor_name': last_session.mentor.user.username if last_session.mentor else "Mentor",
            'student_name': user.username
        }

        # 3. Cancel session in database first
        last_session.status = "cancelled"
        last_session.save()
        print(f"✅ Session {last_session.id} marked as cancelled in database")

        # 4. Remove from Google Calendar (with enhanced error handling)
        calendar_cancelled = False
        if session_info['event_id']:
            try:
                # Import the improved cancel function
                from .calendar_client import cancel_calendar_event
                calendar_cancelled = cancel_calendar_event(session_info['event_id'])
                
                if calendar_cancelled:
                    print(f"✅ Calendar event {session_info['event_id']} cancelled successfully")
                else:
                    print(f"⚠️ Calendar event {session_info['event_id']} cancellation had issues")
                    
            except ImportError as import_err:
                print(f"⚠️ Could not import calendar function: {import_err}")
                
            except Exception as cal_err:
                print(f"⚠️ Calendar cancellation error: {cal_err}")
        else:
            print("ℹ️ No event_id found for calendar cancellation")

        # 5. Send cancellation emails
        email_sent = False
        try:
            student_email = user.email
            student_name = user.first_name or user.username or "Student"
            mentor_profile = last_session.mentor
            mentor_email = mentor_profile.user.email if mentor_profile else None
            mentor_name = mentor_profile.user.first_name or mentor_profile.user.username if mentor_profile else "Mentor"

            if student_email and mentor_email:
                # Import and use the fixed email function
                from .emails import send_cancellation_email
                
                email_sent = send_cancellation_email(
                    session=last_session,
                    student_email=student_email,
                    student_name=student_name,
                    mentor_email=mentor_email,
                    mentor_name=mentor_name
                )
                
                if email_sent:
                    print(f"✅ Cancellation emails sent successfully")
                else:
                    print(f"⚠️ Email sending had issues (check logs)")
                    
            else:
                print(f"⚠️ Missing email addresses: student={student_email}, mentor={mentor_email}")
                
        except ImportError as import_err:
            print(f"⚠️ Could not import email function: {import_err}")
            
        except Exception as email_err:
            print(f"⚠️ Failed to send cancellation emails: {email_err}")
            import traceback
            traceback.print_exc()

        # 6. Prepare response message based on what succeeded
        success_parts = []
        warning_parts = []
        
        success_parts.append("✅ Your session has been cancelled")
        
        if email_sent:
            success_parts.append("confirmation emails have been sent")
        else:
            warning_parts.append("email notifications may have failed")
            
        if calendar_cancelled:
            success_parts.append("calendar event has been removed")
        elif session_info['event_id']:
            warning_parts.append("calendar removal may have had issues")

        # Build final message
        if success_parts:
            message = " and ".join(success_parts) + "."
            if warning_parts:
                message += f" Note: {', '.join(warning_parts)}."
        else:
            message = "✅ Your session has been cancelled in the system."

        return Response(
            {"message": message},
            status=status.HTTP_200_OK
        )

        
class ScheduleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    HEAD_EMAIL = "sunilramtri000@gmail.com"
    HEAD_NAME = "Vardaan Shekhawat (Head Mentor)"

    def post(self, request):
        try:
            print("📌 [DEBUG] ScheduleView POST called")

            data = request.data
            mentor_id = data.get("mentor_id")
            selected_slot = data.get("selected_slot")
            domain = data.get("domain")
            auto_select = data.get("auto_select", False)
            auto_book = data.get("auto_book", False)
            preferred_day = data.get("preferred_day")

            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            print(f"👀 {request.user.email} session_count: {profile.session_count}")

            if not profile.is_premium:
                return Response({"error": "Only premium users can book sessions."}, status=403)

            # PRIORITY 1: HEAD mentor case (ONLY for first-time users OR explicit head request)
            if mentor_id == "head" or (is_first_time_user(request.user) and mentor_id is None):
                head_email = "sunilramtri000@gmail.com"
                head_name = "Sunil (Head Mentor)"
                print(f"🎯 [HEAD] Using head mentor: {head_email}")

                # Get available slots for head mentor
                if preferred_day:
                    available_slots = self.get_slots_for_specific_day(head_email, preferred_day)
                else:
                    available_slots = get_next_available_slots_for_user(head_email, count=1)

                if not available_slots:
                    return Response({
                        "error": "No available slots found with head mentor",
                        "show_day_filter": True,
                        "available_days": self.get_available_days(head_email),
                        "mentor_name": head_name
                    }, status=200)

                earliest_slot = available_slots[0]

                # If user provided selected_slot, book it
                if selected_slot:
                    return self.confirm_booking(
                        request.user,
                        head_email,
                        head_name,
                        selected_slot,
                        profile,
                        mentor=None
                    )

                # Otherwise, return earliest slot for confirmation
                return Response({
                    "message": f"Your earliest available slot with {head_name} is:",
                    "earliest_slot": {
                        "start_time": earliest_slot["start_time"].isoformat(),
                        "end_time": earliest_slot["end_time"].isoformat(),
                        "formatted_date": earliest_slot["formatted_date"],
                        "formatted_time": earliest_slot["formatted_time"]
                    },
                    "mentor_name": head_name,
                    "requires_confirmation": True,
                    "show_day_filter": True,
                    "available_days": self.get_available_days(head_email),
                    "selected_mentor_id": "head"
                }, status=200)

            # PRIORITY 2: Specific mentor by ID (This should take precedence over domain)
            if mentor_id and mentor_id != "head":
                try:
                    selected_mentor = Mentor.objects.get(id=mentor_id, is_active=True)
                    mentor_email = selected_mentor.user.email.strip()
                    mentor_name = selected_mentor.user.username
                    print(f"🎯 Specific mentor selected: {mentor_name} <{mentor_email}>")
                    
                    # Get available slots for the SPECIFIC mentor (not head mentor)
                    if preferred_day:
                        available_slots = self.get_slots_for_specific_day(mentor_email, preferred_day)
                    else:
                        available_slots = get_next_available_slots_for_user(mentor_email, count=1)

                    if not available_slots:
                        return Response({
                            "error": f"No available slots found for {mentor_name}",
                            "show_day_filter": True,
                            "available_days": self.get_available_days(mentor_email),
                            "mentor_name": mentor_name
                        }, status=200)

                    earliest_slot = available_slots[0]

                    # If user provided selected_slot, book it with the SPECIFIC mentor
                    if selected_slot:
                        return self.confirm_booking(
                            request.user,
                            mentor_email,  # Use the specific mentor's email, not head
                            mentor_name,   # Use the specific mentor's name
                            selected_slot,
                            profile,
                            selected_mentor  # Pass the actual mentor object
                        )

                    return Response({
                        "message": f"Your earliest available slot with {mentor_name} is:",
                        "earliest_slot": {
                            "start_time": earliest_slot["start_time"].isoformat(),
                            "end_time": earliest_slot["end_time"].isoformat(),
                            "formatted_date": earliest_slot["formatted_date"],
                            "formatted_time": earliest_slot["formatted_time"]
                        },
                        "mentor_name": mentor_name,
                        "requires_confirmation": True,
                        "show_day_filter": True,
                        "available_days": self.get_available_days(mentor_email),
                        "selected_mentor_id": selected_mentor.id
                    }, status=200)
                    
                except Mentor.DoesNotExist:
                    print(f"⚠️ Mentor with ID {mentor_id} not found")
                    return Response({
                        "error": f"Mentor with ID {mentor_id} not found"
                    }, status=400)

            # PRIORITY 3: Domain-based mentor selection (only for non-first-time users without specific mentor)
            if domain and not is_first_time_user(request.user) and not mentor_id:
                selected_mentor = get_random_mentor_by_domain(domain)

                if not selected_mentor or not getattr(selected_mentor.user, "email", None):
                    print(f"⚠️ No valid mentor for {domain}, falling back to HEAD")
                    mentor_email = self.HEAD_EMAIL
                    mentor_name = self.HEAD_NAME
                    selected_mentor = None
                else:
                    mentor_email = selected_mentor.user.email.strip()
                    mentor_name = selected_mentor.user.username

                print(f"🎯 Domain mentor selected: {mentor_name} <{mentor_email}>")

                if preferred_day:
                    available_slots = self.get_slots_for_specific_day(mentor_email, preferred_day)
                else:
                    available_slots = get_next_available_slots_for_user(mentor_email, count=1)

                if not available_slots:
                    return Response({
                        "error": "No available slots found for this day",
                        "show_day_filter": True,
                        "available_days": self.get_available_days(mentor_email),
                        "domain": domain.title()
                    }, status=200)

                earliest_slot = available_slots[0]

                if selected_slot:
                    return self.confirm_booking(
                        request.user,
                        mentor_email,
                        mentor_name,
                        selected_slot,
                        profile,
                        selected_mentor
                    )

                return Response({
                    "message": f"Your earliest available slot for {domain.title()} mentorship is:",
                    "earliest_slot": {
                        "start_time": earliest_slot["start_time"].isoformat(),
                        "end_time": earliest_slot["end_time"].isoformat(),
                        "formatted_date": earliest_slot["formatted_date"],
                        "formatted_time": earliest_slot["formatted_time"]
                    },
                    "domain": domain.title(),
                    "domain_description": self.get_domain_description(domain),
                    "requires_confirmation": True,
                    "show_day_filter": True,
                    "available_days": self.get_available_days(mentor_email),
                    "selected_mentor_id": selected_mentor.id if selected_mentor else "head"
                }, status=200)

            # ERROR: If no valid parameters provided
            return Response({
                "error": "Invalid request. Please specify mentor_id or provide domain for domain-based booking."
            }, status=400)

        except Exception as e:
            print(f"❌ [SCHEDULE] Unexpected error: {e}")
            traceback.print_exc()
            return Response({"error": f"Scheduling error: {str(e)}"}, status=500)

    def confirm_booking(self, user, mentor_email, display_name, selected_slot, profile, mentor=None):
        """Confirm and create the booking with enhanced error handling"""
        try:
            print(f"🔧 [BOOKING] Starting confirmation for {user.email}")
            print(f"🔧 [BOOKING] Selected slot: {selected_slot}")
            print(f"🔧 [BOOKING] Mentor email: {mentor_email}")
            print(f"🔧 [BOOKING] Display name: {display_name}")
            
            # Validate slot data
            if not isinstance(selected_slot, dict):
                print(f"❌ [BOOKING] Invalid slot format: {type(selected_slot)}")
                return Response({"error": "Invalid slot data format"}, status=400)
            
            slot_start_str = selected_slot.get("start_time")
            slot_end_str = selected_slot.get("end_time")
            
            if not slot_start_str or not slot_end_str:
                print(f"❌ [BOOKING] Missing times: start={slot_start_str}, end={slot_end_str}")
                return Response({"error": "Missing start_time or end_time"}, status=400)

            # Parse datetime strings
            try:
                slot_start = parse_datetime(slot_start_str) if isinstance(slot_start_str, str) else slot_start_str
                slot_end = parse_datetime(slot_end_str) if isinstance(slot_end_str, str) else slot_end_str
                
                # Fallback to dateutil parser
                if slot_start is None and dateutil_parser and isinstance(slot_start_str, str):
                    slot_start = dateutil_parser.parse(slot_start_str)
                if slot_end is None and dateutil_parser and isinstance(slot_end_str, str):
                    slot_end = dateutil_parser.parse(slot_end_str)
                
                print(f"🔧 [BOOKING] Parsed times: start={slot_start}, end={slot_end}")
                
            except Exception as parse_error:
                print(f"❌ [BOOKING] Datetime parsing failed: {parse_error}")
                return Response({"error": f"Invalid datetime format: {str(parse_error)}"}, status=400)
            
            if not slot_start or not slot_end:
                return Response({"error": "Could not parse datetime strings"}, status=400)

            # Ensure timezone awareness
            IST = timezone.get_fixed_timezone(5*60 + 30)
            if slot_start.tzinfo is None:
                slot_start = timezone.make_aware(slot_start, IST)
            if slot_end.tzinfo is None:
                slot_end = timezone.make_aware(slot_end, IST)

            # IMPORTANT: Don't override mentor_email here - use the one passed in
            print(f"🔧 [BOOKING] Final mentor email (not changed): {mentor_email}")
            print(f"🔧 [BOOKING] Calling schedule_specific_slot...")
            print(f"  - Student: {user.email}")
            print(f"  - Mentor: {mentor_email}")
            print(f"  - Times: {slot_start} to {slot_end}")

            # Schedule the session with the correct mentor
            try:
                result = schedule_specific_slot(
                    student_email=user.email,
                    mentor_email=mentor_email,  # This should be the selected mentor's email
                    slot_start=slot_start,
                    slot_end=slot_end,
                    student_name=user.username,
                    mentor_name=display_name
                )
                print(f"🔧 [BOOKING] Schedule result: {result}")
                
            except Exception as schedule_error:
                print(f"❌ [BOOKING] Scheduling failed: {schedule_error}")
                traceback.print_exc()
                return Response({"error": f"Scheduling failed: {str(schedule_error)}"}, status=500)

            if not result.get("success"):
                error_msg = result.get("error", "Unknown scheduling error")
                print(f"❌ [BOOKING] Scheduling error: {error_msg}")
                return Response({"error": error_msg}, status=500)

            # Create booking record
            try:
                booking = SessionBooking.objects.create(
                    user=user,
                    mentor=mentor,  # This should be the actual mentor object
                    organizer="UK Jobs Mentorship System",
                    start_time=result["start_time"],
                    end_time=result["end_time"],
                    meet_link=result.get("meet_link", ""),
                    attendees=[user.email, mentor_email],  # Correct mentor email
                    event_id=result.get("event_id", ""),
                    status="confirmed"
                )
                print(f"✅ [BOOKING] Created booking: {booking.id}")

            except Exception as db_error:
                print(f"❌ [BOOKING] Database error: {db_error}")
                traceback.print_exc()
                return Response({"error": f"Failed to save booking: {str(db_error)}"}, status=500)

            # Send email to correct participants
            try:
                send_enhanced_manual_invitations(
                    attendees=[user.email, mentor_email],  # Correct mentor email
                    meet_link=result["meet_link"],
                    start_time=result["start_time"],
                    end_time=result["end_time"],
                    student_name=user.username,
                    mentor_name=display_name,
                    session_type="1-on-1 Mentorship"
                )
                print(f"✅ [BOOKING] Email sent to {mentor_email}")
            except Exception as email_error:
                print(f"⚠️ [BOOKING] Email failed (non-critical): {email_error}")

            # Update session count
            profile.session_count += 1
            profile.save()

            # Format response
            start_formatted = result["start_time"].strftime('%A, %B %d at %I:%M %p')
            
            return Response({
                "success": True,
                "message": f"Your session with {display_name} is confirmed for {start_formatted} IST!",
                "booking_id": booking.id,
                "meet_link": result["meet_link"],
                "calendar_link": result.get("calendar_link", ""),
                "start_time": result["start_time"].isoformat(),
                "end_time": result["end_time"].isoformat(),
                "session_type": display_name,
                "session_count": profile.session_count,
                "mentor_name": display_name,
                "mentor_email": mentor_email  # For debugging
            }, status=200)

        except Exception as e:
            print(f"❌ [BOOKING] Unexpected error: {e}")
            traceback.print_exc()
            return Response({"error": f"Booking failed: {str(e)}"}, status=500)

    # Keep other methods unchanged
    def get_available_days(self, email):
        """Get list of days in next 7 days that have available slots"""
        try:
            from .calendar_client import get_available_days_for_user
            return get_available_days_for_user(email, max_days=7)
        except Exception as e:
            print(f"❌ Error getting available days: {e}")
            return []

    def get_slots_for_specific_day(self, email, day_name):
        """Get available slots for a specific day"""
        try:
            from .calendar_client import get_slots_for_specific_day_helper
            return get_slots_for_specific_day_helper(email, day_name)
        except Exception as e:
            print(f"❌ Error getting slots for day: {e}")
            return []

    def get_domain_description(self, domain):
        """Get user-friendly description for domain"""
        descriptions = {
            'marketing': 'Digital Marketing & Growth Strategies',
            'cv': 'CV Writing & Career Documents', 
            'linkedin': 'LinkedIn Profile Optimization',
            'testing': 'QA & Test Automation',
            'data': 'Data Science & Analytics',
            'development': 'Software Development',
            'design': 'UI/UX Design',
            'finance': 'Finance & Investment',
            'hr': 'HR & Recruitment',
            'general': 'General Career Guidance'
        }
        return descriptions.get(domain, f'{domain.title()} Expertise')

    def confirm_booking(self, user, mentor_email, display_name, selected_slot, profile, mentor=None):
        """Confirm and create the booking with enhanced error handling"""
        try:
            print(f"🔧 [BOOKING] Starting confirmation for {user.email}")
            print(f"🔧 [BOOKING] Selected slot: {selected_slot}")
            print(f"🔧 [BOOKING] Mentor email: {mentor_email}")
            
            # Validate slot data
            if not isinstance(selected_slot, dict):
                print(f"❌ [BOOKING] Invalid slot format: {type(selected_slot)}")
                return Response({"error": "Invalid slot data format"}, status=400)
            
            slot_start_str = selected_slot.get("start_time")
            slot_end_str = selected_slot.get("end_time")
            
            if not slot_start_str or not slot_end_str:
                print(f"❌ [BOOKING] Missing times: start={slot_start_str}, end={slot_end_str}")
                return Response({"error": "Missing start_time or end_time"}, status=400)

            # Parse datetime strings with multiple fallback methods
            try:
                # Method 1: Django's parse_datetime
                slot_start = parse_datetime(slot_start_str) if isinstance(slot_start_str, str) else slot_start_str
                slot_end = parse_datetime(slot_end_str) if isinstance(slot_end_str, str) else slot_end_str
                
                # Method 2: dateutil parser (if Django fails)
                if slot_start is None and dateutil_parser and isinstance(slot_start_str, str):
                    slot_start = dateutil_parser.parse(slot_start_str)
                if slot_end is None and dateutil_parser and isinstance(slot_end_str, str):
                    slot_end = dateutil_parser.parse(slot_end_str)
                
                print(f"🔧 [BOOKING] Parsed times: start={slot_start}, end={slot_end}")
                
            except Exception as parse_error:
                print(f"❌ [BOOKING] Datetime parsing failed: {parse_error}")
                return Response({"error": f"Invalid datetime format: {str(parse_error)}"}, status=400)
            
            if not slot_start or not slot_end:
                return Response({"error": "Could not parse datetime strings"}, status=400)

            # Ensure timezone awareness
            IST = timezone.get_fixed_timezone(5*60 + 30)
            if slot_start.tzinfo is None:
                slot_start = timezone.make_aware(slot_start, IST)
            if slot_end.tzinfo is None:
                slot_end = timezone.make_aware(slot_end, IST)

            # Correct head mentor email
            if mentor_email == "head":
                mentor_email = "sunilramtri000@gmail.com"

            print(f"🔧 [BOOKING] Calling schedule_specific_slot...")
            print(f"  - Student: {user.email}")
            print(f"  - Mentor: {mentor_email}")
            print(f"  - Times: {slot_start} to {slot_end}")

            # Schedule the session
            try:
                result = schedule_specific_slot(
                    student_email=user.email,
                    mentor_email=mentor_email,
                    slot_start=slot_start,
                    slot_end=slot_end,
                    student_name=user.username,
                    mentor_name=display_name
                )
                print(f"🔧 [BOOKING] Schedule result: {result}")
                
            except Exception as schedule_error:
                print(f"❌ [BOOKING] Scheduling failed: {schedule_error}")
                traceback.print_exc()
                return Response({"error": f"Scheduling failed: {str(schedule_error)}"}, status=500)

            if not result.get("success"):
                error_msg = result.get("error", "Unknown scheduling error")
                print(f"❌ [BOOKING] Scheduling error: {error_msg}")
                return Response({"error": error_msg}, status=500)

            # Create booking record
            try:
                booking = SessionBooking.objects.create(
                    user=user,
                    mentor=mentor,
                    organizer="UK Jobs Mentorship System",
                    start_time=result["start_time"],
                    end_time=result["end_time"],
                    meet_link=result.get("meet_link", ""),
                    attendees=[user.email, mentor_email],
                    event_id=result.get("event_id", ""),
                    status="confirmed"
                )
                print(f"✅ [BOOKING] Created booking: {booking.id}")

            except Exception as db_error:
                print(f"❌ [BOOKING] Database error: {db_error}")
                traceback.print_exc()
                return Response({"error": f"Failed to save booking: {str(db_error)}"}, status=500)

            # Send email (non-blocking)
            try:
                send_enhanced_manual_invitations(
                    attendees=[user.email, mentor_email],
                    meet_link=result["meet_link"],
                    start_time=result["start_time"],
                    end_time=result["end_time"],
                    student_name=user.username,
                    mentor_name=display_name,
                    session_type="1-on-1 Mentorship"
                )
                print(f"✅ [BOOKING] Email sent")
            except Exception as email_error:
                print(f"⚠️ [BOOKING] Email failed (non-critical): {email_error}")

            # Update session count
            profile.session_count += 1
            profile.save()

            # Format response
            start_formatted = result["start_time"].strftime('%A, %B %d at %I:%M %p')
            
            return Response({
                "success": True,
                "message": f"Your session with {display_name} is confirmed for {start_formatted} IST!",
                "booking_id": booking.id,
                "meet_link": result["meet_link"],
                "calendar_link": result.get("calendar_link", ""),
                "start_time": result["start_time"].isoformat(),
                "end_time": result["end_time"].isoformat(),
                "session_type": display_name,
                "session_count": profile.session_count,
                "mentor_name": display_name
            }, status=200)

        except Exception as e:
            print(f"❌ [BOOKING] Unexpected error: {e}")
            traceback.print_exc()
            return Response({"error": f"Booking failed: {str(e)}"}, status=500)



class AvailableSlotsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return next 5 available 2-hour slots"""
        try:
            from .calendar_client import find_next_available_2hour_slot
            
            available_slots = []
            current_time = datetime.now()
            
            # Get next 5 available slots
            for i in range(5):
                try:
                    start_time, end_time = find_next_available_2hour_slot()
                    available_slots.append({
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "formatted_time": f"{start_time.strftime('%A, %B %d at %I:%M %p')} - {end_time.strftime('%I:%M %p')} IST",
                        "duration_hours": 2
                    })
                    # Move to next day to find next slot
                    current_time += timedelta(days=1)
                except:
                    break
            
            return Response({
                "available_slots": available_slots,
                "message": f"Found {len(available_slots)} available 2-hour slots"
            }, status=200)
            
        except Exception as e:
            print(f"Error getting available slots: {e}")
            return Response({
                "error": "Could not fetch available slots"
            }, status=500)

class ChatView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            data = request.data
            message = data.get("message", "").strip()
            if not message:
                return Response({"error": "Message is required"}, status=400)

            profile = UserProfile.objects.filter(user=request.user).first()
            is_premium = profile.is_premium if profile else False

            # PRIORITY 1: Check for cancellation requests FIRST
            if is_cancel_request(message):
                if not is_premium:
                    return Response({
                        "reply": "⚠️ Only premium users can manage sessions. Please upgrade to premium.",
                        "mentors": None
                    }, status=200)
                
                # Get last ACTIVE (non-cancelled) session
                last_session = (
                    SessionBooking.objects.filter(user=request.user)
                    .exclude(status="cancelled")  # Exclude already cancelled sessions
                    .order_by("-created_at")
                    .first()
                )

                if not last_session:
                    return Response({
                        "reply": "❌ No active booked sessions found to cancel.",
                        "mentors": None
                    }, status=200)

                # Convert start_time to readable format
                session_start = last_session.start_time
                if isinstance(session_start, str):
                    from django.utils.dateparse import parse_datetime
                    session_start = parse_datetime(session_start)

                # Ensure timezone aware
                from django.utils import timezone
                IST = timezone.get_fixed_timezone(5*60 + 30)
                if session_start.tzinfo is None:
                    session_start = timezone.make_aware(session_start, IST)

                session_time_ist = session_start.astimezone(IST).strftime('%d %b %Y, %I:%M %p')
                mentor_name = last_session.mentor.user.username if last_session.mentor else "Mentor"

                return Response({
                    "reply": f"📅 I found your active session with {mentor_name} scheduled for {session_time_ist}.\n\nAre you sure you want to cancel this session?",
                    "session_actions": True,  # This will trigger the cancel/reschedule UI
                    "session_details": {
                        "mentor_name": mentor_name,
                        "session_time": session_time_ist,
                        "session_id": last_session.id
                    }
                }, status=200)

            # PRIORITY 2: Check for meeting/booking requests  
            if is_meeting_request(message):
                if not is_premium:
                    return Response({
                        "reply": "⚠️ Only premium users can book mentorship sessions. Please upgrade to premium.",
                        "mentors": None
                    }, status=200)
                
                # Detect domain from message
                detected_domain = detect_domain_from_message(message)
                
                if is_first_time_user(request.user):
                    # First time user - show head mentor only
                    head_mentor = {
                        "id": "head",
                        "username": "Vardaan (Head Mentor)",
                        "email": "sunilramtri000@gmail.com",
                        "expertise": "Initial Assessment & Career Guidance"
                    }
                    
                    return Response({
                        "reply": "🎯 Welcome! As a first-time premium user, your initial session will be with our Head Mentor for assessment and guidance. Please select to continue:",
                        "mentors": [head_mentor],
                        "is_first_time": True,
                        "detected_domain": detected_domain
                    }, status=200)
                
                else:
                    # If domain detected, auto-select mentor
                    if detected_domain != 'general':
                        selected_mentor = get_random_mentor_by_domain(detected_domain)
                        
                        if selected_mentor:
                            return Response({
                                "reply": f"🎯 I detected you're interested in {detected_domain.title()} domain. I've selected {selected_mentor.user.username} as your mentor specialist for this area.",
                                "mentors": [{
                                    "id": selected_mentor.id,
                                    "username": selected_mentor.user.username,
                                    "email": selected_mentor.user.email,
                                    "expertise": selected_mentor.expertise
                                }],
                                "is_first_time": False,
                                "detected_domain": detected_domain,
                                "auto_selected": True,
                                "auto_mentor_id": selected_mentor.id
                            }, status=200)
                    
                    # Fallback: show all mentors
                    mentors = Mentor.objects.filter(is_active=True).select_related("user")
                    mentor_list = [
                        {
                            "id": m.id,
                            "username": m.user.username,
                            "email": m.user.email,
                            "expertise": m.expertise
                        }
                        for m in mentors
                    ]

                    return Response({
                        "reply": "📅 I can help you schedule a mentorship session. Please select a mentor:",
                        "mentors": mentor_list,
                        "is_first_time": False,
                        "detected_domain": detected_domain
                    }, status=200)

            # PRIORITY 3: Default AI chat for other messages
            reply = ask_gemini(message, is_premium)
            return Response({"reply": reply}, status=200)

        except Exception as e:
            traceback.print_exc()
            return Response({"error": str(e)}, status=500)

# Add new endpoint to get mentors by domain
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_mentors_by_domain(request):
    """Get mentors filtered by domain"""
    try:
        domain = request.GET.get('domain', 'general')
        
        profile = UserProfile.objects.filter(user=request.user).first()
        if not profile or not profile.is_premium:
            return Response({"error": "Only premium users can access mentors"}, status=403)
        
        if domain == 'general':
            mentors = Mentor.objects.filter(is_active=True).select_related("user")
        else:
            # Filter by domain keywords
            mentors = Mentor.objects.filter(is_active=True).select_related("user")
            domain_mentors = []
            
            for mentor in mentors:
                expertise_lower = mentor.expertise.lower() if mentor.expertise else ""
                keywords = DOMAIN_KEYWORDS.get(domain, [])
                
                if any(keyword in expertise_lower for keyword in keywords):
                    domain_mentors.append(mentor)
            
            mentors = domain_mentors

        mentor_list = [
            {
                "id": m.id,
                "username": m.user.username,
                "email": m.user.email,
                "expertise": m.expertise,
                "domain": domain
            }
            for m in mentors
        ]
        
        return Response({
            "mentors": mentor_list,
            "domain": domain,
            "count": len(mentor_list)
        }, status=200)
        
    except Exception as e:
        print(f"Error getting mentors by domain: {e}")
        return Response({"error": str(e)}, status=500)