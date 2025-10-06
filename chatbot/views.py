import traceback
import random
from .models import SessionBooking, UserProfile, TimeSlot, EnhancedSessionBooking, Mentor
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
from .services import schedule_between_two_users
import json
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import csv
import os
from django.core.exceptions import ValidationError
from django.conf import settings
from .gemini_client import ask_gemini
from .utils import is_meeting_request, extract_duration
from datetime import datetime, timedelta
from django.core.mail import EmailMultiAlternatives
from .calendar_client import (
    schedule_specific_slot,
    get_next_available_slots_for_user,
    send_enhanced_manual_invitations,
    cancel_calendar_event,
    get_mentor_config,
    MENTOR_CONFIG,
    book_time_slot
)
from django.utils import timezone
from .emails import send_cancellation_email
from django.utils.dateparse import parse_datetime
try:
    from dateutil import parser as dateutil_parser
except ImportError:
    dateutil_parser = None

from zoneinfo import ZoneInfo
UK_TZ = ZoneInfo("Europe/London")

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
    """Ensure datetime object is timezone-aware in UK_TZ"""
    from django.utils import timezone
    
    if dt_obj is None:
        return None
        
    UK_TZ = ZoneInfo("UTC")
    
    if isinstance(dt_obj, str):
        from django.utils.dateparse import parse_datetime
        dt_obj = parse_datetime(dt_obj)
        if dt_obj is None:
            raise ValueError(f"Cannot parse datetime: {dt_obj}")
    
    if dt_obj.tzinfo is None:
        dt_obj = timezone.make_aware(dt_obj, UK_TZ)
    
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
        # Check both old and new booking models
        old_bookings = SessionBooking.objects.filter(
            user=user, 
            status='confirmed'
        ).count()
        
        new_bookings = EnhancedSessionBooking.objects.filter(
            user=user, 
            status='confirmed'
        ).count()
        
        return (old_bookings + new_bookings) == 0
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
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(minutes=15),
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

            if not is_email_allowed(email):
                return Response({
                    "error": "This email is not allowed to signup. Please contact support."
                }, status=status.HTTP_403_FORBIDDEN)

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
    UK_TZ = ZoneInfo("UTC")
    
    if isinstance(dt_str_or_dt, str):
        dt = parse_datetime(dt_str_or_dt)
        if dt is None:
            raise ValueError(f"Invalid datetime string: {dt_str_or_dt}")
    else:
        dt = dt_str_or_dt

    if dt.tzinfo is None:
        dt = timezone.make_aware(dt, UK_TZ)
    return dt

@method_decorator(csrf_exempt, name="dispatch")
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            token = getattr(request.user, "auth_token", None)
            if token:
                token.delete()
            return Response({"message": "Logged out successfully"}, status=status.HTTP_200_OK)
        except Exception:
            # Even if token is missing or invalid
            return Response({"message": "Logout safe"}, status=status.HTTP_200_OK)


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
            return Response({"error": "Only Plus users can access mentors"}, status=403)
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
- Sent at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UK_TZ')}  
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
    
class CancelRescheduleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        # 1. Check if user has ever booked a session (both old and new models)
        last_session_any = None
        
        # Check EnhancedSessionBooking first
        last_new_session = (
            EnhancedSessionBooking.objects.filter(user=user)
            .select_related('mentor', 'mentor__user')
            .order_by("-created_at")
            .first()
        )
        
        if last_new_session:
            last_session_any = last_new_session
        else:
            # Fall back to old SessionBooking
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
        last_session = None
        
        # Check EnhancedSessionBooking first
        last_new_session = (
            EnhancedSessionBooking.objects.filter(user=user)
            .exclude(status="cancelled")
            .select_related('mentor', 'mentor__user')
            .order_by("-created_at")
            .first()
        )
        
        if last_new_session:
            last_session = last_new_session
        else:
            # Fall back to old SessionBooking
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

        # Convert start_time to UK timezone for consistent display
        start_time_utc = last_session.start_time
        if isinstance(start_time_utc, str):
            from django.utils.dateparse import parse_datetime
            start_time_utc = parse_datetime(start_time_utc)

        # ✅ FIX: Properly handle timezone conversion
        from zoneinfo import ZoneInfo
        UK_TZ_PROPER = ZoneInfo("Europe/London")

        if start_time_utc.tzinfo is None:
            # If naive, assume it's UK time
            start_time_uk = start_time_utc.replace(tzinfo=UK_TZ_PROPER)
        else:
            # If aware, convert to UK
            start_time_uk = start_time_utc.astimezone(UK_TZ_PROPER)

        # Store session info
        session_info = {
            'event_id': getattr(last_session, 'event_id', None),
            'start_time': start_time_uk,
            'start_time_formatted': start_time_uk.strftime('%A, %B %d, %Y at %I:%M %p UK Time'),
            'mentor_email': last_session.mentor.user.email if last_session.mentor else None,
            'mentor_name': last_session.mentor.user.first_name or last_session.mentor.user.username if last_session.mentor else 'Mentor',
            'student_name': user.username,
            'is_enhanced': isinstance(last_session, EnhancedSessionBooking)
        }

        print(f"🕐 Cancelling session scheduled at: {session_info['start_time_formatted']}")

        # 3. Cancel session in database first
        last_session.status = "cancelled"
        last_session.save()
        print(f"✅ Session {last_session.id} marked as cancelled in database")

        # 4. Remove from Google Calendar (with enhanced error handling)
        calendar_cancelled = False
        if session_info['event_id']:
            try:
                mentor_email = session_info['mentor_email']
                if mentor_email:
                    calendar_cancelled = cancel_calendar_event(session_info['event_id'], mentor_email)
                
                if calendar_cancelled:
                    print(f"✅ Calendar event {session_info['event_id']} cancelled successfully")
                else:
                    print(f"⚠️ Calendar event {session_info['event_id']} cancellation had issues")
                    
            except Exception as cal_err:
                print(f"⚠️ Calendar cancellation error: {cal_err}")
        else:
            print("ℹ️ No event_id found for calendar cancellation")

        # 5. Send cancellation emails with UK time
        email_sent = False
        try:
            student_email = user.email
            student_name = user.first_name or user.username or "Student"

            if student_email and session_info['mentor_email']:
                email_sent = send_cancellation_email(
                    session=last_session,
                    student_email=student_email,
                    student_name=student_name,
                    mentor_email=session_info['mentor_email'],
                    mentor_name=session_info['mentor_name']
                )
                
                if email_sent:
                    print(f"✅ Cancellation emails sent successfully")
                else:
                    print(f"⚠️ Email sending had issues (check logs)")
                    
            else:
                print(f"⚠️ Missing email addresses: student={student_email}, mentor={session_info['mentor_email']}")
                
        except Exception as email_err:
            print(f"⚠️ Failed to send cancellation emails: {email_err}")
            import traceback
            traceback.print_exc()

        # 6. Build response message with UK time
        success_parts = ["✅ Your session has been cancelled"]
        warning_parts = []
        
        success_parts.append("confirmation emails have been sent" if email_sent else "")
        if not email_sent:
            warning_parts.append("email notifications may have failed")
            
        if calendar_cancelled:
            success_parts.append("calendar event has been removed")
        elif session_info['event_id']:
            warning_parts.append("calendar removal may have had issues")

        # Build final message with session details
        message_parts = [part for part in success_parts if part]
        message = " and ".join(message_parts) + "."
        if warning_parts:
            message += f" Note: {', '.join(warning_parts)}."

        return Response({
            "message": message,
            "cancelled_session": {
                "mentor_name": session_info['mentor_name'],
                "session_time": session_info['start_time_formatted'],  # Use UK formatted time
                "booking_id": last_session.id
            }
        }, status=status.HTTP_200_OK)

