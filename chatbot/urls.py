# chatbot/urls.py
from django.urls import path
from .views import SignupView, LoginView, LogoutView, ScheduleView, ChatView, UserProfileView, test_email_send, TestView,AvailableSlotsView, list_mentors

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
    


]