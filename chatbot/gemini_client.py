# chatbot/gemini_client.py
import google.generativeai as genai
import os
from dotenv import load_dotenv
from PyPDF2 import PdfReader
from django.conf import settings

load_dotenv()

# ✅ Fix: Use environment variable name, not the actual key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or getattr(settings, 'GEMINI_API_KEY', None)

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("ERROR: GEMINI_API_KEY not found in environment or settings!")

# --- Load PDF instructions once ---
PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "ukjobs8.pdf")  # Better path handling

def load_pdf_text(pdf_path):
    try:
        if not os.path.exists(pdf_path):
            print(f"Warning: PDF not found at {pdf_path}")
            return "UKJobsInsider training data not available."
        
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        print(f"Error loading PDF: {str(e)}")
        return "UKJobsInsider training data not available."

# Load instructions on import
INSTRUCTION_TEXT = load_pdf_text(PDF_PATH)

def ask_gemini(user_message: str, is_premium: bool = False):
    """Send user query + system instructions to Gemini"""
    try:
        if not GEMINI_API_KEY:
            return "AI service is currently unavailable. Please contact support."
        
        model = genai.GenerativeModel("gemini-1.5-flash")

        # Free vs Premium rules
        if is_premium:
            role_instruction = "You are UKJobsInsider Premium Assistant. You have access to all features including session booking, detailed CV optimization, and comprehensive career guidance. Provide detailed, helpful responses."
        else:
            role_instruction = "You are UKJobsInsider Free Assistant. Provide helpful but concise responses (limit to 150 words). Do NOT allow session booking - suggest upgrading to Premium for 1-on-1 sessions."

        prompt = f"""
You are the official UKJobsInsider chatbot assistant helping users with UK job search.

TRAINING DATA & INSTRUCTIONS:
{INSTRUCTION_TEXT}

USER TYPE: {"Premium ✨" if is_premium else "Free"}
ROLE: {role_instruction}

IMPORTANT RULES:
1. Answer based on the UKJobsInsider training data above
2. Be helpful and professional 
3. For resources/PDFs, say "I can help you with that! The resource is available in your dashboard."
4. For Premium users: Allow all features including session booking
5. For Free users: Limit response length and suggest Premium for advanced features
6. Never mention technical limitations or say "I cannot access PDFs"

USER QUERY: {user_message}

RESPONSE:"""

        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        print(f"Gemini API Error: {str(e)}")
        return "I'm experiencing technical difficulties. Please try again in a moment."