class TimeSlotListView(APIView):
    """View to list available time slots for a mentor"""
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, mentor_id=None):
        try:
            # Check if user is premium
            profile = UserProfile.objects.get(user=request.user)
            if not profile.is_premium:
                return Response({"error": "Only Plus users can view time slots"}, status=403)
            
            # Get mentor
            if mentor_id:
                try:
                    mentor = Mentor.objects.get(id=mentor_id, is_active=True)
                except Mentor.DoesNotExist:
                    return Response({"error": "Mentor not found"}, status=404)
            else:
                # Default to head mentor
                head_email = MENTOR_CONFIG.get("head", {}).get("email")
                if not head_email:
                    return Response({"error": "Head mentor configuration not found"}, status=500)
                
                try:
                    mentor = Mentor.objects.get(user__email=head_email, is_active=True)
                except Mentor.DoesNotExist:
                    return Response({"error": "Head mentor not found"}, status=404)
            
            # Get date range from query parameters
            start_date_str = request.GET.get('start_date')
            end_date_str = request.GET.get('end_date')
            
            # Default to next 7 days
            start_date = timezone.now().date()
            if start_date_str:
                try:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                except ValueError:
                    return Response({"error": "Invalid start_date format. Use YYYY-MM-DD"}, status=400)
            
            end_date = start_date + timedelta(days=7)
            if end_date_str:
                try:
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                except ValueError:
                    return Response({"error": "Invalid end_date format. Use YYYY-MM-DD"}, status=400)
            
            # Get available time slots
            slots = TimeSlot.objects.filter(
                mentor=mentor,
                date__gte=start_date,
                date__lte=end_date,
                is_available=True,
                is_booked=False
            ).order_by('date', 'start_time')
            
            # Format slots for response
            slot_list = []
            for slot in slots:
                slot_list.append({
                    "id": slot.id,
                    "date": slot.date.isoformat(),
                    "start_time": slot.start_time.isoformat(),
                    "end_time": slot.end_time.isoformat(),
                    "formatted_date": slot.date.strftime('%A, %B %d'),
                    "formatted_time": f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
                    "datetime_start": slot.datetime_start.isoformat(),
                    "datetime_end": slot.datetime_end.isoformat(),
                })
            
            return Response({
                "mentor": {
                    "id": mentor.id,
                    "name": mentor.user.username,
                    "email": mentor.user.email,
                    "expertise": mentor.expertise
                },
                "slots": slot_list,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat()
            })
            
        except UserProfile.DoesNotExist:
            return Response({"error": "User profile not found"}, status=404)
        except Exception as e:
            print(f"❌ Error getting time slots: {e}")
            return Response({"error": "Failed to get time slots"}, status=500)
        
class TimeSlotCancelView(APIView):
    """Cancel a booked time slot"""
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            
            # Check if user is premium
            profile = UserProfile.objects.get(user=user)
            if not profile.is_premium:
                return Response({
                    "error": "Only Plus users can manage sessions"
                }, status=403)
            
            # 1. Find last active (non-cancelled) booking
            # FIXED: Removed 'time_slot' from select_related since it doesn't exist
            last_booking = EnhancedSessionBooking.objects.filter(
                user=user
            ).exclude(
                status="cancelled"
            ).select_related('mentor', 'mentor__user').order_by("-created_at").first()
            
            if not last_booking:
                return Response({
                    "message": "❌ No active sessions found to cancel. All your sessions are already cancelled."
                }, status=404)
            
            # Store session info before cancelling
            mentor_name = last_booking.mentor.get_display_name() if last_booking.mentor else "Mentor"
            mentor_email = last_booking.mentor.user.email if last_booking.mentor else None
            student_name = user.first_name or user.username
            student_email = user.email
            
            # Format session time
# Format session time - CORRECT VERSION
            if isinstance(last_booking.start_time, str):
                from django.utils.dateparse import parse_datetime
                start_time = parse_datetime(last_booking.start_time)
            else:
                start_time = last_booking.start_time

            # ✅ CORRECT: Make timezone-aware first
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=ZoneInfo("UTC"))

            # Convert to UK timezone
            start_time_uk = start_time.astimezone(UK_TZ)
            formatted_time = start_time_uk.strftime('%A, %B %d, %Y at %I:%M %p UK Time')

            print(f"🕐 DEBUG: UTC: {start_time}, UK: {start_time_uk}, Formatted: {formatted_time}")
            
            # 2. Cancel booking in database
            last_booking.status = "cancelled"
            last_booking.save()
            print(f"✅ Booking {last_booking.id} marked as cancelled")
            
            # 3. Free up the associated time slots (using reverse relationship)
            # FIXED: Use time_slots.all() to access related TimeSlot objects
            freed_slots = last_booking.time_slots.all()
            if freed_slots.exists():
                for time_slot in freed_slots:
                    time_slot.is_booked = False
                    time_slot.is_available = True
                    time_slot.booking = None
                    time_slot.save()
                print(f"✅ Freed {freed_slots.count()} time slot(s)")
            else:
                print("ℹ️ No time slots associated with this booking")
            
            # 4. Cancel calendar event if exists
            calendar_cancelled = False
            if last_booking.event_id and mentor_email:
                try:
                    calendar_cancelled = cancel_calendar_event(
                        last_booking.event_id, 
                        mentor_email
                    )
                    if calendar_cancelled:
                        print(f"✅ Calendar event {last_booking.event_id} cancelled")
                    else:
                        print(f"⚠️ Calendar cancellation had issues")
                except Exception as cal_err:
                    print(f"⚠️ Calendar cancellation error: {cal_err}")
            from .calendar_client import send_cancellation_notifications

            # 5. Send cancellation emails
            email_sent = False
            try:
                attendees = [student_email]
                if mentor_email:
                    attendees.append(mentor_email)

                email_sent = send_cancellation_notifications(
                    attendees=attendees,
                    student_name=student_name,
                    mentor_name=mentor_name,
                    formatted_time=formatted_time
                )

                if email_sent:
                    print("✅ Cancellation emails sent successfully")
                else:
                    print("⚠️ Email sending had issues")

            except Exception as email_err:
                print(f"⚠️ Failed to send cancellation emails: {email_err}")
            
            # 6. Build response message
            success_parts = ["✅ Your session has been cancelled"]
            warning_parts = []
            
            if email_sent:
                success_parts.append("confirmation emails have been sent")
            else:
                warning_parts.append("email notifications may have failed")
            
            if calendar_cancelled:
                success_parts.append("calendar event has been removed")
            elif last_booking.event_id:
                warning_parts.append("calendar removal may have had issues")
            
            message = " and ".join(success_parts) + "."
            if warning_parts:
                message += f" Note: {', '.join(warning_parts)}."
            
            return Response({
                "success": True,
                "message": message,
                "cancelled_session": {
                    "mentor_name": mentor_name,
                    "session_time": formatted_time,
                    "booking_id": last_booking.id
                }
            }, status=200)
            
        except UserProfile.DoesNotExist:
            return Response({"error": "User profile not found"}, status=404)
        except Exception as e:
            print(f"❌ Error cancelling session: {e}")
            traceback.print_exc()
            return Response({"error": f"Failed to cancel session: {str(e)}"}, status=500)
    
    def send_cancellation_emails(self, student_email, student_name, mentor_email, mentor_name, formatted_time):
        """Send cancellation emails using calendar_client function"""
        try:
            from .calendar_client import send_cancellation_notifications
            
            # Prepare attendees list
            attendees = [student_email]
            if mentor_email:
                attendees.append(mentor_email)
            
            # Use the working SMTP method
            email_sent = send_cancellation_notifications(
                attendees=attendees,
                student_name=student_name,
                mentor_name=mentor_name,
                formatted_time=formatted_time
            )
            
            return email_sent
            
        except Exception as e:
            print(f"❌ Email sending error: {e}")
            import traceback
            traceback.print_exc()
            return False

