import traceback
import random
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
    send_enhanced_manual_invitations
)

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
        previous_bookings = SessionBooking.objects.filter(
            user=user, 
            status='confirmed'
        ).count()
        
        return previous_bookings == 0
    except:
        return True  # Assume first time if error

def is_email_premium(email):
    """Check if given email exists in premium_users.csv"""
    csv_path = os.path.join(settings.BASE_DIR, "premium_users.csv")
    try:
        with open(csv_path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row["email"].strip().lower() == email.strip().lower():
                    return True
    except Exception as e:
        print(f"Error reading premium_users.csv: {e}")
    return False

def is_email_allowed(email: str) -> bool:
    """
    Google Sheets ya CSV ke andar allowed emails check karega.
    Abhi example CSV ke liye likha hai.
    """
    filepath = os.path.join(BASE_DIR, "registeredemail.csv")
    try:
        with open(filepath, newline='') as csvfile:
            reader = csv.reader(csvfile)
            allowed = [row[0].strip().lower() for row in reader]
            return email.lower() in allowed
    except Exception as e:
        print("CSV read error:", e)
        return False

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

            # ✅ Allowed email check
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

            token, _ = Token.objects.get_or_create(user=user)

            return Response({
                "message": "User created successfully",
                "token": token.key,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
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

        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            "message": "Login successful",
            "token": token.key,
            "user": {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "is_premium": getattr(user, "userprofile", None).is_premium if hasattr(user, "userprofile") else False
            }
        }, status=200)

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
            profile = UserProfile.objects.get(user=request.user)
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

class ScheduleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

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

            if not profile.is_premium:
                return Response({"error": "Only premium users can book sessions."}, status=403)

            # Handle head mentor booking
            if mentor_id == "head":
                head_email = "sunilramtri000@gmail.com"
                
                # Get available slots with day filter if provided
                if preferred_day:
                    available_slots = self.get_slots_for_specific_day(head_email, preferred_day)
                else:
                    available_slots = get_next_available_slots_for_user(head_email, count=1)

                if not available_slots:
                    return Response({
                        "error": "No available slots found",
                        "show_day_filter": True,
                        "available_days": self.get_available_days(head_email)
                    }, status=200)

                earliest_slot = available_slots[0]
                
                # If user already confirmed a slot, book it
                if selected_slot:
                    return self.confirm_booking(
                        request.user, 
                        head_email, 
                        "Sunil (Head Mentor)",
                        selected_slot,
                        profile
                    )

                # Show earliest slot with yes/no confirmation
                return Response({
                    "message": f"Your earliest available slot with Head Mentor is:",
                    "earliest_slot": {
                        "start_time": earliest_slot["start_time"].isoformat(),
                        "end_time": earliest_slot["end_time"].isoformat(),
                        "formatted_date": earliest_slot["formatted_date"],
                        "formatted_time": earliest_slot["formatted_time"]
                    },
                    "mentor_name": "Sunil (Head Mentor)",
                    "requires_confirmation": True,
                    "show_day_filter": True,
                    "available_days": self.get_available_days(head_email) if not preferred_day else None
                }, status=200)

            # Handle domain-based mentor selection
            if not domain:
                return Response({"error": "domain is required"}, status=400)

            selected_mentor = get_random_mentor_by_domain(domain)
            if not selected_mentor:
                return Response({
                    "error": f"No mentors available for {domain} domain",
                    "available_domains": list(DOMAIN_KEYWORDS.keys())
                }, status=404)

            print(f"🎯 [DOMAIN-BASED] Selected mentor for {domain} domain")

            # Get available slots with day filter if provided
            if preferred_day:
                available_slots = self.get_slots_for_specific_day(selected_mentor.user.email, preferred_day)
            else:
                available_slots = get_next_available_slots_for_user(selected_mentor.user.email, count=1)

            if not available_slots:
                return Response({
                    "error": "No available slots found for this day",
                    "show_day_filter": True,
                    "available_days": self.get_available_days(selected_mentor.user.email),
                    "domain": domain.title()
                }, status=200)

            earliest_slot = available_slots[0]
            
            # If user already confirmed a slot, book it
            if selected_slot:
                return self.confirm_booking(
                    request.user, 
                    selected_mentor.user.email, 
                    f"{domain.title()} Expert",
                    selected_slot,
                    profile,
                    selected_mentor
                )

            # Show earliest slot with yes/no confirmation
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
                "available_days": self.get_available_days(selected_mentor.user.email),
                "selected_mentor_id": selected_mentor.id
            }, status=200)

        except Exception as e:
            traceback.print_exc()
            return Response({"error": str(e)}, status=500)

    def get_available_days(self, email):
        """Get list of days in next 7 days that have available slots"""
        from .calendar_client import get_available_days_for_user
        return get_available_days_for_user(email, max_days=7)

    def get_slots_for_specific_day(self, email, day_name):
        """Get available slots for a specific day"""
        from .calendar_client import get_slots_for_specific_day_helper
        return get_slots_for_specific_day_helper(email, day_name)

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
        """Confirm and create the booking with domain-based display"""
        try:
            slot_start = parse_datetime(selected_slot["start_time"])
            slot_end = parse_datetime(selected_slot["end_time"])
            
            if not slot_start or not slot_end:
                return Response({"error": "Invalid datetime format in selected_slot"}, status=400)

            result = schedule_specific_slot(
                student_email=user.email,
                mentor_email=mentor_email,
                slot_start=slot_start,
                slot_end=slot_end,
                student_name=user.username,
                mentor_name=display_name
            )

            if result["success"]:
                booking = SessionBooking.objects.create(
                    user=user,
                    mentor=mentor,
                    organizer="UK Jobs Mentorship System",
                    start_time=result["start_time"],
                    end_time=result["end_time"],
                    meet_link=result["meet_link"],
                    attendees=[user.email, mentor_email],
                    event_id=result["event_id"],
                    status="confirmed"
                )

# Send email with calendar invite to both mentor & user
 # Send email with calendar invite to both mentor & user
                description = f"1-on-1 mentorship session with {display_name}"

                student_email = user.email
                student_name = user.username
                mentor_name = display_name  # or mentor.user.username if available

                send_success = send_enhanced_manual_invitations(
                    attendees=[student_email, mentor_email],
                    meet_link=result["meet_link"],
                    start_time=result["start_time"],
                    end_time=result["end_time"],
                    student_name=student_name,
                    mentor_name=mentor_name,
                    session_type="1-on-1 Mentorship"
                )

                if send_success:
                    print("✅ Calendar invite sent to both mentor and user")
                else:
                    print("❌ Failed to send calendar invite")



                if send_success:
                    print("✅ Calendar invite sent to both mentor and user")
                else:
                    print("❌ Failed to send calendar invite")


                profile.session_count += 1
                profile.save()

                return Response({
                    "success": True,
                    "message": f"✅ Your {display_name.lower()} session is confirmed for {result['start_time'].strftime('%A, %B %d at %I:%M %p')} IST!",
                    "booking_id": booking.id,
                    "meet_link": result["meet_link"],
                    "calendar_link": result.get("calendar_link"),
                    "start_time": result["start_time"].isoformat(),
                    "end_time": result["end_time"].isoformat(),
                    "session_type": display_name,
                    "session_count": profile.session_count
                }, status=200)
            else:
                return Response({"error": result.get("error", "Booking failed")}, status=500)

        except Exception as e:
            traceback.print_exc()
            return Response({"error": f"Error processing booking: {str(e)}"}, status=500)

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

            # Detect meeting intent
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
                        "username": "Sunil (Head Mentor)",
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

            # Default AI chat
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