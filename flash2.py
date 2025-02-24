import streamlit as st
import sqlite3
import json
import time
import PyPDF2
from groq import Groq

# ---------------------------------------------------------------------------------
# ------------------------- CONFIGURATION -----------------------------------------
# ---------------------------------------------------------------------------------
API_MODEL = "gemma2-9b-it"
GROQ_API_KEY = "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"

# ---------------------------------------------------------------------------------
# ------------------------- DATABASE SETUP ----------------------------------------
# ---------------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute(
        '''CREATE TABLE IF NOT EXISTS users (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT UNIQUE,
                 password TEXT,
                 analytics TEXT
         )'''
    )
    # Check and add analytics column if missing
    c.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in c.fetchall()]
    if "analytics" not in columns:
        c.execute("ALTER TABLE users ADD COLUMN analytics TEXT")
    conn.commit()
    conn.close()

init_db()

def update_user_analytics(username, analytics):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("UPDATE users SET analytics=? WHERE username=?", (json.dumps(analytics), username))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------------
# ------------------------- AUTHENTICATION FUNCTIONS ------------------------------
# ---------------------------------------------------------------------------------
def login(username, password):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
    user = c.fetchone()
    conn.close()
    
    # Default analytics structure
    default_analytics = {
        "pdfs_uploaded": 0,
        "flashcards_generated": 0,
        "flashcards_viewed": 0,
        "tests_taken": 0,
        "last_test_score": 0,
        "test_insights": ""
    }
    
    if user:
        st.session_state["user"] = username
        try:
            st.session_state["analytics"] = json.loads(user[3]) if user[3] else default_analytics
        except Exception as e:
            st.session_state["analytics"] = default_analytics
        st.rerun()
    else:
        st.error("Invalid login credentials")

def signup(username, password):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    try:
        initial_analytics = json.dumps({
            "pdfs_uploaded": 0,
            "flashcards_generated": 0,
            "flashcards_viewed": 0,
            "tests_taken": 0,
            "last_test_score": 0,
            "test_insights": ""
        })
        c.execute("INSERT INTO users (username, password, analytics) VALUES (?, ?, ?)",
                  (username, password, initial_analytics))
        conn.commit()
        st.success("Signup successful. Please log in.")
    except sqlite3.IntegrityError:
        st.error("Username already exists")
    conn.close()

# ---------------------------------------------------------------------------------
# ------------------------- PDF TEXT EXTRACTION -----------------------------------
# ---------------------------------------------------------------------------------
def extract_text_from_pdf(pdf_file):
    text = ""
    reader = PyPDF2.PdfReader(pdf_file)
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            text += extracted
    return text

# ---------------------------------------------------------------------------------
# ------------------------- HELPER FUNCTION FOR FLASHCARDS ------------------------
# ---------------------------------------------------------------------------------
def clean_flashcard_text(text):
    """
    Remove unnecessary formatting markers from the flashcard text.
    """
    markers = ["** front **", "**Front**", "(back front)", "** back **", "Front:", "Back:"]
    for marker in markers:
        text = text.replace(marker, "")
    return text.strip()

# ---------------------------------------------------------------------------------
# ------------------------- GROQ AI FUNCTIONS -------------------------------------
# ---------------------------------------------------------------------------------
def generate_flashcard_response_groq(pdf_text, user_input):
    client = Groq(api_key=GROQ_API_KEY)
    max_text_length = 1500
    pdf_text = pdf_text[:max_text_length]
    prompt_template = (
        "You are a chatbot that helps users learn topics from a given document by creating flashcards. "
        "The document content is as follows:\n\n'{pdf_text}'\n\n"
        "User's question or topic: '{user_input}'\n"
        "Create a flashcard with a question and answer based on the document content."
    )
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt_template.format(pdf_text=pdf_text, user_input=user_input)}],
            model=API_MODEL
        )
        flashcard_text = chat_completion.choices[0].message.content.strip()
        # Clean the flashcard text before returning
        flashcard_text = clean_flashcard_text(flashcard_text)
        return flashcard_text
    except Exception as e:
        st.error(f"Error generating flashcard: {str(e)}")
        return "Error generating flashcard."

def generate_test_questions_groq(pdf_text):
    client = Groq(api_key=GROQ_API_KEY)
    max_text_length = 1500
    pdf_text = pdf_text[:max_text_length]
    prompt_template = (
        "Generate 10 multiple-choice questions from this document:\n\n'{pdf_text}'\n\n"
        "For each question, provide a JSON object with: 'question', 'options' (list of 4), and 'correct'. "
        "Return as a JSON array."
    )
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt_template.format(pdf_text=pdf_text)}],
            model=API_MODEL
        )
        return json.loads(chat_completion.choices[0].message.content.strip())
    except Exception as e:
        st.error(f"Error generating test: {str(e)}")
        return []