class TimeSlotRescheduleView(APIView):
    """Reschedule a booked time slot"""
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            
            # Check if user is premium
            profile = UserProfile.objects.get(user=user)
            if not profile.is_premium:
                return Response({
                    "error": "Only Plus users can manage sessions"
                }, status=403)
            
            # Get action type
            action = request.data.get('action', 'get_slots')
            preferred_day = request.data.get('preferred_day')
            new_slot_id = request.data.get('new_slot_id')
            
            # 1. Find last active booking
            # FIXED: Removed 'time_slot' from select_related
            last_booking = EnhancedSessionBooking.objects.filter(
                user=user
            ).exclude(
                status="cancelled"
            ).select_related('mentor', 'mentor__user').order_by("-created_at").first()
            
            if not last_booking:
                return Response({
                    "message": "❌ No active sessions found to reschedule."
                }, status=404)
            
            mentor = last_booking.mentor
            mentor_name = mentor.get_display_name() if mentor else "Mentor"
            
            # Format current session time
            if isinstance(last_booking.start_time, str):
                from django.utils.dateparse import parse_datetime
                start_time = parse_datetime(last_booking.start_time)
            else:
                start_time = last_booking.start_time
            
            if start_time.tzinfo is None:
                UK_TZ = ZoneInfo("UTC")
                start_time = timezone.make_aware(start_time, UK_TZ)
            
            current_time = start_time.strftime('%A, %B %d, %Y at %I:%M %p UK Time')
            
            # ACTION 1: Get available slots for rescheduling
            if action == 'get_slots':
                # Calculate earliest allowed date (current session date + 1 day minimum)
                earliest_date = start_time.date() + timedelta(days=1)
                end_date = earliest_date + timedelta(days=14)  # Look ahead 2 weeks
                
                # Get available slots
                if preferred_day:
                    slots = self.get_slots_for_day(mentor, preferred_day, earliest_date, end_date)
                else:
                    slots = TimeSlot.objects.filter(
                        mentor=mentor,
                        date__gte=earliest_date,
                        date__lte=end_date,
                        is_available=True,
                        is_booked=False
                    ).order_by('date', 'start_time')[:10]
                
                # Format slots
                slot_list = []
                for slot in slots:
                    slot_list.append({
                        "id": slot.id,
                        "date": slot.date.isoformat(),
                        "start_time": slot.start_time.isoformat(),
                        "end_time": slot.end_time.isoformat(),
                        "formatted_date": slot.date.strftime('%A, %B %d'),
                        "formatted_time": f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
                        "datetime_start": slot.datetime_start.isoformat(),
                        "datetime_end": slot.datetime_end.isoformat(),
                    })
                
                # Get available days for filter
                available_days = self.get_available_days(mentor, earliest_date, end_date)
                
                return Response({
                    "action": "select_new_slot",
                    "current_session": {
                        "mentor_name": mentor_name,
                        "session_time": current_time,
                        "booking_id": last_booking.id
                    },
                    "available_slots": slot_list,
                    "available_days": available_days,
                    "show_day_filter": True,
                    "message": f"Select a new time slot for your session with {mentor_name}:"
                }, status=200)
            
            # ACTION 2: Confirm rescheduling to new slot
            elif action == 'confirm_reschedule':
                if not new_slot_id:
                    return Response({
                        "error": "new_slot_id is required for rescheduling"
                    }, status=400)
                
                # Get new slot
                try:
                    new_slot = TimeSlot.objects.get(id=new_slot_id)
                except TimeSlot.DoesNotExist:
                    return Response({"error": "Selected time slot not found"}, status=404)
                
                # Verify slot is available
                if not new_slot.is_available or new_slot.is_booked:
                    return Response({
                        "error": "This time slot is no longer available"
                    }, status=400)
                
                # Verify slot belongs to same mentor
                if new_slot.mentor.id != mentor.id:
                    return Response({
                        "error": "New slot must be with the same mentor"
                    }, status=400)
                
                # Free up old slots (using reverse relationship)
                old_slots = last_booking.time_slots.all()
                if old_slots.exists():
                    for old_slot in old_slots:
                        old_slot.is_booked = False
                        old_slot.is_available = True
                        old_slot.booking = None
                        old_slot.save()
                    print(f"✅ Freed {old_slots.count()} old slot(s)")
                
                # Cancel old calendar event
                if last_booking.event_id:
                    try:
                        cancel_calendar_event(last_booking.event_id, mentor.user.email)
                        print(f"✅ Old calendar event cancelled")
                    except Exception as e:
                        print(f"⚠️ Calendar cancellation error: {e}")
                
                # Book new slot
                new_slot.is_booked = True
                new_slot.is_available = False
                new_slot.booking = last_booking
                new_slot.save()
                
                # Update booking
                last_booking.start_time = new_slot.datetime_start
                last_booking.end_time = new_slot.datetime_end
                last_booking.status = "confirmed"
                
                # Create new calendar event
                try:
                    from .calendar_client import schedule_specific_slot
                    
                    calendar_result = schedule_specific_slot(
                        mentor_email=mentor.user.email,
                        student_email=user.email,
                        start_time=new_slot.datetime_start,
                        end_time=new_slot.datetime_end,
                        student_name=user.first_name or user.username,
                        mentor_name=mentor_name,
                        session_type="Mentorship Session"
                    )
                    
                    if calendar_result:
                        last_booking.meet_link = calendar_result.get('meet_link', '')
                        last_booking.event_id = calendar_result.get('event_id', '')
                        last_booking.calendar_link = calendar_result.get('calendar_link', '')
                        print(f"✅ New calendar event created")
                    
                except Exception as e:
                    print(f"⚠️ Calendar creation error: {e}")
                
                last_booking.save()
                
                # Format new time
                new_time = new_slot.datetime_start.strftime('%A, %B %d, %Y at %I:%M %p UK Time')
                
                # Send rescheduling emails
                email_sent = self.send_reschedule_emails(
                    student_email=user.email,
                    student_name=user.first_name or user.username,
                    mentor_email=mentor.user.email,
                    mentor_name=mentor_name,
                    old_time=current_time,
                    new_time=new_time,
                    meet_link=last_booking.meet_link
                )
                
                return Response({
                    "success": True,
                    "message": f"✅ Your session has been rescheduled to {new_time}",
                    "rescheduled_session": {
                        "mentor_name": mentor_name,
                        "old_time": current_time,
                        "new_time": new_time,
                        "meet_link": last_booking.meet_link,
                        "calendar_link": last_booking.calendar_link,
                        "booking_id": last_booking.id
                    },
                    "email_sent": email_sent
                }, status=200)
            
            else:
                return Response({
                    "error": "Invalid action. Use 'get_slots' or 'confirm_reschedule'"
                }, status=400)
            
        except UserProfile.DoesNotExist:
            return Response({"error": "User profile not found"}, status=404)
        except Exception as e:
            print(f"❌ Error rescheduling session: {e}")
            traceback.print_exc()
            return Response({"error": f"Failed to reschedule session: {str(e)}"}, status=500)
    
    def get_slots_for_day(self, mentor, day_name, start_date, end_date):
        """Get available slots for a specific day within date range"""
        try:
            days_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2,
                'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
            }
            
            if day_name.lower() not in days_map:
                return []
            
            target_weekday = days_map[day_name.lower()]
            
            # Find all target dates
            target_dates = []
            current_date = start_date
            while current_date <= end_date:
                if current_date.weekday() == target_weekday:
                    target_dates.append(current_date)
                current_date += timedelta(days=1)
            
            # Get slots for target dates
            slots = TimeSlot.objects.filter(
                mentor=mentor,
                date__in=target_dates,
                is_available=True,
                is_booked=False
            ).order_by('date', 'start_time')
            
            return slots
            
        except Exception as e:
            print(f"❌ Error getting slots for day: {e}")
            return []
    
    def get_available_days(self, mentor, start_date, end_date):
        """Get list of days that have available slots"""
        try:
            slots = TimeSlot.objects.filter(
                mentor=mentor,
                date__gte=start_date,
                date__lte=end_date,
                is_available=True,
                is_booked=False
            ).values_list('date', flat=True).distinct()
            
            days = []
            for slot_date in sorted(set(slots)):
                days.append({
                    "day": slot_date.strftime('%A'),
                    "date": slot_date.isoformat(),
                    "formatted": slot_date.strftime('%A, %B %d')
                })
            
            return days
            
        except Exception as e:
            print(f"❌ Error getting available days: {e}")
            return []
    
    def send_reschedule_emails(self, student_email, student_name, mentor_email, 
                               mentor_name, old_time, new_time, meet_link):
        """Send rescheduling confirmation emails"""
        try:
            # Student email
            student_subject = f"📅 Session Rescheduled with {mentor_name}"
            student_text = f"""Hi {student_name},

Your mentorship session has been rescheduled.

Previous Time: {old_time}
New Time: {new_time}

Meet Link: {meet_link}

Thanks,
UK Jobs Mentorship Team"""
            
            student_html = f"""
            <html>
            <body>
            <p>Hi {student_name},</p>
            <p>Your mentorship session with <b>{mentor_name}</b> has been rescheduled.</p>
            <p><b>Previous Time:</b> {old_time}<br>
            <b>New Time:</b> {new_time}</p>
            <p><b>Meet Link:</b> <a href="{meet_link}">{meet_link}</a></p>
            <p>Thanks,<br>UK Jobs Mentorship Team</p>
            </body>
            </html>
            """
            
            # Mentor email
            mentor_subject = f"📅 Session Rescheduled with {student_name}"
            mentor_text = f"""Hi {mentor_name},

Your mentorship session with {student_name} has been rescheduled.

Previous Time: {old_time}
New Time: {new_time}

Meet Link: {meet_link}

Thanks,
UK Jobs Mentorship Team"""
            
            mentor_html = f"""
            <html>
            <body>
            <p>Hi {mentor_name},</p>
            <p>Your mentorship session with <b>{student_name}</b> has been rescheduled.</p>
            <p><b>Previous Time:</b> {old_time}<br>
            <b>New Time:</b> {new_time}</p>
            <p><b>Meet Link:</b> <a href="{meet_link}">{meet_link}</a></p>
            <p>Thanks,<br>UK Jobs Mentorship Team</p>
            </body>
            </html>
            """
            
            # Send emails
            student_email_msg = EmailMultiAlternatives(
                student_subject,
                student_text,
                settings.DEFAULT_FROM_EMAIL,
                [student_email]
            )
            student_email_msg.attach_alternative(student_html, "text/html")
            student_email_msg.send(fail_silently=False)
            
            if mentor_email:
                mentor_email_msg = EmailMultiAlternatives(
                    mentor_subject,
                    mentor_text,
                    settings.DEFAULT_FROM_EMAIL,
                    [mentor_email]
                )
                mentor_email_msg.attach_alternative(mentor_html, "text/html")
                mentor_email_msg.send(fail_silently=False)
            
            return True
            
        except Exception as e:
            print(f"❌ Email sending error: {e}")
            return False
