import traceback
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
import json
from .utils import is_meeting_request, extract_duration
from datetime import datetime, timedelta
from .calendar_client import (
    schedule_specific_slot,
    get_next_available_slots_for_user,
    send_enhanced_manual_invitations
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_email_send(request):
    """Test email sending functionality"""
    try:
        from .calendar_client import send_enhanced_manual_invitations
        from datetime import datetime, timedelta
        
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
   # Add this function at the top of views.py after imports
def is_first_time_user(user):
    """Check if user has any previous confirmed sessions"""
    try:
        # Check if user has any previous bookings
        previous_bookings = SessionBooking.objects.filter(
            user=user, 
            status='confirmed'
        ).count()
        
        return previous_bookings == 0
    except:
        return True  # Assume first time if error
     
# ---------------- Utility for Premium Check ----------------
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


# ---------------- Signup ----------------
@method_decorator(csrf_exempt, name="dispatch")
class SignupView(APIView):
    permission_classes = [AllowAny]  # Explicitly allow unauthenticated access
    
    def post(self, request):
        try:
            # Handle both JSON and form data
            if request.content_type == 'application/json':
                data = json.loads(request.body)
            else:
                data = request.data

            email = data.get("email")
            password = data.get("password")

            if not email or not password:
                return Response({
                    "error": "Email and password are required"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Check if user exists
            if User.objects.filter(username=email).exists():
                return Response({
                    "error": "User already exists"
                }, status=status.HTTP_400_BAD_REQUEST)

            # Create user
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password
            )

            # Check premium from CSV
            premium_status = is_email_premium(email)

            # Create UserProfile
            UserProfile.objects.create(
                user=user,
                email=email,
                is_premium=premium_status
            )

            # Create token
            token, created = Token.objects.get_or_create(user=user)

            return Response({
                "message": "User created successfully",
                "token": token.key,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "is_premium": premium_status
                }
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                "error": f"Failed to create user: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ---------------- Login ----------------
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


# ---------------- Logout ----------------
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


# ---------------- Test View (for debugging) ----------------
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


# ---------------- User Profile ----------------
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


# ---------------- Schedule (Secured) ----------------
# chatbot/views.py
# chatbot/views.py

# ---------------- Schedule (Secured) ----------------
# Replace your ScheduleView class with this fixed version:



# In your ScheduleView class, update the post method to send emails after booking

# In your ScheduleView class, update the post method to fix the date/time and email issues
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def test_email_config(request):
    """Test email configuration with detailed debugging"""
    try:
        from django.core.mail import send_mail
        from django.conf import settings
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


# Fixed ScheduleView with proper email handling
# Update your ScheduleView class
class ScheduleView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            print("📌 [DEBUG] ScheduleView POST called")

            data = request.data
            mentor_id = data.get("mentor_id")
            selected_slot = data.get("selected_slot")

            profile, _ = UserProfile.objects.get_or_create(user=request.user)

            if not profile.is_premium:
                return Response({"error": "Only premium users can book sessions."}, status=403)

            if not mentor_id:
                return Response({"error": "mentor_id is required"}, status=400)

            # ---------------- HEAD MENTOR BOOKING ----------------
 # 🔥 HANDLE HEAD MENTOR BOOKING (First Time Users)
            if mentor_id == "head":
                head_email = "sunilramtri000@gmail.com"
                available_slots = get_next_available_slots_for_user(head_email, count=3)

                if not available_slots:
                    return Response({"error": "No available slots found"}, status=500)

                if selected_slot:
                    try:
                        slot_start = parse_datetime(selected_slot["start_time"])
                        slot_end = parse_datetime(selected_slot["end_time"])

                        result = schedule_specific_slot(
                            student_email=request.user.email,
                            mentor_email=head_email,
                            slot_start=slot_start,
                            slot_end=slot_end,
                            student_name=request.user.username,
                            mentor_name="Sunil (Head Mentor)"
                        )

                        if result["success"]:
                            booking = SessionBooking.objects.create(
                                user=request.user,
                                start_time=result["start_time"],
                                end_time=result["end_time"],
                                meet_link=result["meet_link"],
                                # calendar_event_id=result["event_id"],
                                status="confirmed"
                            )

                            # Invitations bhejna
                            send_enhanced_manual_invitations(
                                attendees=[request.user.email, head_email],
                                meet_link=result.get("meet_link"),
                                calendar_link=result.get("calendar_link"),
                                start_time=result.get("start_time"),
                                end_time=result.get("end_time"),
                                organizer_email=head_email,
                                student_name=request.user.username,
                                mentor_name="Sunil (Head Mentor)",
                                session_type="Head Mentor Session"
                            )

                            profile.session_count += 1
                            profile.save()

                            return Response({
                                "success": True,
                                "message": f"✅ Session booked for {result['start_time'].strftime('%A, %B %d at %I:%M %p')} IST!",
                                "booking_id": booking.id,
                                "meet_link": result["meet_link"],
                                "calendar_link": result.get("calendar_link"),
                                "start_time": result["start_time"].isoformat(),
                                "end_time": result["end_time"].isoformat(),
                                "mentor_name": "Sunil (Head Mentor)",   # 👈 sirf response me
                                "mentor_email": head_email,             # 👈 sirf response me
                                "session_count": profile.session_count
                            }, status=200)

                        return Response({"error": result.get("error", "Booking failed")}, status=500)

                    except Exception as e:
                        traceback.print_exc()
                        return Response({"error": f"Error processing selected slot: {str(e)}"}, status=500)

                # Agar slot select nahi hua hai → slots dikhana
                return Response({
                    "available_slots": [
                        {
                            "start_time": slot["start_time"].isoformat(),
                            "end_time": slot["end_time"].isoformat(),
                            "formatted_date": slot["formatted_date"],
                            "formatted_time": slot["formatted_time"]
                        }
                        for slot in available_slots
                    ],
                    "message": "📅 Available slots with Head Mentor. Please confirm one.",
                    "mentor_name": "Sunil (Head Mentor)"
                }, status=200)


            # ---------------- REGULAR MENTORS ----------------
            mentor = Mentor.objects.filter(id=mentor_id, is_active=True).select_related("user").first()
            if not mentor:
                return Response({"error": "Invalid or inactive mentor"}, status=400)

            if selected_slot:
                try:
                    slot_start = parse_datetime(selected_slot["start_time"])
                    slot_end = parse_datetime(selected_slot["end_time"])
                    if not slot_start or not slot_end:
                        return Response({"error": "Invalid datetime format in selected_slot"}, status=400)

                    result = schedule_specific_slot(
                        student_email=request.user.email,
                        mentor_email=mentor.user.email,
                        slot_start=slot_start,
                        slot_end=slot_end,
                        student_name=request.user.username,
                        mentor_name=mentor.user.username
                    )

                    if result["success"]:
                        booking = SessionBooking.objects.create(
                            user=request.user,
                            mentor=mentor,
                            organizer="UK Jobs Mentorship System",
                            start_time=result["start_time"],
                            end_time=result["end_time"],
                            meet_link=result["meet_link"],
                            calendar_link=result.get("calendar_link", ""),
                            attendees=[request.user.email, mentor.user.email],
                            event_id=result["event_id"],
                            status="confirmed"
                        )

                        try:
                            send_enhanced_manual_invitations(
                                attendees=[request.user.email, mentor.user.email],
                                meet_link=result.get("meet_link"),
                                calendar_link=result.get("calendar_link"),
                                start_time=result.get("start_time"),
                                end_time=result.get("end_time"),
                                organizer_email="sunilramtri000@gmail.com",
                                student_name=request.user.username,
                                mentor_name=mentor.user.username,
                                session_type="1-on-1 Mentorship"
                            )
                            print("✅ [DEBUG] Email invitations sent")
                        except Exception as mail_err:
                            print("❌ [ERROR] Email failed:", mail_err)

                        profile.session_count += 1
                        profile.save()

                        return Response({
                            "success": True,
                            "message": f"✅ Session booked for {result['start_time'].strftime('%A, %B %d at %I:%M %p')} IST!",
                            "booking_id": booking.id,
                            "meet_link": result["meet_link"],
                            "calendar_link": result.get("calendar_link"),
                            "start_time": result["start_time"].isoformat(),
                            "end_time": result["end_time"].isoformat(),
                            "mentor_name": mentor.user.username,
                            "session_count": profile.session_count
                        }, status=200)
                    else:
                        return Response({"error": result.get("error", "Booking failed")}, status=500)

                except Exception as e:
                    traceback.print_exc()
                    return Response({"error": f"Error processing selected slot: {str(e)}"}, status=500)

            # Else return available slots for mentor
            available_slots = get_next_available_slots_for_user(mentor.user.email, count=3)
            if not available_slots:
                return Response({"error": "No available slots found. Please try again later."}, status=500)

            return Response({
                "available_slots": [
                    {
                        "start_time": slot["start_time"].isoformat(),
                        "end_time": slot["end_time"].isoformat(),
                        "formatted_date": slot["formatted_date"],
                        "formatted_time": slot["formatted_time"]
                    }
                    for slot in available_slots
                ],
                "message": f"📅 Available slots with {mentor.user.username}. Please confirm one.",
                "mentor_name": mentor.user.username
            }, status=200)

        except Exception as e:
            traceback.print_exc()
            return Response({"error": str(e)}, status=500)


        
# Optional: Add a view to check available slots
class AvailableSlotsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return next 5 available 2-hour slots"""
        try:
            from .calendar_client import find_next_available_2hour_slot, get_busy_slots
            import datetime
            
            available_slots = []
            current_time = datetime.datetime.now()
            
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
                    current_time += datetime.timedelta(days=1)
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


            # -------- NEXT SESSIONS (Mentors) --------
            if not mentor_id:
                return Response({"error": "mentor_id is required for next sessions"}, status=400)

            mentor = Mentor.objects.filter(id=mentor_id, is_active=True).select_related("user").first()
            if not mentor:
                return Response({"error": "Invalid mentor"}, status=400)

            from .calendar_client import find_next_available_slot, create_event, send_manual_invitations
            start_time, end_time = find_next_available_slot(duration)

            attendees = [booking_user.email, mentor.user.email]
            cal_event = create_event(
                summary=f"1-on-1 Session with {mentor.user.username}",
                description=f"Mentorship session with {mentor.user.username}",
                start_time_ist=start_time,
                end_time_ist=end_time,
                attendees=attendees
            )
            send_manual_invitations(attendees, cal_event["meet_link"], cal_event["calendar_link"], start_time, end_time)

            booking = SessionBooking.objects.create(
                 user=request.user,
                organizer=organizer_user.username,
                start_time=result.get("start_time"),
                end_time=result.get("end_time"),
                meet_link=result.get("meet_link"),
                calendar_link=result.get("calendar_link", ""),  # safe default empty string
                attendees=attendees_value,
                mentor=mentor_obj,
                status="confirmed"
)


            return Response({
                "success": True,
                "message": f"✅ Session booked with {mentor.user.username} for {start_time.strftime('%I:%M %p')} IST!",
                "meet_link": cal_event["meet_link"],
                "calendar_link": cal_event["calendar_link"],
                "start_time_ist": start_time.isoformat(),
                "end_time_ist": end_time.isoformat(),
                "attendees": attendees,
                "mentor": mentor.user.username,
                "booking_id": booking.id
            })

        except Exception as e:
            traceback.print_exc()
            return Response({"error": str(e)}, status=500)





# ---------------- Chat (Secured) ----------------
# views.py
from .utils import is_meeting_request, extract_duration
from .gemini_client import ask_gemini

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
                
                # 🔥 CHECK IF FIRST TIME USER
                if is_first_time_user(request.user):
                    # First time user - show head mentor only
                    head_mentor = {
                        "id": "head",  # Special ID
                        "username": "Sunil (Head Mentor)",
                        "email": "sunilramtri000@gmail.com",
                        "expertise": "Initial Assessment & Career Guidance"
                    }
                    
                    return Response({
                        "reply": "🎯 Welcome! As a first-time premium user, your initial session will be with our Head Mentor for assessment and guidance. Please select to continue:",
                        "mentors": [head_mentor],
                        "is_first_time": True
                    }, status=200)
                
                else:
                    # Returning user - show all mentors
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
                        "is_first_time": False
                    }, status=200)

            # Default AI chat
            reply = ask_gemini(message, is_premium)
            return Response({"reply": reply}, status=200)

        except Exception as e:
            traceback.print_exc()
            return Response({"error": str(e)}, status=500)