# chatbot/urls.py
from django.urls import path
from .views import SignupView, LoginView, LogoutView, ScheduleView, ChatView, CancelRescheduleView,TimeSlotCancelView,TimeSlotRescheduleView,UserProfileView, test_email_send, TestView,AvailableSlotsView, list_mentors, test_email_config, TimeSlotBookingView, TimeSlotListView

urlpatterns = [
    # Authentication endpoints
    path('test/', TestView.as_view(), name='test'),
    path('auth/signup/', SignupView.as_view(), name='signup'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    
    # Feature endpoints
    path('schedule/', ScheduleView.as_view(), name='schedule'),
    path('chat/', ChatView.as_view(), name='chat'),
    path("mentors/", list_mentors, name="list_mentors"),
    path('available-slots/', AvailableSlotsView.as_view(), name='available-slots'),
    path('test-email/', test_email_send, name='test-email'),
    path("cancel-reschedule/", CancelRescheduleView.as_view(), name="cancel-reschedule"),
    path('test-email-config/', test_email_config, name='test_email_config'),
    path('book-slot/', TimeSlotBookingView.as_view(), name='book_slot'),
    path('timeslot/cancel/', TimeSlotCancelView.as_view(), name='timeslot-cancel'),
    path('timeslot/reschedule/', TimeSlotRescheduleView.as_view(), name='timeslot-reschedule'),
    # Add these URL patterns for the time slot views
    path('slots/<int:mentor_id>/', TimeSlotListView.as_view(), name='mentor_slots'),
    

]