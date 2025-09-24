# chatbot/emails.py
from django.core.mail import send_mail
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from django.conf import settings

def send_booking_email(to_emails, session):
    # placeholder implementation
    send_mail(
        subject=f"Booking Confirmed: {session.mentor_name}",
        message=f"Your session is confirmed for {session.start_time}.",
        from_email="no-reply@example.com",
        recipient_list=to_emails,
    )
def send_cancellation_email(student_email, student_name, mentor_email, mentor_name, session_time):
    """
    Send cancellation email to both student and mentor
    """
    subject_student = f"Your session with {mentor_name} has been cancelled"
    subject_mentor = f"Your session with {student_name} has been cancelled"

    # Handle datetime object
    if hasattr(session_time, 'strftime'):
        formatted_time = session_time.strftime('%A, %B %d, %Y at %I:%M %p')
    else:
        formatted_time = str(session_time)

    student_msg = f"""Hi {student_name},

Your scheduled session on {formatted_time} with {mentor_name} has been cancelled.

If you want to reschedule, please login and book a new slot.

Thanks,
UK Jobs Mentorship Team"""

    mentor_msg = f"""Hi {mentor_name},

The session scheduled on {formatted_time} with {student_name} has been cancelled.

You are now free for this time slot.

Thanks,
UK Jobs Mentorship Team"""

    try:
        # Send to student
        msg_student = MIMEMultipart()
        msg_student['From'] = settings.EMAIL_HOST_USER
        msg_student['To'] = student_email
        msg_student['Subject'] = subject_student
        msg_student.attach(MIMEText(student_msg, 'plain'))

        # Send to mentor
        msg_mentor = MIMEMultipart()
        msg_mentor['From'] = settings.EMAIL_HOST_USER
        msg_mentor['To'] = mentor_email
        msg_mentor['Subject'] = subject_mentor
        msg_mentor.attach(MIMEText(mentor_msg, 'plain'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)

        server.sendmail(settings.EMAIL_HOST_USER, [student_email], msg_student.as_string())
        server.sendmail(settings.EMAIL_HOST_USER, [mentor_email], msg_mentor.as_string())
        server.quit()

        print(f"✅ Cancellation email sent to {student_email} and {mentor_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send cancellation emails: {e}")
        return False
