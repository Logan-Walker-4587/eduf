import streamlit as st
import sqlite3
import json
import time
import PyPDF2
from groq import Groq
import re
import html  # for unescaping HTML entities
import pandas as pd  # For dashboard graph

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

# ---------------------------------------------------------------------------------
# --------------------- FLASHCARD SESSION DATABASE SETUP --------------------------
# ---------------------------------------------------------------------------------
def init_session_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    
    # First create the table if it doesn't exist with original schema
    c.execute(
        '''CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                session_name TEXT,
                flashcards TEXT,
                pdf_content TEXT,
                created_at TEXT
         )'''
    )
    
    # Check if pdf_content column exists
    c.execute("PRAGMA table_info(sessions)")
    columns = [col[1] for col in c.fetchall()]
    
    # Add pdf_content column if it doesn't exist
    if "pdf_content" not in columns:
        c.execute("ALTER TABLE sessions ADD COLUMN pdf_content TEXT")
    
    conn.commit()
    conn.close()

init_session_db()

# ---------------------------------------------------------------------------------
# --------------------- COMMUNITY DATABASE SETUP ----------------------------------
# ---------------------------------------------------------------------------------
def init_community_db():
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    
    # Create communities table
    c.execute(
        '''CREATE TABLE IF NOT EXISTS communities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                description TEXT
         )'''  
    )
    
    # Create community_members table
    c.execute(
        '''CREATE TABLE IF NOT EXISTS community_members (
                community_id INTEGER,
                username TEXT,
                PRIMARY KEY (community_id, username),
                FOREIGN KEY (community_id) REFERENCES communities(id)
         )'''  
    )
    
    # Create community_flashcards table
    c.execute(
        '''CREATE TABLE IF NOT EXISTS community_flashcards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                community_id INTEGER,
                flashcard_data TEXT,
                shared_by TEXT,
                created_at TEXT,
                FOREIGN KEY (community_id) REFERENCES communities(id)
         )'''  
    )
    
    conn.commit()
    conn.close()

init_community_db()

def update_user_analytics(username, analytics):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("UPDATE users SET analytics=? WHERE username=?", (json.dumps(analytics), username))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------------
# --------------------- FLASHCARD SESSION FUNCTIONS -------------------------------
# ---------------------------------------------------------------------------------
def create_session(session_name, pdf_content=None):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    created_at = time.strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO sessions (username, session_name, flashcards, pdf_content, created_at) VALUES (?, ?, ?, ?, ?)",
              (st.session_state["user"], session_name, json.dumps([]), pdf_content, created_at))
    conn.commit()
    session_id = c.lastrowid
    conn.close()
    return session_id

def update_session_flashcards(session_id, flashcards):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("UPDATE sessions SET flashcards=? WHERE id=? AND username=?",
              (json.dumps(flashcards), session_id, st.session_state["user"]))
    conn.commit()
    conn.close()

def get_sessions(username):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT id, session_name, flashcards, pdf_content, created_at FROM sessions WHERE username=? ORDER BY created_at DESC", (username,))
    sessions = c.fetchall()
    conn.close()
    return sessions

