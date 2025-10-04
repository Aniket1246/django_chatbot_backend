import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

import threading
import time
from datetime import date, datetime, timedelta, time as dt_time

from django.contrib.auth.models import User
from chatbot.models import UserProfile, Mentor, TimeSlot
from chatbot.calendar_client import book_time_slot

# ───────────────────────────────────────────────
print("Fetching mentor (id=14)...")
mentor = Mentor.objects.get(id=14)
print(f"Mentor: {mentor.user.username}")

# ───────────────────────────────────────────────
print("Getting Amit user...")
amit_user = User.objects.get(email='co2021.amit.ramtri@ves.ac.in')
amit_profile = UserProfile.objects.get(user=amit_user)
print(f"User: {amit_user.username}")

print("Creating test users...")
test_users = [amit_profile]
for i in range(2, 6):
    user, _ = User.objects.get_or_create(
        username=f'testuser{i}',
        defaults={'email': f'test{i}@example.com'}
    )
    profile, _ = UserProfile.objects.get_or_create(
        user=user,
        defaults={'is_premium': True}
    )
    profile.is_premium = True
    profile.save()
    test_users.append(profile)

print(f"Total users: {len(test_users)}")

# ───────────────────────────────────────────────
print("Creating test slots for Kapil...")
test_date = date.today() + timedelta(days=10)

# Optional cleanup — only test slots for that date
TimeSlot.objects.filter(mentor=mentor, date=test_date).delete()

slot_duration = 15  # minutes
start_dt = datetime.combine(test_date, dt_time(14, 0))  # 2:00 PM
end_of_day = datetime.combine(test_date, dt_time(15, 30))  # 3:30 PM (5 slots)

test_slots = []

while start_dt < end_of_day:
    end_dt = start_dt + timedelta(minutes=slot_duration)
    start_time = start_dt.time()
    end_time = end_dt.time()

    # Skip duplicates if any
    if not TimeSlot.objects.filter(
        mentor=mentor,
        date=test_date,
        start_time=start_time
    ).exists():
        slot = TimeSlot.objects.create(
            mentor=mentor,
            date=test_date,
            start_time=start_time,
            end_time=end_time,
            is_available=True,
            is_booked=False
        )
        test_slots.append(slot)
        print(f"Created slot {slot.start_time}–{slot.end_time}")
    else:
        print(f"Skipping duplicate slot at {start_time}")

    start_dt = end_dt

print(f"✅ Created {len(test_slots)} test slots on {test_date}")

# ───────────────────────────────────────────────
print("\n" + "="*60)
print("QUEUE TEST WITH AUTO-NEXT-SLOT")
print("="*60)

results = []


def attempt_booking(user_profile, slot_id, mentor_obj, user_num):
    start = time.time()
    try:
        print(f"User {user_num} attempting...")
        booking = book_time_slot(slot_id, user_profile, mentor_obj, auto_find_next=True)
        elapsed = time.time() - start
        booked_time = booking.start_time.strftime('%H:%M')
        results.append(f"User {user_num}: SUCCESS in {elapsed:.2f}s - Booked {booked_time}")
        print(f"✅ User {user_num}: {booked_time}")
    except Exception as e:
        elapsed = time.time() - start
        results.append(f"User {user_num}: FAILED in {elapsed:.2f}s - {str(e)[:60]}")
        print(f"❌ User {user_num}: FAILED - {str(e)[:60]}")


threads = []
for i, user in enumerate(test_users, 1):
    t = threading.Thread(target=attempt_booking, args=(user, test_slots[0].id, mentor, i))
    threads.append(t)

for t in threads:
    t.start()

for t in threads:
    t.join()

print("\n" + "="*60)
print("RESULTS:")
print("="*60)
for r in results:
    print(r)

# ───────────────────────────────────────────────
print("\n" + "="*60)
print("SLOT STATUS:")
print("="*60)
for i, slot in enumerate(test_slots, 1):
    slot.refresh_from_db()
    status = "BOOKED" if slot.is_booked else "AVAILABLE"
    by_user = slot.booking.user.username if getattr(slot, 'booking', None) else "None"
    print(f"Slot {i} ({slot.start_time}): {status} by {by_user}")

success_count = len([r for r in results if 'SUCCESS' in r])
print(f"\n{'='*60}")
print(f"SUCCESS: {success_count}/5")
print(f"FAILED: {5-success_count}/5")
print(f"{'='*60}")