def generate_test_insights_groq(score):
    client = Groq(api_key=GROQ_API_KEY)
    prompt = f"Provide concise learning insights for a test score of {score}/10."
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=API_MODEL
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        return ""

# ---------------------------------------------------------------------------------
# ------------------------- MAIN USER INTERFACE -----------------------------------
# ---------------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="EduFlash", layout="wide", page_icon="📚")
    
    # ---------------------- CUSTOM CSS STYLING -----------------------------------
    st.markdown("""
    <style>
    [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
        color: #4CAF50 !important;
    }
    .flashcard {
        background: #1E1E1E;
        border-radius: 10px;
        padding: 2rem;
        margin: 1rem 0;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .stButton>button {
        background: #4CAF50 !important;
        color: white !important;
        border: none !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # ---------------------- SIDEBAR MENU -----------------------------------------
    if "user" not in st.session_state:
        menu = ["Login", "Sign Up"]
    else:
        menu = ["Dashboard", "Flashcards", "Test", "Logout"]
    
    choice = st.sidebar.selectbox("Menu", menu, key="menu")
    
    # ---------------------- LOGIN SECTION ----------------------------------------
    if choice == "Login":
        with st.container():
            st.title("🔒 Login")
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            if st.button("Login", use_container_width=True):
                login(username, password)
                
    # ---------------------- SIGN UP SECTION --------------------------------------
    elif choice == "Sign Up":
        with st.container():
            st.title("📝 Sign Up")
            username = st.text_input("Choose Username", key="signup_username")
            password = st.text_input("Choose Password", type="password", key="signup_password")
            if st.button("Create Account", use_container_width=True):
                signup(username, password)
                
    # ---------------------- LOGOUT SECTION ---------------------------------------
    elif choice == "Logout":
        st.session_state.clear()
        st.rerun()
    
    # ---------------------- DASHBOARD SECTION ------------------------------------
    elif choice == "Dashboard":
        st.title("📊 Learning Dashboard")
        st.write(f"Welcome back, {st.session_state['user']}! 🎉")
        analytics = st.session_state.get("analytics", {})
        
        cols = st.columns(4)
        metrics = [
            ("PDFs Uploaded", "📄", analytics.get("pdfs_uploaded", 0)),
            ("Flashcards Generated", "🔄", analytics.get("flashcards_generated", 0)),
            ("Tests Taken", "📝", analytics.get("tests_taken", 0)),
            ("Avg Score", "🎯", f"{analytics.get('last_test_score', 0)}/10")
        ]
        for col, (title, icon, value) in zip(cols, metrics):
            col.metric(title, f"{icon} {value}")
        
        with st.expander("Detailed Analytics"):
            st.write(f"**Flashcards Viewed:** {analytics.get('flashcards_viewed', 0)}")
            st.write(f"**Last Test Insights:** {analytics.get('test_insights', 'N/A')}")
    
    # ---------------------- FLASHCARDS SECTION -----------------------------------
    elif choice == "Flashcards":
        st.title("📖 Flashcard Generator")
        # Upload PDF and persist the extracted text
        uploaded_file = st.file_uploader("Upload PDF", type="pdf", key="pdf_uploader")
        
        if uploaded_file:
            # Save PDF text in session state if not already done
            if "pdf_text" not in st.session_state:
                pdf_text = extract_text_from_pdf(uploaded_file)
                st.session_state["pdf_text"] = pdf_text
                # Update analytics only once for PDF upload
                if "pdf_uploaded_once" not in st.session_state:
                    st.session_state["analytics"]["pdfs_uploaded"] += 1
                    update_user_analytics(st.session_state["user"], st.session_state["analytics"])
                    st.session_state["pdf_uploaded_once"] = True
            else:
                pdf_text = st.session_state["pdf_text"]
            
            # Use the user's query only to generate the initial flashcard topic.
            # The flashcard is stored in session state so it doesn't get repeated.
            if "current_flashcard" not in st.session_state:
                user_input = st.text_input("Enter topic/question for flashcard:", key="flashcard_query")
                if user_input:
                    flashcard = generate_flashcard_response_groq(pdf_text, user_input)
                    st.session_state["current_flashcard"] = flashcard
                    st.session_state["analytics"]["flashcards_generated"] += 1
                    update_user_analytics(st.session_state["user"], st.session_state["analytics"])
            else:
                # Keep the text input empty after the first flashcard generation
                user_input = st.text_input("Enter topic/question for flashcard:", key="flashcard_query", value="")
            
            # Display the current flashcard if available
            if "current_flashcard" in st.session_state:
                with st.container():
                    st.markdown(f"""
                    <div class="flashcard">
                        <h3 style='text-align:center;border-bottom: 1px solid #4CAF50;padding-bottom: 0.5rem;'>
                            {st.session_state.get("flashcard_query", "Flashcard Topic")}
                        </h3>
                        <p style='text-align:center;margin-top: 1rem;'>{st.session_state["current_flashcard"]}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Options to modify the flashcard without creating duplicates
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("Simplify Explanation"):
                            simplified = generate_flashcard_response_groq(pdf_text, "Simplify this explanation")
                            st.session_state["current_flashcard"] = simplified
                            st.session_state["analytics"]["flashcards_generated"] += 1
                            update_user_analytics(st.session_state["user"], st.session_state["analytics"])
                            st.rerun()
                    with col2:
                        if st.button("Generate New"):
                            if "flashcard_query" in st.session_state and st.session_state["flashcard_query"]:
                                new_flashcard = generate_flashcard_response_groq(pdf_text, st.session_state["flashcard_query"])
                                # Only update if the new flashcard is different to avoid duplicates
                                if new_flashcard != st.session_state["current_flashcard"]:
                                    st.session_state["current_flashcard"] = new_flashcard
                                    st.session_state["analytics"]["flashcards_viewed"] += 1
                                    update_user_analytics(st.session_state["user"], st.session_state["analytics"])
                                else:
                                    st.info("Generated flashcard is the same as the current one. Try modifying the query.")
                            else:
                                st.error("No flashcard topic provided.")
                            st.rerun()
        else:
            st.info("Please upload a PDF to generate flashcards.")
    
    # ---------------------- TEST SECTION -----------------------------------------
    elif choice == "Test":
        st.title("📝 Knowledge Test")
        # Check if a PDF was uploaded by verifying pdf_text in session state
        if "pdf_text" not in st.session_state:
            st.info("No PDF uploaded yet. Please upload a PDF in the Flashcards section to generate a test.")
        else:
            # If test questions are not yet generated, provide a button to create them
            if "test_questions" not in st.session_state:
                if st.button("Generate Test Questions"):
                    test_questions = generate_test_questions_groq(st.session_state["pdf_text"])
                    if test_questions:
                        st.session_state["test_questions"] = test_questions
                    else:
                        st.error("Failed to generate test questions. Please try again.")
            
            # If test questions exist, display the test interface
            if "test_questions" in st.session_state:
                answers = {}
                for i, q in enumerate(st.session_state["test_questions"]):
                    with st.container():
                        st.subheader(f"Question {i+1}")
                        answers[i] = st.radio(q["question"], q["options"], key=f"q_{i}")
                
                if st.button("Submit Test"):
                    score = sum(1 for i, q in enumerate(st.session_state["test_questions"]) 
                                if answers.get(i) == q["correct"])
                    insights = generate_test_insights_groq(score)
                    st.session_state["analytics"].update({
                        "tests_taken": st.session_state["analytics"].get("tests_taken", 0) + 1,
                        "last_test_score": score,
                        "test_insights": insights
                    })
                    update_user_analytics(st.session_state["user"], st.session_state["analytics"])
                    
                    st.success(f"Score: {score}/10")
                    with st.expander("Test Insights"):
                        st.write(insights)
                    
                    # Provide detailed test review
                    st.subheader("Test Review")
                    for i, q in enumerate(st.session_state["test_questions"]):
                        st.write(f"**Question {i+1}:** {q['question']}")
                        st.write(f"**Your Answer:** {answers.get(i, 'No answer')}")
                        st.write(f"**Correct Answer:** {q['correct']}")
                        if answers.get(i) == q["correct"]:
                            st.success("✅ Correct")
                        else:
                            st.error("❌ Incorrect")
                        st.write("---")
                    
                    # Clear test questions after submission to avoid repetition
                    del st.session_state["test_questions"]

# ---------------------------------------------------------------------------------
# ------------------------- EXECUTE MAIN FUNCTION -------------------------------
# ---------------------------------------------------------------------------------
if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------------
# ------------------------- ADDITIONAL PADDING ------------------------------------
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
# ------------------------- END OF CODE -----------------------------------------