def delete_session(session_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("DELETE FROM sessions WHERE id=? AND username=?", (session_id, st.session_state["user"]))
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------------
# --------------------- COMMUNITY MANAGEMENT FUNCTIONS ----------------------------
# ---------------------------------------------------------------------------------
def create_community(name, description):
    if not name:
        st.error("Community name is required")
        return None
    
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    
    try:
        # Check if the community name already exists
        c.execute("SELECT id FROM communities WHERE name=?", (name,))
        if c.fetchone():
            st.error("A community with this name already exists.")
            return None
        
        # Ensure the user is logged in before adding them
        if "user" not in st.session_state:
            st.error("You must be logged in to create a community.")
            return None
        
        # Insert the new community
        c.execute("INSERT INTO communities (name, description) VALUES (?, ?)", (name, description))
        community_id = c.lastrowid
        
        # Add the creator as a member
        c.execute("INSERT INTO community_members (community_id, username) VALUES (?, ?)", 
                  (community_id, st.session_state["user"]))
        
        conn.commit()
        st.success(f"Community '{name}' created successfully!")
        return community_id
    
    except sqlite3.Error as e:
        conn.rollback()
        st.error(f"Database error: {e}")
        return None
    
    finally:
        conn.close()

def join_community(community_id, username):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("INSERT INTO community_members (community_id, username) VALUES (?, ?)", (community_id, username))
    conn.commit()
    conn.close()


def leave_community(username):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()

    try:
        # Fetch communities where the user is a member
        c.execute("""
            SELECT c.id, c.name 
            FROM communities c
            INNER JOIN community_members cm ON c.id = cm.community_id
            WHERE cm.username=?
        """, (username,))

        communities = c.fetchall()  # List of (id, name)

        return communities if communities else []

    except sqlite3.Error as e:
        st.error(f"Database error: {e}")
        return []
    
    finally:
        conn.close()

def leave_selected_community(community_id, username):
    if not community_id or not username:
        st.error("Community ID and username are required")
        return False
    
    conn = None
    try:
        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        
        # Check if user is a member
        c.execute("SELECT 1 FROM community_members WHERE community_id=? AND username=?", 
                 (community_id, username))
        if not c.fetchone():
            st.error("You are not a member of this community")
            return False
            
        c.execute("DELETE FROM community_members WHERE community_id=? AND username=?", 
                 (community_id, username))
        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"Database error: {str(e)}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

def share_flashcard_to_community(community_ids, flashcard_data, shared_by):
    if not community_ids or not flashcard_data:
        st.error("Community IDs and flashcard data are required.")
        return False
    
    conn = sqlite3.connect("users.db")
    try:
        c = conn.cursor()
        created_at = time.strftime("%Y-%m-%d %H:%M:%S")
        for community_id in community_ids:
            c.execute("INSERT INTO community_flashcards (community_id, flashcard_data, shared_by, created_at) VALUES (?, ?, ?, ?)",
                       (community_id, flashcard_data, shared_by, created_at))
        conn.commit()
        return True
    except sqlite3.Error as e:
        st.error(f"Database error: {str(e)}")
        conn.rollback()
        return False
    finally:
        conn.close()

def delete_shared_flashcard(flashcard_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("DELETE FROM community_flashcards WHERE id=?", (flashcard_id,))
    conn.commit()
    conn.close()

def delete_community(community_id):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("DELETE FROM communities WHERE id=?", (community_id,))
    conn.commit()
    conn.close()

# New function to get user communities
def get_user_communities(username):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT c.id, c.name FROM communities c INNER JOIN community_members cm ON c.id = cm.community_id WHERE cm.username=?", (username,))
    communities = c.fetchall()
    conn.close()
    return communities  # Returns (id, name)

# ---------------------------------------------------------------------------------
# ------------------------- AUTHENTICATION FUNCTIONS ------------------------------
# ---------------------------------------------------------------------------------
def validate_password(password):
    """
    Validates the password based on predefined security criteria.
    Returns True if valid, otherwise returns False and an error message.
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    
    if not re.search(r"\d", password):
        return False, "Password must contain at least one digit."
    
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False, "Password must contain at least one special character (!@#$%^&* etc.)."
    
    return True, "Password is valid."

def login(username, password):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE username=?", (username,))
    user = c.fetchone()
    conn.close()
    
    if user:
        if user[2] == password:  #
            st.session_state["user"] = username
            # Initialize analytics if not present
            try:
                analytics = json.loads(user[3]) if user[3] else {}
            except json.JSONDecodeError:
                analytics = {}
            
            # Ensure all required analytics fields exist
            analytics.setdefault("pdfs_uploaded", 0)
            analytics.setdefault("flashcards_generated", 0)
            analytics.setdefault("flashcards_viewed", 0)
            analytics.setdefault("tests_taken", 0)
            analytics.setdefault("last_test_score", 0)
            analytics.setdefault("test_history", [])
            analytics.setdefault("test_insights", "No tests taken yet")
            
            st.session_state["analytics"] = analytics
            st.success("Logged in successfully!")
            st.rerun()
        else:
            st.error("Incorrect password")
    else:
        st.error("User not found")

def signup(username, password):
    is_valid, message = validate_password(password)
    if not is_valid:
        st.error(message)
        return
    
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    try:
        initial_analytics = json.dumps({
            "pdfs_uploaded": 0,
            "flashcards_generated": 0,
            "flashcards_viewed": 0,
            "tests_taken": 0,
            "last_test_score": 0,
            "test_history": [],
            "test_insights": "No tests taken yet"
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
# --------------------- HELPER FUNCTION FOR FLASHCARDS ----------------------------
# ---------------------------------------------------------------------------------
def clean_flashcard_text(text: str) -> str:
    """
    1. Unescape HTML entities.
    2. Remove HTML tags.
    3. Remove common markers (Front:, Back:, etc.).
    4. Strip whitespace.
    """
    text = html.unescape(text)
    text = re.sub(r"<[^>]*>", "", text)
    markers = ["** front **", "**Front**", "(back front)", "** back **", "Front:", "Back:"]
    for marker in markers:
        text = text.replace(marker, "")
    return text.strip()

# ---------------------------------------------------------------------------------
# ------------------------- GROQ AI FUNCTIONS -------------------------------------
# ---------------------------------------------------------------------------------
def generate_flashcard_question_groq(pdf_text, user_input, prev_question=""):
    client = Groq(api_key=GROQ_API_KEY)
    max_text_length = 1500
    pdf_text = pdf_text[:max_text_length]

    prompt_template = (
        "You are an expert tutor helping a student understand complex documents.\n"
        "The document content is as follows:\n\n"
        "'{pdf_text}'\n\n"
        "The student is interested in the following topic/question: '{user_input}'.\n\n"
        "Please generate ONE clear and concise flashcard question that tests a key concept from the document.\n"
        "- Do not include the answer in your response.\n"
        "- If a previous flashcard question was provided ('{prev_question}'), ensure the new question is different.\n"
        "- Output only plain text, starting with 'Question:' and then the question. No HTML.\n"
    )
    prompt = prompt_template.format(pdf_text=pdf_text, user_input=user_input, prev_question=prev_question)
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=API_MODEL
        )
        question_text = chat_completion.choices[0].message.content.strip()
        return clean_flashcard_text(question_text)
    except Exception as e:
        st.error(f"Error generating flashcard question: {str(e)}")
        return "Error generating flashcard question."

def generate_flashcard_answer_groq(pdf_text, question):
    client = Groq(api_key=GROQ_API_KEY)
    max_text_length = 1500
    pdf_text = pdf_text[:max_text_length]

    prompt_template = (
        "You are an expert tutor helping a student understand complex documents.\n"
        "The document content is as follows:\n\n"
        "'{pdf_text}'\n\n"
        "Given the flashcard question below:\n\n"
        "'{question}'\n\n"
        "Please provide a detailed and accurate answer in plain text only.\n"
        "Do not include any labels like 'Answer:' or use any HTML. Just return the text.\n"
    )
    prompt = prompt_template.format(pdf_text=pdf_text, question=question)
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=API_MODEL
        )
        answer_text = chat_completion.choices[0].message.content.strip()
        return clean_flashcard_text(answer_text)
    except Exception as e:
        st.error(f"Error generating flashcard answer: {str(e)}")
        return "Error generating flashcard answer."

def generate_simplified_explanation_groq(pdf_text, answer):
    client = Groq(api_key=GROQ_API_KEY)
    max_text_length = 1500
    pdf_text = pdf_text[:max_text_length]

    prompt_template = (
        "You are an expert tutor. The student did not understand the following answer:\n\n"
        "'{answer}'\n\n"
        "Based on the original document:\n\n"
        "'{pdf_text}'\n\n"
        "Please re-explain this answer in simpler terms, step by step, avoiding complex jargon.\n"
        "Return only plain text, with no HTML.\n"
    )
    prompt = prompt_template.format(pdf_text=pdf_text, answer=answer)
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=API_MODEL
        )
        simplified_text = chat_completion.choices[0].message.content.strip()
        return clean_flashcard_text(simplified_text)
    except Exception as e:
        st.error(f"Error simplifying explanation: {str(e)}")
        return "Error simplifying explanation."

def generate_test_questions_groq(pdf_text):
    client = Groq(api_key=GROQ_API_KEY)
    max_text_length = 1500
    pdf_text = pdf_text[:max_text_length]

    prompt_template = (
        "Generate 10 multiple-choice questions from this document:\n\n"
        "'{pdf_text}'\n\n"
        "For each question, provide a JSON array of objects with keys:\n"
        "  'question': plain text of the question,\n"
        "  'options': a list of 4 possible answers in plain text,\n"
        "  'correct': the correct option in plain text.\n"
        "Ensure the response is strictly a valid JSON array with no additional text."
    )
    prompt = prompt_template.format(pdf_text=pdf_text)

    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=API_MODEL
        )
        response_text = chat_completion.choices[0].message.content.strip()

        # Log the raw response for debugging
        print("Raw response:", response_text)

        # Ensure the response only contains a valid JSON array
        start_index = response_text.find('[')
        end_index = response_text.rfind(']')
        if start_index == -1 or end_index == -1:
            raise ValueError("Invalid JSON format: Missing '[' or ']'\n")
        
        # Extract only the JSON part
        json_text = response_text[start_index:end_index+1]

        # Log the extracted JSON for debugging
        print("Extracted JSON:", json_text)

        # Attempt to parse the JSON safely
        if not json_text:
            raise ValueError("Extracted JSON is empty.")
        
        try:
            test_questions = json.loads(json_text)
            return test_questions
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON parsing error: {e}")

    except Exception as e:
        st.error(f"Error generating test questions: {str(e)}")
        return []

def generate_test_insights_groq(score, wrong_qas=None):
    if wrong_qas is None:
        wrong_qas = []
    client = Groq(api_key=GROQ_API_KEY)
    prompt = (
        f"You are an expert tutor. Provide detailed learning insights for a test score of {score}/10.\n"
        "Return only plain text, with no HTML.\n"
    )
    if wrong_qas:
        wrong_details = "\n".join([f"Question: {item['question']}\nAnswer: {item['answer']}" for item in wrong_qas])
        prompt += (
            "The student answered the following questions incorrectly:\n" +
            wrong_details +
            "\nPlease analyze the mistakes and suggest areas for improvement."
        )
    else:
        prompt += "No specific wrong questions provided."
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=API_MODEL
        )
        return clean_flashcard_text(chat_completion.choices[0].message.content.strip())
    except Exception as e:
        st.error(f"Error generating test insights: {str(e)}")
        return ""
# ---------------------------------------------------------------------------------
# ------------------------- MAIN USER INTERFACE -----------------------------------
# ---------------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="EduFlash", layout="wide", page_icon="📚")
    
    st.markdown("""
    <style>
    [data-testid="stMetricValue"] {
        font-size: 1.5rem !important;
        color: #4CAF50 !important;
    }
    
    /* Flashcard Styling */
    .flashcard {
        background: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 10px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.1);
    }
    
    .flashcard p {
        color: #343a40;
        font-size: 16px;
        text-align: center;
        margin: 0;
    }

    /* Button Styling */
    .stButton>button {
        background: #007bff !important;
        color: white !important;
        border-radius: 5px !important;
        padding: 10px 15px !important;
        font-size: 16px !important;
        font-weight: bold !important;
        transition: background 0.3s ease-in-out !important;
    }

    .stButton>button:hover {
        background: #0056b3 !important;
    }

    </style>
    """, unsafe_allow_html=True)
    
    # Sidebar menu now includes "Saved Flashcards"
    if "user" not in st.session_state:
        menu = ["Login", "Sign Up"]
    else:
        menu = ["Dashboard", "Flashcards", "Test", "Saved Flashcards", "Community", "Logout"]
    
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
        
        # Test History Graph and Table
        with st.expander("Test History"):
            test_history = analytics.get("test_history", [])
            if test_history:
                df = pd.DataFrame(test_history)
                df["datetime"] = pd.to_datetime(df["date"] + " " + df["time"])
                df = df.sort_values("datetime")
                chart_data = df.set_index("datetime")["score"]
                st.line_chart(chart_data)
                st.table(df[["date", "time", "score"]])
            else:
                st.write("No test history available yet.")
    
    # ---------------------- FLASHCARDS SECTION -----------------------------------
    elif choice == "Flashcards":
        st.title("📖 Flashcard Generator")

        # Initialize session state variables
        if "active_session_id" not in st.session_state:
            st.session_state["active_session_id"] = None
        if "session_flashcards" not in st.session_state:
            st.session_state["session_flashcards"] = []
        if "flashcard_query" not in st.session_state:
            st.session_state["flashcard_query"] = ""
        if "current_flashcard_question" not in st.session_state:
            st.session_state["current_flashcard_question"] = None
        if "current_flashcard_answer" not in st.session_state:
            st.session_state["current_flashcard_answer"] = ""
        if "flashcard_reveal" not in st.session_state:
            st.session_state["flashcard_reveal"] = False
        if "pdf_text" not in st.session_state:
            st.session_state["pdf_text"] = None
        if "pdf_uploaded_once" not in st.session_state:
            st.session_state["pdf_uploaded_once"] = False

        # ---------------------- SESSION MANAGEMENT ----------------------
        st.sidebar.markdown("### 💬 Chat Sessions")

        # Create a new session
        new_session_name = st.sidebar.text_input("New Session Name")
        if st.sidebar.button("Create Session"):
            if new_session_name:
                session_id = create_session(new_session_name)
                st.session_state["active_session_id"] = session_id
                st.session_state["session_flashcards"] = []
                st.session_state.pop("pdf_text", None)
                st.session_state.pop("pdf_uploaded_once", None)
                st.session_state.pop("pdf_uploader", None) # Ensure uploader state is reset
                st.success(f"✅ Session '{new_session_name}' created successfully!")
                st.rerun()
            else:
                st.sidebar.error("⚠️ Please enter a session name.")

        # Fetch existing sessions
        user_id = st.session_state.get("user")
        if user_id:
            sessions = get_sessions(user_id)

            if sessions:
                st.sidebar.markdown("### 📂 Your Sessions")
                session_mapping = {s[1]: s[0] for s in sessions}
                session_names = list(session_mapping.keys())

                # Dropdown for selecting an existing session
                selected_session_name = st.sidebar.selectbox("Select a session", session_names)

                if selected_session_name:
                    selected_session_id = session_mapping[selected_session_name]
                    if st.session_state["active_session_id"] != selected_session_id:
                        st.session_state["active_session_id"] = selected_session_id
                        selected_session_data = next(s for s in sessions if s[0] == selected_session_id)
                        st.session_state["session_flashcards"] = json.loads(selected_session_data[2])
                        st.session_state["pdf_text"] = selected_session_data[3] if selected_session_data[3] else None
                        st.session_state.pop("flashcard_query", None)
                        st.session_state.pop("current_flashcard_question", None)
                        st.session_state.pop("current_flashcard_answer", None)
                        st.session_state.pop("flashcard_reveal", None)
                        st.session_state.pop("pdf_uploaded_once", None)
                        st.session_state.pop("pdf_uploader", None) # Ensure uploader state is reset
                        st.rerun()

        # ---------------------- MAIN FLASHCARD FUNCTIONALITY ----------------------
        if st.session_state["active_session_id"] is None:
            st.info("⚠️ Please create or select a session to continue.")
        else:
            uploaded_file = st.file_uploader("Upload PDF", type="pdf", key="pdf_uploader")

            if uploaded_file is not None:
                if "pdf_text" not in st.session_state or not st.session_state["pdf_text"] or not isinstance(st.session_state["pdf_text"], str) or not st.session_state["pdf_text"].strip():

                    # Extract text only if a new file is uploaded
                    pdf_text = extract_text_from_pdf(uploaded_file)
                    st.session_state["pdf_text"] = pdf_text if isinstance(pdf_text, str) and pdf_text.strip() else ""

                    # Save PDF content to session
                    conn = sqlite3.connect("users.db")
                    c = conn.cursor()
                    c.execute("UPDATE sessions SET pdf_content=? WHERE id=?",
                              (pdf_text, st.session_state["active_session_id"]))
                    conn.commit()
                    conn.close()

                    # Mark as uploaded
                    st.session_state["pdf_uploaded_once"] = True
                    st.session_state["analytics"]["pdfs_uploaded"] += 1
                    update_user_analytics(st.session_state["user"], st.session_state["analytics"])
                    st.rerun()  # Rerun to reflect changes immediately

            # Display warning only if no PDF has been uploaded yet
            if "pdf_text" not in st.session_state or not isinstance(st.session_state["pdf_text"], str) or not st.session_state["pdf_text"].strip():
                st.warning("📂 Please upload a PDF to generate flashcards.")
            else:
                pdf_text = st.session_state["pdf_text"]
                # ---------------------- FLASHCARD INPUT & GENERATION ----------------------
                user_input = st.text_input(
                    "Enter topic/question for flashcards (optional):",
                    value=st.session_state["flashcard_query"],
                    key="flashcard_input"
                )

                # Reset flashcards when input changes
                if user_input.strip() and user_input != st.session_state["flashcard_query"]:
                    st.session_state["flashcard_query"] = user_input
                    st.session_state["current_flashcard_question"] = None
                    st.session_state["current_flashcard_answer"] = ""
                    st.session_state["flashcard_reveal"] = False
                    st.rerun()

                # Ensure a flashcard is generated even if no topic is entered
                if st.session_state["current_flashcard_question"] is None:
                    topic = st.session_state["flashcard_query"] if st.session_state["flashcard_query"].strip() else "general concepts"
                    question = generate_flashcard_question_groq(st.session_state["pdf_text"], topic)

                    st.session_state["current_flashcard_question"] = question
                    st.session_state["current_flashcard_answer"] = ""
                    st.session_state["flashcard_reveal"] = False
                    st.session_state["analytics"]["flashcards_generated"] += 1
                    update_user_analytics(st.session_state["user"], st.session_state["analytics"])

                # ---------------------- DISPLAY FLASHCARD ----------------------
                if st.session_state["current_flashcard_question"]:
                    safe_question = clean_flashcard_text(st.session_state["current_flashcard_question"])

                    with st.container():
                        st.markdown(f"""
                        <div class="flashcard">
                            <p style='text-align:center;margin-top: 1rem;'>
                                <strong>Question:</strong> {safe_question}
                            </p>
                        </div>
                        """, unsafe_allow_html=True)

                    # Reveal Answer
                    if not st.session_state["flashcard_reveal"]:
                        if st.button("Reveal Answer"):
                            answer = generate_flashcard_answer_groq(pdf_text, safe_question)
                            st.session_state["current_flashcard_answer"] = answer
                            st.session_state["flashcard_reveal"] = True
                            st.rerun()
                    else:
                        safe_answer = clean_flashcard_text(st.session_state["current_flashcard_answer"])
                        with st.container():
                            st.markdown(f"""
                            <div class="flashcard">
                                <p style='text-align:center;margin-top: 1rem;'><strong>Answer:</strong> {safe_answer}</p>
                            </div>
                            """, unsafe_allow_html=True)

                        # "Didn't Understand" Button
                        if st.button("Didn't Understand"):
                            simpler_answer = generate_simplified_explanation_groq(pdf_text, safe_answer)
                            st.session_state["current_flashcard_answer"] = simpler_answer
                            st.rerun()

                        # Share Flashcard Option
                        user_communities = get_user_communities(st.session_state["user"])
                        community_names = [community[1] for community in user_communities]

                        if community_names:
                            selected_communities = st.multiselect(
                                "Select Communities to Share Flashcard",
                                community_names,
                                key="share_flashcard_direct"
                            )

                            if st.button("Share Flashcard Without Saving", key="share_flashcard_now"):
                                if not selected_communities:
                                    st.error("Please select at least one community to share the flashcard.")
                                else:
                                    flashcard_data = {
                                        "question": st.session_state["current_flashcard_question"],
                                        "answer": st.session_state["current_flashcard_answer"],
                                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                                    }
                                    shared = False
                                    for community_name in selected_communities:
                                        community_id = next((c[0] for c in user_communities if c[1] == community_name), None)
                                        if community_id:
                                            success = share_flashcard_to_community([community_id], json.dumps(flashcard_data), st.session_state["user"])
                                            if success:
                                                shared = True

                                    if shared:
                                        st.success("Flashcard shared successfully!")
                                        st.session_state["selected_communities"] = set()
                                        st.rerun()
                                    else:
                                        st.error("Failed to share flashcard. Please try again.")
                        else:
                            st.warning("You are not a member of any community. Join one to share flashcards.")

                        # Add flashcard to session and update database
                        if st.button("Add Flashcard to Session"):
                            if not safe_question or not safe_answer:
                                st.error("Invalid flashcard data. Please try again.")
                            else:
                                flashcard_data = {
                                    "question": safe_question,
                                    "answer": safe_answer,
                                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                                }

                                try:
                                    st.session_state.setdefault("session_flashcards",)
                                    st.session_state["session_flashcards"].append(flashcard_data)
                                    update_session_flashcards(st.session_state["active_session_id"],
                                                           st.session_state["session_flashcards"])
                                    st.success("Flashcard added to session.")

                                    # Share flashcard to communities if user is a member of any
                                    user_communities = get_user_communities(st.session_state["user"])
                                    if user_communities:
                                        st.session_state.setdefault("selected_communities", set())
                                        st.write("### Share with Communities")
                                        for community in user_communities:
                                            if st.checkbox(f"Share to {community[1]}", key=f"share_{community[0]}"):
                                                st.session_state["selected_communities"].add(community[0])

                                        if st.session_state["selected_communities"] and st.button("Share to Selected Communities"):
                                            success = share_flashcard_to_community(
                                                list(st.session_state["selected_communities"]),
                                                json.dumps(flashcard_data),
                                                st.session_state["user"]
                                            )
                                            if success:
                                                st.success("Flashcard shared successfully to selected communities!")
                                                st.session_state["selected_communities"].clear()
                                                st.rerun()
                                            else:
                                                st.error("Failed to share flashcard. Please try again.")
                                    else:
                                        st.warning("You are not a member of any community. Join one to share flashcards.")
                                        st.rerun()
                                except Exception as e:
                                    st.error(f"Error saving flashcard: {str(e)}")

                        # "Next Flashcard" Button
                        if st.button("Next Flashcard"):
                            prev_question = st.session_state["current_flashcard_question"]
                            new_question = generate_flashcard_question_groq(pdf_text, user_input, prev_question=prev_question)
                            st.session_state["current_flashcard_question"] = new_question
                            st.session_state["current_flashcard_answer"] = ""
                            st.session_state["flashcard_reveal"] = False
                            st.session_state["analytics"]["flashcards_viewed"] += 1
                            update_user_analytics(st.session_state["user"], st.session_state["analytics"])
                            st.rerun()

                # Display current session flashcards
                if st.session_state["session_flashcards"]:
                    st.markdown("### Current Session Flashcards")
                    st.info(f"Total flashcards in session: {len(st.session_state['session_flashcards'])}")

                    for idx, fc in enumerate(st.session_state["session_flashcards"], start=1):
                        st.markdown(f"""
                        <div style="background:#f8f9fa; padding:10px; border-radius:8px; margin-bottom:8px;">
                            <strong>Flashcard {idx}:</strong><br>
                            <b>Q:</b> {fc.get('question', 'No question')}<br>
                            <b>A:</b> {fc.get('answer', 'No answer')}<br>
                            <small>Saved on: {fc.get('timestamp', 'Unknown date')}</small>
                        </div>
                        """, unsafe_allow_html=True)

                        # Share Flashcard Option for Saved Flashcards
                        user_communities = get_user_communities(st.session_state["user"])
                        community_names = [community[1] for community in user_communities]

                        if community_names:
                            selected_communities = st.multiselect(
                                f"Share Flashcard {idx} with Communities",
                                community_names,
                                key=f"share_flashcard_{idx}"
                            )

                            if st.button(f"Share Flashcard {idx}", key=f"share_button_{idx}"):
                                if not selected_communities:
                                    st.error("Please select at least one community to share the flashcard.")
                                else:
                                    flashcard_data = {
                                        "question": fc.get("question"),
                                        "answer": fc.get("answer"),
                                        "timestamp": fc.get("timestamp")
                                    }
                                    shared = False
                                    for community_name in selected_communities:
                                        community_id = next((c[0] for c in user_communities if c[1] == community_name), None)
                                        if community_id:
                                            success = share_flashcard_to_community([community_id], json.dumps(flashcard_data), st.session_state["user"])
                                            if success:
                                                shared = True

                                    if shared:
                                        st.success(f"Flashcard {idx} shared successfully!")
                                        st.rerun()
                                    else:
                                        st.error(f"Failed to share Flashcard {idx}. Please try again.")

                        else:
                            st.warning("You are not a member of any community. Join one to share flashcards.")

                else:
                    st.info("No flashcards saved in this session yet.")

    # ---------------------- TEST SECTION -----------------------------------
    elif choice == "Test":
        st.title("📝 Knowledge Test")
    
        # Fetch all chat sessions for the user
        sessions = get_sessions(st.session_state["user"])
    
        if not sessions:
            st.warning("No chat sessions found. Please create a flashcard session first.")
        else:
            # Ensure session names and mapping use the same format
            session_names = [f"{s[1]} ({s[4]})" for s in sessions]  # Format: "Session Name (Date)"
            session_mapping = {f"{s[1]} ({s[4]})": s[0] for s in sessions}  # Mapping: {"Session Name (Date)": session_id}
    
            # Display dropdown for selecting a chat session
            selected_session_name = st.selectbox("Select a chat session", session_names)
    
            if selected_session_name not in session_mapping:
                st.error(f"Error: Selected session '{selected_session_name}' not found. Please refresh and try again.")
                st.stop()
    
            # Retrieve the corresponding session ID
            selected_session_id = session_mapping[selected_session_name]
            
            # ✅ Fix: Reset test questions when switching sessions
            if st.session_state.get("active_session_id") != selected_session_id:
                st.session_state["active_session_id"] = selected_session_id
                st.session_state.pop("pdf_text", None)  # Reset PDF when switching sessions
                st.session_state.pop("test_questions", None)  # ✅ Clear test questions for new session

            # ✅ Fix: Clear test questions when user navigates away and comes back
            if "last_visited_section" not in st.session_state:
                st.session_state["last_visited_section"] = "Test"

            if st.session_state["last_visited_section"] != "Test":
                st.session_state.pop("test_questions", None)  # ✅ Clear test questions when returning to Test section
                st.session_state["last_visited_section"] = "Test"    
            
            # Ensure the selected session is active
            if st.session_state.get("active_session_id") != selected_session_id:
                st.session_state["active_session_id"] = selected_session_id
                st.session_state.pop("pdf_text", None)  # Reset PDF when switching sessions
    
            # Load the PDF content for the selected session
            conn = sqlite3.connect("users.db")
            c = conn.cursor()
            c.execute("SELECT pdf_content FROM sessions WHERE id=? AND username=?", 
                      (selected_session_id, st.session_state["user"]))
            session_pdf = c.fetchone()
            conn.close()
    
            if session_pdf and session_pdf[0]:
                st.session_state["pdf_text"] = session_pdf[0]
            else:
                st.session_state["pdf_text"] = None
    
            # Ensure a PDF is available before allowing test generation
            if "pdf_text" not in st.session_state or not st.session_state["pdf_text"]:
                st.info("No PDF found for the selected chat session. Please upload a PDF in the Flashcards section.")
            else:
                # ✅ Fix: Always allow generating a new test after switching sessions
                if st.button("Generate Test Questions"):
                    st.session_state.pop("test_questions", None)  # ✅ Reset test questions when regenerating
                    test_questions = generate_test_questions_groq(st.session_state["pdf_text"])
                    if test_questions:
                        st.session_state["test_questions"] = test_questions
                    else:
                        st.error("Failed to generate test questions. Please try again.")
    
                # Display test questions if they exist
                if "test_questions" in st.session_state:
                    answers = {}
                    wrong_qas = []  # Store incorrectly answered questions
                    for i, q in enumerate(st.session_state["test_questions"]):
                        with st.container():
                            st.subheader(f"Question {i+1}")
                            question_text = clean_flashcard_text(q["question"])
                            options = [clean_flashcard_text(opt) for opt in q["options"]]
                            answers[i] = st.radio(question_text, options, key=f"q_{i}")
    
                    # Submit and score the test
                    if st.button("Submit Test"):
                        score = 0
                        for i, q in enumerate(st.session_state["test_questions"]):
                            correct_answer = clean_flashcard_text(q["correct"])
                            if answers.get(i) == correct_answer:
                                score += 1
                            else:
                                wrong_qas.append({
                                    "question": clean_flashcard_text(q["question"]),
                                    "answer": answers.get(i, "No answer")
                                })
    
                        # Generate insights with wrong answers
                        insights = generate_test_insights_groq(score, wrong_qas)
                        current_date = time.strftime("%Y-%m-%d")
                        current_time = time.strftime("%H:%M:%S")
    
                        # Update analytics
                        st.session_state["analytics"]["tests_taken"] = st.session_state["analytics"].get("tests_taken", 0) + 1
                        st.session_state["analytics"]["last_test_score"] = score
                        st.session_state["analytics"]["test_insights"] = insights
                        st.session_state["analytics"].setdefault("test_history", []).append({
                            "date": current_date,
                            "time": current_time,
                            "score": score
                        })
                        update_user_analytics(st.session_state["user"], st.session_state["analytics"])

                        # Display score and insights
                        st.success(f"Score: {score}/10")
                        with st.expander("Test Insights"):
                            st.write(insights)

                        # Test Review Section
                        st.subheader("Test Review")
                        for i, q in enumerate(st.session_state["test_questions"]):
                            st.write(f"**Question {i+1}:** {clean_flashcard_text(q['question'])}")
                            st.write(f"**Your Answer:** {answers.get(i, 'No answer')}")
                            st.write(f"**Correct Answer:** {clean_flashcard_text(q['correct'])}")
                            if answers.get(i) == clean_flashcard_text(q['correct']):
                                st.success("Correct")
                            else:
                                st.error("Incorrect")
                            st.write("---")

                        # Clear test questions after submission
                        st.session_state.pop("test_questions", None)
    # ---------------------- SAVED FLASHCARDS SECTION -------------------------------
    elif choice == "Saved Flashcards":
        st.title("Saved Flashcard Sessions")
        sessions = get_sessions(st.session_state["user"])
        if sessions:
            for session in sessions:
                session_id, session_name, flashcards_json, pdf_content, created_at = session
                st.markdown(f"**{session_name}** (Created: {created_at})")
                try:
                    flashcards = json.loads(flashcards_json) if flashcards_json else []
                except Exception:
                    flashcards = []
                if flashcards:
                    for idx, fc in enumerate(flashcards, start=1):
                        st.write(f"**Flashcard {idx}:**")
                        st.write(f"Q: {fc.get('question', '')}")
                        st.write(f"A: {fc.get('answer', '')}")
                        st.write(f"Saved on: {fc.get('timestamp', '')}")
                        st.write("---")
                if st.button("Delete Session", key=f"delete_session_{session_id}"):
                    delete_session(session_id)
                    st.success("Session deleted.")
                    st.rerun()
        else:
            st.info("No saved flashcard sessions available.")

# ---------------------- COMMUNITY SECTION -------------------------------------
    elif choice == "Community":
        st.title("Community Management")

        # ✅ Fetch all communities the user is part of
        user_communities = get_user_communities(st.session_state["user"])
        selected_community_id = None  # Initialize with None

        # ✅ NEW: Fetch all available communities (including ones user hasn't joined)
        conn = sqlite3.connect("users.db")
        c = conn.cursor()
        c.execute("SELECT id, name FROM communities")  # Fetch all communities
        all_communities = c.fetchall()
        conn.close()

        # ✅ NEW: Filter out already joined communities
        joined_community_ids = {c[0] for c in user_communities}  # Get IDs of joined communities
        available_communities = [(c[0], c[1]) for c in all_communities if c[0] not in joined_community_ids]

        # ---------------------- Create Community Section ----------------------
        with st.expander("Create Community", expanded=False):
            community_name = st.text_input("Community Name")
            community_description = st.text_area("Description (optional)")
            if st.button("Create Community"):
                if not community_name:
                    st.error("Community name is required")
                    return
                new_community_id = create_community(community_name, community_description)
                if new_community_id:
                    st.success(f"Community '{community_name}' created successfully! ")
                    st.session_state['refresh'] = True  # ✅ Refresh session after creating
                    st.rerun()

        # ---------------------- Search & Join Community Section ----------------------
        st.subheader("Join a Community")

        # ✅ NEW: Show dropdown of available communities to join
        if available_communities:
            community_options = {c[1]: c[0] for c in available_communities}  # Mapping of {name: id}
            selected_join_community = st.selectbox("Available Communities", list(community_options.keys()))

            if st.button("Join Community"):
                community_id_to_join = community_options[selected_join_community]
                join_community(community_id_to_join, st.session_state["user"])
                st.success(f"Joined '{selected_join_community}' successfully!")
                st.session_state['refresh'] = True  # ✅ Refresh session after joining
                st.rerun()
        else:
            st.info("No new communities available to join.")

        # ---------------------- If User Has Communities ----------------------
        if user_communities:
            # Extract community names
            community_names = [community[1] for community in user_communities]

            # Select a community for viewing
            selected_community_name = st.selectbox("Select Community", community_names, key="selected_community")

            # Find the corresponding community ID
            selected_community_id = next((c[0] for c in user_communities if c[1] == selected_community_name), None)

            if selected_community_id is None:
                st.error("Selected community not found")
                return

            # ✅ Check if the user is the creator of the community
            conn = sqlite3.connect("users.db")
            c = conn.cursor()
            c.execute("SELECT id FROM communities WHERE id=? AND id IN (SELECT community_id FROM community_members WHERE username=?)",
                    (selected_community_id, st.session_state["user"]))
            is_creator = c.fetchone()
            conn.close()

            # ✅ NEW: Show Leave and Delete buttons immediately after selection
            col1, col2 = st.columns(2)

            with col1:
                if st.button("Leave Community", key="leave_community"):
                    if selected_community_id is not None:
                        success = leave_selected_community(selected_community_id, st.session_state["user"])
                        if success:
                            st.success(f"Left community '{selected_community_name}' successfully!")
                            st.session_state['refresh'] = True  # ✅ Refresh session after leaving
                            st.rerun()
                        else:
                            st.error("Failed to leave the community.")

            with col2:
                if is_creator:
                    if st.button("Delete Community", key="delete_community"):
                        delete_community(selected_community_id)
                        st.success(f"Community '{selected_community_name}' deleted successfully!")
                        st.session_state['refresh'] = True  # ✅ Refresh session after deletion
                        st.rerun()
                else:
                    st.warning("You cannot delete this community as you are not the creator.")

            # ---------------------- Show Shared Flashcards ----------------------
            conn = sqlite3.connect("users.db")
            c = conn.cursor()
            c.execute("SELECT * FROM community_flashcards WHERE community_id=?", (selected_community_id,))
            shared_flashcards = c.fetchall()
            conn.close()

            st.subheader(f"Flashcards in {selected_community_name}")
            if shared_flashcards:
                for flashcard in shared_flashcards:
                    try:
                        # ✅ Parse JSON data from the database
                        flashcard_data = json.loads(flashcard[2])

                        question = flashcard_data.get("question", "No question available")
                        answer = flashcard_data.get("answer", "No answer available")
                        timestamp = flashcard_data.get("timestamp", "Unknown date")

                        # ✅ Display Flashcard UI
                        with st.container():
                            st.markdown(f"""
                            <div style="
                                background-color: #f8f9fa;
                                border: 1px solid #dee2e6;
                                border-radius: 10px;
                                padding: 15px;
                                margin: 10px 0;
                                box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.1);
                            ">
                                <p style='color: #343a40; font-size: 16px;'><strong>Question:</strong> {question}</p>
                            </div>
                            """, unsafe_allow_html=True)

                            # ✅ Show Answer Toggle
                            if st.button(f"Show Answer", key=f"show_answer_{flashcard[0]}"):
                                st.markdown(f"""
                                <div style="
                                    background-color: #e3f2fd;
                                    border: 1px solid #90caf9;
                                    border-radius: 10px;
                                    padding: 15px;
                                    margin-top: 5px;
                                ">
                                    <p style='color: #1e88e5; font-size: 16px;'><strong>Answer:</strong> {answer}</p>
                                </div>
                                """, unsafe_allow_html=True)

                            st.caption(f"Shared by: {flashcard[3]} on {timestamp}")

                    except json.JSONDecodeError:
                        st.error("Error displaying flashcard. Invalid data format.")
            else:
                st.info("No flashcards have been shared yet in this community.")

        else:
            st.info("You are currently not a member of any communities. Create one or search for existing communities to join!")

        # ✅ Ensure instant UI updates
        if 'refresh' in st.session_state:
            del st.session_state['refresh']
            st.rerun()

if __name__ == "__main__":
    main()