# In views.py, update the TimeSlotBookingView
# views.py
class TimeSlotBookingView(APIView):
    """View to book a time slot with earliest slot detection and confirmation step"""
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            profile = UserProfile.objects.get(user=request.user)
            if not profile.is_premium:
                return Response({"error": "Only Plus users can book sessions"}, status=403)
            
            slot_id = request.data.get('slot_id')
            confirm_booking = request.data.get('confirm_booking', False)
            preferred_day = request.data.get('preferred_day')
            mentor_id = request.data.get('mentor_id')
            
            # Check if first-time user
            first_time_user = is_first_time_user(request.user)
            
            # STEP 1: First-time users automatically get head mentor
            if first_time_user and not slot_id:
                return self.get_earliest_slot(request, profile, mentor_id=None, preferred_day=preferred_day)
            
            # STEP 2: Returning users MUST provide mentor_id
            if not first_time_user and not mentor_id and not slot_id:
                # Return mentor list for selection
                head_mentor = self.get_head_mentor()
                
                # Get all mentors except head mentor
                if head_mentor:
                    mentors = Mentor.objects.filter(is_active=True).exclude(id=head_mentor.id).select_related("user")
                else:
                    mentors = Mentor.objects.filter(is_active=True).select_related("user")
                
                mentor_list = [
                    {
                        "id": m.id,
                        "name": m.get_display_name(),
                        "email": m.user.email,
                        "expertise": m.expertise
                    }
                    for m in mentors
                ]
                
                return Response({
                    "message": "Please select a mentor to view available slots",
                    "action": "select_mentor",
                    "mentors": mentor_list,
                    "is_first_time": False
                }, status=200)
            
            # STEP 3: If no slot_id, get earliest slot for selected mentor
            if not slot_id:
                return self.get_earliest_slot(request, profile, mentor_id, preferred_day)
            
            # STEP 4: If slot_id without confirmation, show confirmation
            if not confirm_booking:
                return self.show_slot_confirmation(request, slot_id)
            
            # STEP 5: Confirm and book
            return self.confirm_booking(slot_id, profile)
            
        except UserProfile.DoesNotExist:
            return Response({"error": "User profile not found"}, status=404)
        except Exception as e:
            print(f"Error in booking view: {e}")
            import traceback
            traceback.print_exc()
            return Response({"error": f"Failed to book time slot: {str(e)}"}, status=500)
    
    def get_head_mentor(self):
        """Get the head mentor from MENTOR_CONFIG"""
        head_config = MENTOR_CONFIG.get("head")
        if not head_config or not head_config.get("email"):
            return None
            
        try:
            return Mentor.objects.get(user__email=head_config["email"], is_active=True)
        except Mentor.DoesNotExist:
            return None
    
    def get_earliest_slot(self, request, profile, mentor_id=None, preferred_day=None):
        """
        Get available slots for the user
        - If no preferred_day: returns earliest slot with confirmation
        - If preferred_day specified: returns ALL slots for that day for manual selection
        """
        try:
            first_time_user = is_first_time_user(request.user)
            
            # Get user's last booking to determine exclusion date
            last_booking = EnhancedSessionBooking.objects.filter(
                user=request.user
            ).exclude(status="cancelled").order_by("-created_at").first()
            
            # Calculate earliest allowed date (minimum 1 day gap from last booking)
            if last_booking:
                last_booking_date = last_booking.start_time
                if isinstance(last_booking_date, str):
                    from django.utils.dateparse import parse_datetime
                    last_booking_date = parse_datetime(last_booking_date)
                
                if last_booking_date.tzinfo is None:
                    last_booking_date = last_booking_date.replace(tzinfo=UK_TZ)
                
                exclusion_date = last_booking_date.date()
                
                earliest_allowed = calculate_earliest_next_session(
                    request.user.email,
                    mentor_id if mentor_id else "any"
                )
                min_start_date = max(
                    exclusion_date + timedelta(days=1),
                    earliest_allowed.date()
                )
            else:
                min_start_date = (timezone.now() + timedelta(days=1)).date()
            
            # CASE 1: First-time users -> Always use head mentor
            if first_time_user:
                head_mentor = self.get_head_mentor()
                if not head_mentor:
                    return Response({"error": "Head mentor not found"}, status=404)
                
                mentor = head_mentor
                head_name = head_mentor.get_display_name()
                
            # CASE 2: Returning users
            else:
                if mentor_id:
                    try:
                        mentor = Mentor.objects.get(id=mentor_id, is_active=True)
                    except Mentor.DoesNotExist:
                        return Response({"error": "Mentor not found"}, status=404)
                else:
                    # Get random mentor excluding head mentor
                    head_mentor = self.get_head_mentor()
                    all_mentors = Mentor.objects.filter(is_active=True)
                    if head_mentor:
                        all_mentors = all_mentors.exclude(id=head_mentor.id)
                    
                    if not all_mentors.exists():
                        all_mentors = Mentor.objects.filter(is_active=True)
                    
                    mentor = random.choice(list(all_mentors))
            
            mentor_name = mentor.get_display_name()
            end_date = min_start_date + timedelta(days=14)
            
            # ============================================================
            # SCENARIO A: User selected a specific day from day filter
            # Return ALL available slots for that day (no auto-selection)
            # ============================================================
            if preferred_day:
                print(f"User selected specific day: {preferred_day}")
                
                # Get ALL slots for the selected day
                available_slots = self.get_slots_for_specific_day(
                    mentor, preferred_day, min_start_date, end_date
                )
                
                if not available_slots:
                    return Response({
                        "error": f"No slots available for {preferred_day.title()}",
                        "show_day_filter": True,
                        "available_days": self.get_available_days(
                            mentor, min_start_date, end_date
                        ),
                        "mentor": {
                            "id": mentor.id,
                            "name": mentor_name,
                            "email": mentor.user.email,
                            "expertise": mentor.expertise
                        },
                        "domain": getattr(request, 'domain', None)
                    }, status=200)
                
                # Format ALL slots for the selected day
                slot_list = []
                for slot in available_slots:
                    slot_list.append({
                        "id": slot.id,
                        "date": slot.date.isoformat(),
                        "start_time": slot.start_time.isoformat(),
                        "end_time": slot.end_time.isoformat(),
                        "formatted_date": slot.date.strftime('%A, %B %d'),
                        "formatted_time": f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
                        "datetime_start": slot.datetime_start.isoformat(),
                        "datetime_end": slot.datetime_end.isoformat(),
                    })
                
                print(f"Returning {len(slot_list)} slots for {preferred_day}")
                
                # Return ALL slots for user to manually select
                return Response({
                    "message": f"Available slots for {preferred_day.title()}:",
                    "available_slots": slot_list,  # Multiple slots
                    "show_slot_selector": True,  # Flag to show slot selector UI
                    "mentor": {
                        "id": mentor.id,
                        "name": mentor_name,
                        "email": mentor.user.email,
                        "expertise": mentor.expertise
                    },
                    "selected_day": preferred_day.title(),
                    "domain": getattr(request, 'domain', None),
                    "is_first_time": first_time_user,
                    "min_booking_date": min_start_date.isoformat(),
                    "selected_mentor_id": mentor.id
                }, status=200)
            
            # ============================================================
            # SCENARIO B: Initial request (no day selected yet)
            # Return earliest slot with yes/no confirmation
            # ============================================================
            else:
                print(f"Getting earliest slot for {mentor_name}")
                
                # Get next 5 available slots
                available_slots = TimeSlot.objects.filter(
                    mentor=mentor,
                    date__gte=min_start_date,
                    date__lte=end_date,
                    is_available=True,
                    is_booked=False
                ).order_by('date', 'start_time')[:5]
                
                if not available_slots:
                    return Response({
                        "error": f"No slots available starting from {min_start_date.strftime('%B %d')}",
                        "show_day_filter": True,
                        "available_days": self.get_available_days(
                            mentor, min_start_date, end_date
                        ),
                        "mentor": {
                            "id": mentor.id,
                            "name": mentor_name,
                            "email": mentor.user.email,
                            "expertise": mentor.expertise
                        }
                    }, status=200)
                
                # Get the earliest slot
                earliest_slot = available_slots[0]
                
                slot_details = {
                    "id": earliest_slot.id,
                    "date": earliest_slot.date.isoformat(),
                    "start_time": earliest_slot.start_time.isoformat(),
                    "end_time": earliest_slot.end_time.isoformat(),
                    "formatted_date": earliest_slot.date.strftime('%A, %B %d'),
                    "formatted_time": f"{earliest_slot.start_time.strftime('%I:%M %p')} - {earliest_slot.end_time.strftime('%I:%M %p')}",
                    "datetime_start": earliest_slot.datetime_start.isoformat(),
                    "datetime_end": earliest_slot.datetime_end.isoformat(),
                }
                
                print(f"Returning earliest slot: {earliest_slot.date} at {earliest_slot.start_time}")
                
                # Return earliest slot with yes/no confirmation
                return Response({
                    "message": f"{'Welcome! ' if first_time_user else ''}Your earliest available slot with {mentor_name} is:",
                    "earliest_slot": slot_details,
                    "mentor": {
                        "id": mentor.id,
                        "name": mentor_name,
                        "email": mentor.user.email,
                        "expertise": mentor.expertise
                    },
                    "requires_confirmation": True,  # Show yes/no buttons
                    "show_day_filter": True,  # Show day filter for "no" option
                    "available_days": self.get_available_days(
                        mentor, min_start_date, end_date,
                        exclude_date=earliest_slot.date  # Exclude shown slot's date
                    ),
                    "is_first_time": first_time_user,
                    "min_booking_date": min_start_date.isoformat(),
                    "selected_mentor_id": mentor.id
                }, status=200)
                
        except Exception as e:
            print(f"Error getting slots: {e}")
            import traceback
            traceback.print_exc()
            return Response({"error": "Failed to get slots"}, status=500)
    
    def show_slot_confirmation(self, request, slot_id):
        """Show confirmation for a specific slot"""
        try:
            slot = TimeSlot.objects.get(id=slot_id)
            mentor = slot.mentor
            
            # Check if slot is still available
            if not slot.is_available or slot.is_booked:
                return Response({"error": "This slot is no longer available"}, status=400)
            
            slot_details = {
                "id": slot.id,
                "date": slot.date.isoformat(),
                "start_time": slot.start_time.isoformat(),
                "end_time": slot.end_time.isoformat(),
                "formatted_date": slot.date.strftime('%A, %B %d'),
                "formatted_time": f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
                "datetime_start": slot.datetime_start.isoformat(),
                "datetime_end": slot.datetime_end.isoformat(),
            }
            
            return Response({
                "message": f"Are you comfortable with this slot with {mentor.get_display_name()}?",
                "slot": slot_details,
                "mentor": {
                    "id": mentor.id,
                    "name": mentor.get_display_name(),
                    "email": mentor.user.email,
                    "expertise": mentor.expertise
                },
                "requires_confirmation": True,
                "confirmation_options": ["Yes, book this slot", "No, show me other days"],
                "show_day_filter": True,
                "available_days": self.get_available_days(mentor),
                "selected_slot_id": slot_id
            }, status=200)
            
        except TimeSlot.DoesNotExist:
            return Response({"error": "Time slot not found"}, status=404)
        except Exception as e:
            print(f"❌ Error showing slot confirmation: {e}")
            return Response({"error": "Failed to show slot confirmation"}, status=500)
    
 # Replace the email sending section in your ScheduleView.confirm_booking() method with this:

    def confirm_booking(self, slot_id, profile):
        """Confirm and book the slot with mentor validation"""
        try:
            slot = TimeSlot.objects.get(id=slot_id)
            mentor = slot.mentor

            if not slot.is_available or slot.is_booked:
                return Response({"error": "Time slot already taken"}, status=400)

            # ✅ CRITICAL: Validate mentor assignment based on user history
            first_time_user = is_first_time_user(profile.user)
            head_mentor = self.get_head_mentor()
            
            if head_mentor:
                is_head_slot = (mentor.id == head_mentor.id)
                
                # First-time users MUST book with head mentor
                if first_time_user and not is_head_slot:
                    return Response({
                        "error": "As a first-time user, your first session must be with the head mentor.",
                        "action": "redirect_to_head_mentor",
                        "head_mentor_id": head_mentor.id
                    }, status=400)
                
                # Returning users CANNOT book with head mentor
                if not first_time_user and is_head_slot:
                    return Response({
                        "error": "You've already completed your introductory session. Please select a specialist mentor.",
                        "action": "show_regular_mentors"
                    }, status=400)

            # Book the slot
            booking = book_time_slot(slot.id, profile, mentor)

            # Send confirmation emails
            try:
                from django.core.mail import EmailMultiAlternatives
                
                subject = f"Session Confirmed with {mentor.get_display_name()}"
                from_email = settings.DEFAULT_FROM_EMAIL
                to_emails = [profile.user.email, mentor.user.email]

                text_body = (
                    f"Hi {profile.user.first_name or profile.user.username},\n\n"
                    f"Your session with {mentor.get_display_name()} is confirmed.\n\n"
                    f"Date: {booking.start_time.strftime('%A, %B %d, %Y')}\n"
                    f"Time: {booking.start_time.strftime('%I:%M %p')} UK Time\n"
                    f"Meet Link: {booking.meet_link}\n\n"
                    f"Best,\nTeam"
                )

                html_body = f"""
                <html>
                <body>
                <p>Hi {profile.user.first_name or profile.user.username},</p>
                <p>Your session with <b>{mentor.get_display_name()}</b> is confirmed.</p>
                <p>
                    <b>Date:</b> {booking.start_time.strftime('%A, %B %d, %Y')}<br>
                    <b>Time:</b> {booking.start_time.strftime('%I:%M %p')} UK Time<br>
                    <b>Meet Link:</b> <a href="{booking.meet_link}">{booking.meet_link}</a>
                </p>
                <p>Best,<br>Team</p>
                </body>
                </html>
                """

                email = EmailMultiAlternatives(subject, text_body, from_email, to_emails)
                email.attach_alternative(html_body, "text/html")
                email.send(fail_silently=False)

            except Exception as e:
                print(f"Email sending failed: {e}")

            # Return success response
            return Response({
                "success": True,
                "message": f"Your session with {mentor.get_display_name()} is confirmed for "
                        f"{booking.start_time.strftime('%A, %B %d at %I:%M %p')} UK time!",
                "booking": {
                    "id": booking.id,
                    "start_time": booking.start_time.isoformat(),
                    "end_time": booking.end_time.isoformat(),
                    "formatted_time": booking.start_time.strftime('%A, %B %d at %I:%M %p'),
                    "meet_link": booking.meet_link,
                    "calendar_link": booking.calendar_link,
                    "status": booking.status,
                    "mentor": {
                        "id": mentor.id,
                        "name": mentor.get_display_name(),
                        "email": mentor.user.email,
                        "expertise": mentor.expertise,
                    }
                }
            })

        except TimeSlot.DoesNotExist:
            return Response({"error": "Time slot not found"}, status=404)
        except ValidationError as e:
            return Response({"error": str(e)}, status=400)
        except Exception as e:
            print(f"Error in confirm_booking: {e}")
            traceback.print_exc()
            return Response({"error": f"Booking failed: {str(e)}"}, status=500)
    
    def get_available_days(self, mentor, start_date=None, end_date=None, exclude_date=None):
        """
        Get list of days that have available slots
        Optionally exclude a specific date (e.g., the date of the shown earliest slot)
        """
        try:
            if not start_date:
                start_date = timezone.now().date()
            
            if not end_date:
                end_date = start_date + timedelta(days=14)
            
            # Get all unique dates with available slots
            slots = TimeSlot.objects.filter(
                mentor=mentor,
                date__gte=start_date,
                date__lte=end_date,
                is_available=True,
                is_booked=False
            ).values_list('date', flat=True).distinct()
            
            # Format days for response
            days = []
            for slot_date in sorted(set(slots)):
                # Exclude the date if specified (e.g., date of earliest slot already shown)
                if exclude_date and slot_date == exclude_date:
                    continue
                
                days.append({
                    "day": slot_date.strftime('%A'),
                    "date": slot_date.isoformat(),
                    "formatted": slot_date.strftime('%A, %B %d')
                })
            
            print(f"Found {len(days)} available days for {mentor.get_display_name()}")
            
            return days
            
        except Exception as e:
            print(f"Error getting available days: {e}")
            return []

    
    def get_slots_for_specific_day(self, mentor, day_name, start_date=None, end_date=None):
        """
        Get ALL available slots for a specific day name (e.g., 'monday')
        Returns all unbooked slots, not just the earliest
        """
        try:
            if not start_date:
                start_date = (timezone.now() + timedelta(days=1)).date()
            if not end_date:
                end_date = start_date + timedelta(days=14)
            
            # Map day names to weekday numbers
            days_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2,
                'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
            }
            
            if day_name.lower() not in days_map:
                print(f"Invalid day name: {day_name}")
                return []
            
            target_weekday = days_map[day_name.lower()]
            
            # Find all dates that match the target weekday within range
            target_dates = []
            current_date = start_date
            while current_date <= end_date:
                if current_date.weekday() == target_weekday:
                    target_dates.append(current_date)
                current_date += timedelta(days=1)
            
            print(f"Found {len(target_dates)} {day_name} dates between {start_date} and {end_date}")
            
            # Get ALL slots for target dates (no limit)
            slots = TimeSlot.objects.filter(
                mentor=mentor,
                date__in=target_dates,
                is_available=True,
                is_booked=False
            ).order_by('date', 'start_time')  # No [:1] limit - return all
            
            print(f"Found {slots.count()} available slots for {day_name}")
            
            return list(slots)
            
        except Exception as e:
            print(f"Error getting slots for day {day_name}: {e}")
            import traceback
            traceback.print_exc()
            return []

    
    def get_available_slots_for_mentor(self, mentor, count=5):
        """Get next N available slots for mentor"""
        try:
            start_date = timezone.now().date()
            end_date = start_date + timedelta(days=14)
            
            slots = TimeSlot.objects.filter(
                mentor=mentor,
                date__gte=start_date,
                date__lte=end_date,
                is_available=True,
                is_booked=False
            ).order_by('date', 'start_time')[:count]
            
            return list(slots)
            
        except Exception as e:
            print(f"❌ Error getting available slots: {e}")
            return []
    
    # Add this new method to your view classes (TimeSlotBookingView or ScheduleView)
    def get_all_slots_for_day(self, mentor, day_name, start_date=None, end_date=None):
        """Get ALL available slots for a specific day (not just earliest)"""
        try:
            if not start_date:
                start_date = (timezone.now() + timedelta(days=1)).date()
            if not end_date:
                end_date = start_date + timedelta(days=14)
            
            days_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2,
                'thursday': 3, 'friday': 4, 'saturday': 5, 'sunday': 6
            }
            
            if day_name.lower() not in days_map:
                return []
            
            target_weekday = days_map[day_name.lower()]
            
            # Find all target dates
            target_dates = []
            current_date = start_date
            while current_date <= end_date:
                if current_date.weekday() == target_weekday:
                    target_dates.append(current_date)
                current_date += timedelta(days=1)
            
            # Get ALL slots for target dates (not limited to 1)
            slots = TimeSlot.objects.filter(
                mentor=mentor,
                date__in=target_dates,
                is_available=True,
                is_booked=False
            ).order_by('date', 'start_time')  # Remove [:1] limit
            
            return list(slots)
            
        except Exception as e:
            print(f"❌ Error getting all slots for day: {e}")
            return []

    # Update the handleDaySelection in your view
    def handle_day_selection_with_all_slots(self, request, selected_day, mentor_id, domain=None):
        """Modified to return ALL slots instead of just earliest"""
        try:
            # Get mentor
            if mentor_id == "head":
                mentor = self.get_head_mentor()
            else:
                mentor = Mentor.objects.get(id=mentor_id, is_active=True)
            
            # Get ALL available slots for the selected day
            available_slots = self.get_all_slots_for_day(mentor, selected_day)
            
            if not available_slots:
                return Response({
                    "error": f"No slots available for {selected_day}",
                    "show_day_filter": True,
                    "available_days": self.get_available_days(mentor),
                    "domain": domain
                }, status=200)
            
            # Format all slots for display
            slot_list = []
            for slot in available_slots:
                slot_list.append({
                    "id": slot.id,
                    "date": slot.date.isoformat(),
                    "start_time": slot.start_time.isoformat(),
                    "end_time": slot.end_time.isoformat(),
                    "formatted_date": slot.date.strftime('%A, %B %d'),
                    "formatted_time": f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
                    "datetime_start": slot.datetime_start.isoformat(),
                    "datetime_end": slot.datetime_end.isoformat(),
                })
            
            return Response({
                "message": f"Available slots for {selected_day}:",
                "available_slots": slot_list,  # Return ALL slots
                "show_slot_selector": True,  # New flag for frontend
                "domain": domain,
                "mentor": {
                    "id": mentor.id,
                    "name": mentor.get_display_name(),
                    "email": mentor.user.email,
                    "expertise": mentor.expertise
                },
                "selected_day": selected_day
            }, status=200)
            
        except Exception as e:
            print(f"❌ Error in day selection: {e}")
            return Response({"error": str(e)}, status=500)
        
class ScheduleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    # In ScheduleView.post() method, update the head mentor handling:

    def post(self, request):
        try:
            print("📌 [DEBUG] ScheduleView POST called")
            self.request = request  # Store request for use in helper methods
            
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
                return Response({"error": "Only Plus users can book sessions."}, status=403)

            # PRIORITY 1: HEAD mentor case (ONLY for first-time users OR explicit head request)
            if mentor_id == "head" or (is_first_time_user(request.user) and mentor_id is None):
                # Get head mentor configuration with error handling
                head_config = None
                try:
                    head_config = MENTOR_CONFIG.get("head")
                    if not head_config or not head_config.get("email"):
                        print("⚠️ Head mentor configuration not found or incomplete")
                        head_config = None
                except Exception as e:
                    print(f"❌ Error accessing head mentor configuration: {e}")
                    head_config = None
                
                # Try to get head mentor if config exists
                head_mentor = None
                head_name = "Head Mentor"
                if head_config:
                    head_email = head_config["email"]
                    head_name = head_config.get("name", "Head Mentor")
                    print(f"🎯 [HEAD] Using head mentor: {head_email}")
                    
                    try:
                        head_mentor = Mentor.objects.get(user__email=head_email, is_active=True)
                    except Mentor.DoesNotExist:
                        print(f"⚠️ Head mentor with email {head_email} not found or not active")
                
                # If head mentor not found, fall back to any active mentor
                if not head_mentor:
                    try:
                        head_mentor = Mentor.objects.filter(is_active=True).first()
                        if not head_mentor:
                            return Response({"error": "No active mentors found"}, status=404)
                        head_name = head_mentor.user.username
                        print(f"🎯 [FALLBACK] Using fallback mentor: {head_mentor.user.email}")
                    except Exception as e:
                        print(f"❌ Error finding fallback mentor: {e}")
                        return Response({"error": "No mentors available"}, status=404)

                # Get available time slots for head mentor
                if preferred_day:
                    available_slots = self.get_slots_for_specific_day(head_mentor, preferred_day)
                else:
                    available_slots = self.get_available_slots_for_mentor(head_mentor, count=5)

                if not available_slots:
                    return Response({
                        "error": "No available slots found with head mentor",
                        "show_day_filter": True,
                        "available_days": self.get_available_days(head_mentor),
                        "mentor_name": head_name
                    }, status=200)

                earliest_slot = available_slots[0]

                # If user provided selected_slot, book it
                if selected_slot:
                    return self.confirm_booking(
                        request.user,
                        head_mentor,
                        selected_slot,
                        profile
                    )

                # Otherwise, return earliest slot for confirmation
                return Response({
                    "message": f"Welcome! As a first-time user, your session will be with {head_name}. Your earliest available slot is:",
                    "earliest_slot": earliest_slot,
                    "mentor_name": head_name,
                    "requires_confirmation": True,
                    "show_day_filter": True,
                    "available_days": self.get_available_days(head_mentor),
                    "selected_mentor_id": "head",
                    "is_first_time": True
                }, status=200)

            # PRIORITY 2: Specific mentor by ID (This should take precedence over domain)
            if mentor_id and mentor_id != "head":
                try:
                    selected_mentor = Mentor.objects.get(id=mentor_id, is_active=True)
                    mentor_name = selected_mentor.user.username
                    print(f"🎯 Specific mentor selected: {mentor_name}")
                    
                    # Get available time slots for the mentor
                    if preferred_day:
                        available_slots = self.get_slots_for_specific_day(selected_mentor, preferred_day)
                    else:
                        available_slots = self.get_available_slots_for_mentor(selected_mentor, count=5)

                    if not available_slots:
                        return Response({
                            "error": f"No available slots found for {mentor_name}",
                            "show_day_filter": True,
                            "available_days": self.get_available_days(selected_mentor),
                            "mentor_name": mentor_name
                        }, status=200)

                    earliest_slot = available_slots[0]

                    # If user provided selected_slot, book it
                    if selected_slot:
                        return self.confirm_booking(
                            request.user,
                            selected_mentor,
                            selected_slot,
                            profile
                        )

                    return Response({
                        "message": f"Your earliest available slot with {mentor_name} is:",
                        "earliest_slot": earliest_slot,
                        "mentor_name": mentor_name,
                        "requires_confirmation": True,
                        "show_day_filter": True,
                        "available_days": self.get_available_days(selected_mentor),
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
                    print(f"⚠️ No valid mentor for {domain}, falling back to any active mentor")
                    
                    # Get head mentor first to exclude it from random selection
                    head_mentor = None
                    try:
                        head_config = MENTOR_CONFIG.get("head")
                        if head_config and head_config.get("email"):
                            head_email = head_config["email"]
                            try:
                                head_mentor = Mentor.objects.get(user__email=head_email, is_active=True)
                            except Mentor.DoesNotExist:
                                pass  # Head mentor not found, continue with any mentor
                    except Exception as e:
                        print(f"❌ Error accessing head mentor configuration: {e}")
                    
                    # Get a random mentor that is not the head mentor
                    try:
                        if head_mentor:
                            # Exclude head mentor from the random selection
                            all_mentors = Mentor.objects.filter(is_active=True).exclude(id=head_mentor.id).select_related('user')
                        else:
                            # If head mentor not found, just get any active mentor
                            all_mentors = Mentor.objects.filter(is_active=True).select_related('user')
                        
                        if not all_mentors.exists():
                            return Response({"error": "No active mentors found"}, status=404)
                        
                        selected_mentor = random.choice(list(all_mentors))
                        print(f"🎯 [RANDOM] Selected random mentor: {selected_mentor.user.email}")
                    except Exception as e:
                        print(f"❌ Error finding random mentor: {e}")
                        return Response({"error": "No mentors available"}, status=404)
                else:
                    mentor_name = selected_mentor.user.username

                print(f"🎯 Domain mentor selected: {selected_mentor.user.username}")

                if preferred_day:
                    available_slots = self.get_slots_for_specific_day(selected_mentor, preferred_day)
                else:
                    available_slots = self.get_available_slots_for_mentor(selected_mentor, count=5)

                if not available_slots:
                    return Response({
                        "error": "No available slots found for this day",
                        "show_day_filter": True,
                        "available_days": self.get_available_days(selected_mentor),
                        "domain": domain.title()
                    }, status=200)

                earliest_slot = available_slots[0]

                if selected_slot:
                    return self.confirm_booking(
                        request.user,
                        selected_mentor,
                        selected_slot,
                        profile
                    )

                return Response({
                    "message": f"Your earliest available slot for {domain.title()} mentorship is:",
                    "earliest_slot": earliest_slot,
                    "domain": domain.title(),
                    "domain_description": self.get_domain_description(domain),
                    "requires_confirmation": True,
                    "show_day_filter": True,
                    "available_days": self.get_available_days(selected_mentor),
                    "selected_mentor_id": selected_mentor.id
                }, status=200)

            # ERROR: If no valid parameters provided
            return Response({
                "error": "Invalid request. Please specify mentor_id or provide domain for domain-based booking."
            }, status=400)

        except Exception as e:
            print(f"❌ [SCHEDULE] Unexpected error: {e}")
            traceback.print_exc()
            return Response({"error": f"Scheduling error: {str(e)}"}, status=500)

class AvailableSlotsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return next 5 available 15-minute slots"""
        try:
            # Check if user is premium
            profile = UserProfile.objects.get(user=request.user)
            if not profile.is_premium:
                return Response({"error": "Only Plus users can view available slots"}, status=403)
            
            mentor_id = request.GET.get('mentor_id')
            
            # Get mentor
            if mentor_id:
                try:
                    mentor = Mentor.objects.get(id=mentor_id, is_active=True)
                except Mentor.DoesNotExist:
                    return Response({"error": "Mentor not found"}, status=404)
            else:
                # Default to head mentor
                head_email = MENTOR_CONFIG.get("head", {}).get("email")
                if not head_email:
                    return Response({"error": "Head mentor configuration not found"}, status=500)
                
                try:
                    mentor = Mentor.objects.get(user__email=head_email, is_active=True)
                except Mentor.DoesNotExist:
                    return Response({"error": "Head mentor not found"}, status=404)
            
            # Calculate earliest allowed session based on 7-day gap rule
            earliest_allowed = calculate_earliest_next_session(
                request.user.email, 
                mentor.user.email
            )
            
            # Get slots starting from earliest allowed date
            start_date = earliest_allowed.date()
            end_date = start_date + timedelta(days=7)
            
            slots = TimeSlot.objects.filter(
                mentor=mentor,
                date__gte=start_date,
                date__lte=end_date,
                is_available=True,
                is_booked=False
            ).order_by('date', 'start_time')
            
            # Format slots for response
            slot_list = []
            for slot in slots:
                if len(slot_list) >= 5:
                    break
                    
                slot_list.append({
                    "id": slot.id,
                    "date": slot.date.isoformat(),
                    "start_time": slot.start_time.isoformat(),
                    "end_time": slot.end_time.isoformat(),
                    "formatted_date": slot.date.strftime('%A, %B %d'),
                    "formatted_time": f"{slot.start_time.strftime('%I:%M %p')} - {slot.end_time.strftime('%I:%M %p')}",
                    "datetime_start": slot.datetime_start.isoformat(),
                    "datetime_end": slot.datetime_end.isoformat(),
                })
            
            return Response({
                "available_slots": slot_list,
                "message": f"Found {len(slot_list)} available 15-minute slots",
                "mentor": {
                    "id": mentor.id,
                    "name": mentor.user.username,
                    "email": mentor.user.email,
                    "expertise": mentor.expertise
                }
            }, status=200)
            
        except UserProfile.DoesNotExist:
            return Response({"error": "User profile not found"}, status=404)
        except Exception as e:
            print(f"Error getting available slots: {e}")
            return Response({
                "error": "Could not fetch available slots"
            }, status=500)
import re
def clean_chat_output(text: str) -> str:
    """
    Sanitize AI reply:
    - Remove <u> tags
    - Allow <a href=""> tags (for blue clickable links)
    - Remove any other unwanted HTML tags
    """
    if not text:
        return text

    # Remove underline tags
    text = re.sub(r"</?u>", "", text, flags=re.IGNORECASE)

    # Keep only <a> tags and their href attribute, remove all others
    text = re.sub(r"<(?!/?a(?=>|\s.*>))[^>]+>", "", text)

    # Ensure anchor tags have inline style for blue color (so link looks professional)
    text = re.sub(
        r'<a\s+([^>]*?)href="([^"]+)"([^>]*)>',
        r'<a href="\2" style="color:#1a73e8; text-decoration:none;" target="_blank">',
        text
    )

    return text.strip()

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

            # PRIORITY 1: Check for cancellation requests FIRST (before booking check)
            if is_cancel_request(message):
                if not is_premium:
                    return Response({
                        "reply": "⚠️ Only Plus users can manage sessions. Please upgrade to Plus.",
                        "mentors": None
                    }, status=200)
                
                # Get last ACTIVE (non-cancelled) session (check both models)
                last_session = None
                
                # Check EnhancedSessionBooking first
                last_new_session = (
                    EnhancedSessionBooking.objects.filter(user=request.user)
                    .exclude(status="cancelled")
                    .order_by("-created_at")
                    .first()
                )
                
                if last_new_session:
                    last_session = last_new_session
                else:
                    # Fall back to old SessionBooking
                    last_session = (
                        SessionBooking.objects.filter(user=request.user)
                        .exclude(status="cancelled")
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
                from zoneinfo import ZoneInfo
                UK_TZ = ZoneInfo("Europe/London")
                if session_start.tzinfo is None:
                    session_start = timezone.make_aware(session_start, UK_TZ)

                session_time_ist = session_start.astimezone(UK_TZ).strftime('%d %b %Y, %I:%M %p')
                mentor_name = last_session.mentor.user.username if last_session.mentor else "Mentor"

                return Response({
                    "reply": f"📅 I found your active session with {mentor_name} scheduled for {session_time_ist}.\n\nAre you sure you want to cancel this session?",
                    "session_actions": True,
                    "session_details": {
                        "mentor_name": mentor_name,
                        "session_time": session_time_ist,
                        "session_id": last_session.id
                    }
                }, status=200)

            # PRIORITY 2: Check for meeting/booking requests (MUST COME BEFORE AI CHAT)
            if is_meeting_request(message):
                if not is_premium:
                    return Response({
                        "reply": "⚠️ Only Plus users can book mentorship sessions. Please upgrade to premium.",
                        "mentors": None
                    }, status=200)
                
                # Detect domain from message
                detected_domain = detect_domain_from_message(message)
                
                # ALL USERS get regular mentor selection (head mentor logic commented out)
                
                # If domain detected, auto-select mentor
                if detected_domain != 'general':
                    selected_mentor = get_random_mentor_by_domain(detected_domain)
                    
                    if selected_mentor:
                        return Response({
                            "reply": f"I detected you're interested in {detected_domain.title()} domain. I've selected {selected_mentor.user.username} as your mentor specialist for this area.",
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
                
                # Fallback: show all mentors except head mentor for ALL users
                try:
                    # Get head mentor to exclude from list
                    head_mentor = None
                    try:
                        head_config = MENTOR_CONFIG.get("head")
                        if head_config and head_config.get("email"):
                            head_email = head_config["email"]
                            try:
                                head_mentor = Mentor.objects.get(user__email=head_email, is_active=True)
                            except Mentor.DoesNotExist:
                                pass  # Head mentor not found, continue with all mentors
                    except Exception as e:
                        print(f"❌ Error accessing head mentor configuration: {e}")
                    
                    # Get all active mentors except head mentor
                    if head_mentor:
                        mentors = Mentor.objects.filter(is_active=True).exclude(id=head_mentor.id).select_related("user")
                    else:
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
                    
                    if not mentor_list:
                        return Response({
                            "reply": "⚠️ No mentors available at the moment. Please try again later.",
                            "mentors": None
                        }, status=200)
                    
                    return Response({
                        "reply": "I can help you schedule a mentorship session. Please select a mentor:",
                        "mentors": mentor_list,
                        "is_first_time": False,
                        "detected_domain": detected_domain
                    }, status=200)
                    
                except Exception as e:
                    print(f"❌ Error getting mentors: {e}")
                    return Response({
                        "reply": "⚠️ No mentors available at the moment. Please try again later.",
                        "mentors": None
                    }, status=200)

            # PRIORITY 3: Default AI chat for other messages (only reached if not booking/cancel)
            reply = ask_gemini(message, is_premium)
            reply = clean_chat_output(reply)

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
            return Response({"error": "Only Plus users can access mentors"}, status=403)
        
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

# Import the calculate_earliest_next_session function from calendar_client
from .calendar_client import calculate_earliest_next_session