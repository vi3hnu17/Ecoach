import os
import csv
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import streamlit as st
import google.generativeai as genai


# =========================================================
# Page config
# =========================================================
st.set_page_config(
    page_title="Ecoach",
    layout="centered",
)

st.markdown("## Ecoach")

# =========================================================
# Paths / storage setup
# =========================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "study_data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "study_chat.db"
CSV_PATH = DATA_DIR / "study_chat_export.csv"


# =========================================================
# API key / Gemini setup
# =========================================================
def load_api_key() -> str | None:
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        try:
            api_key = st.secrets["GEMINI_API_KEY"]
        except Exception:
            api_key = None

    return api_key


api_key = load_api_key()

if api_key:
    genai.configure(api_key=api_key)

model = genai.GenerativeModel("gemini-2.5-pro") if api_key else None


# =========================================================
# Database helpers
# =========================================================
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


conn = get_connection()


def init_database() -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            user_id TEXT NOT NULL,
            mode_symbol TEXT NOT NULL,
            mode_name TEXT NOT NULL,
            role TEXT NOT NULL,
            message TEXT NOT NULL,
            squat_reps INTEGER NOT NULL,
            event_type TEXT NOT NULL
        )
        """
    )
    conn.commit()


init_database()


# =========================================================
# Session state
# =========================================================
def init_session_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "user_id" not in st.session_state:
        st.session_state.user_id = ""

    if "mode_symbol" not in st.session_state:
        st.session_state.mode_symbol = "◌"

    if "squat_session_active" not in st.session_state:
        st.session_state.squat_session_active = False

    if "squat_reps" not in st.session_state:
        st.session_state.squat_reps = 0

    if "squat_last_message" not in st.session_state:
        st.session_state.squat_last_message = "Ready when you are."


init_session_state()


# =========================================================
# Mode helpers
# =========================================================
def resolve_mode(symbol: str) -> str:
    return "generic" if symbol == "◌" else "adaptive"


# =========================================================
# Logging helpers
# =========================================================
def current_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_event(role: str, message: str, event_type: str) -> None:
    user_id = st.session_state.user_id.strip() or "anonymous"
    mode_symbol = st.session_state.mode_symbol
    mode_name = resolve_mode(mode_symbol)
    squat_reps = st.session_state.squat_reps

    conn.execute(
        """
        INSERT INTO chat_logs (
            timestamp, user_id, mode_symbol, mode_name, role, message, squat_reps, event_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            current_timestamp(),
            user_id,
            mode_symbol,
            mode_name,
            role,
            message,
            squat_reps,
            event_type,
        ),
    )
    conn.commit()


def export_db_to_csv() -> None:
    rows = conn.execute(
        """
        SELECT timestamp, user_id, mode_symbol, mode_name, role, message, squat_reps, event_type
        FROM chat_logs
        ORDER BY id ASC
        """
    ).fetchall()

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp",
            "user_id",
            "mode_symbol",
            "mode_name",
            "role",
            "message",
            "squat_reps",
            "event_type",
        ])
        for row in rows:
            writer.writerow([
                row["timestamp"],
                row["user_id"],
                row["mode_symbol"],
                row["mode_name"],
                row["role"],
                row["message"],
                row["squat_reps"],
                row["event_type"],
            ])


# =========================================================
# Prompt builders
# =========================================================
def build_generic_prompt(user_id: str) -> str:
    return f"""
You are an encouraging AI fitness coach.

Context:
- User ID: {user_id or 'Not provided'}
- Chat mode: generic

Behavior rules:
- Give broad, practical, safe fitness advice.
- Keep responses clear, concise, and supportive.
- Do not personalize using assumptions about the user.
- If the user asks about squats, encourage them briefly and clearly.
- If the user mentions pain, injury, chest pain, fainting, or severe dizziness, advise professional medical guidance.
- Maintain continuity using the previous conversation.
""".strip()


def build_adaptive_prompt(user_id: str, chat_history: List[Dict]) -> str:
    prior_user_messages = [m["content"] for m in chat_history if m.get("role") == "user"]
    prior_context = "\n".join(f"- {msg}" for msg in prior_user_messages[-8:]) or "- No prior user context yet"

    return f"""
You are an encouraging AI fitness coach.

Context:
- User ID: {user_id or 'Not provided'}
- Chat mode: adaptive

Known user context from this conversation:
{prior_context}

Behavior rules:
- Adapt your responses using only information the user has shared in this conversation.
- Be supportive, practical, and concise.
- If the user asks about squats, encourage them briefly and clearly.
- If the user mentions pain, injury, chest pain, fainting, or severe dizziness, advise professional medical guidance.
- Maintain continuity using the previous conversation.
""".strip()


def format_chat_history(chat_history: List[Dict]) -> str:
    if not chat_history:
        return "No previous conversation."

    lines = []
    for msg in chat_history:
        role = msg.get("role", "user").capitalize()
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")

    return "\n".join(lines)


# =========================================================
# Gemini response
# =========================================================
def generate_response(user_message: str, mode: str, user_id: str, chat_history: List[Dict]) -> str:
    if model is None:
        return (
            "GEMINI_API_KEY is missing. Add it as an environment variable "
            "or in Streamlit secrets."
        )

    system_prompt = (
        build_generic_prompt(user_id)
        if mode == "generic"
        else build_adaptive_prompt(user_id, chat_history)
    )

    prompt = f"""
{system_prompt}

Previous conversation:
{format_chat_history(chat_history)}

User:
{user_message}

Assistant:
""".strip()

    try:
        response = model.generate_content(prompt)
        return response.text if getattr(response, "text", None) else "I could not generate a response."
    except Exception as e:
        return f"Gemini API error: {e}"


# =========================================================
# Squat motivation
# =========================================================
SQUAT_MESSAGES = [
    "Great rep. Keep going!",
    "Nice squat. Stay strong!",
    "Excellent. Drive up!",
    "Good control. One more!",
    "Strong rep. Keep breathing!",
    "Nice work. Stay steady!",
    "Great job. Keep pushing!",
    "Solid rep. You’ve got this!",
]


def get_squat_message(rep_number: int) -> str:
    return f"Rep {rep_number}: {SQUAT_MESSAGES[(rep_number - 1) % len(SQUAT_MESSAGES)]}"


def add_squat_rep() -> None:
    st.session_state.squat_reps += 1
    message = get_squat_message(st.session_state.squat_reps)
    st.session_state.squat_last_message = message
    stored_message = f"🏋️ {message}"
    st.session_state.messages.append({"role": "assistant", "content": stored_message})
    log_event(role="assistant", message=stored_message, event_type="squat_rep")


# =========================================================
# Sidebar
# =========================================================
with st.sidebar:
    chosen_symbol = st.radio(
        label="",
        options=["◌", "✦"],
        index=0 if st.session_state.mode_symbol == "◌" else 1,
        horizontal=True,
        label_visibility="collapsed",
    )

    if chosen_symbol != st.session_state.mode_symbol:
        st.session_state.mode_symbol = chosen_symbol
        st.session_state.messages = []
        st.session_state.squat_reps = 0
        st.session_state.squat_last_message = "Ready when you are."
        st.session_state.squat_session_active = False
        log_event(role="system", message=f"Mode changed to {chosen_symbol}", event_type="mode_change")

    st.text_input("User ID", key="user_id")

    st.divider()
    st.subheader("Squat Coach")

    if st.button("Start", use_container_width=True):
        st.session_state.squat_session_active = True
        st.session_state.squat_reps = 0
        st.session_state.squat_last_message = "Session started. Let’s go!"
        start_message = "🏋️ Session started. Let’s go!"
        st.session_state.messages.append({"role": "assistant", "content": start_message})
        log_event(role="assistant", message=start_message, event_type="squat_start")

    if st.button("Rep +1", use_container_width=True, disabled=not st.session_state.squat_session_active):
        add_squat_rep()

    if st.button("Stop", use_container_width=True):
        st.session_state.squat_session_active = False
        st.session_state.squat_last_message = "Session ended. Nice work!"
        stop_message = "🏋️ Session ended. Nice work!"
        st.session_state.messages.append({"role": "assistant", "content": stop_message})
        log_event(role="assistant", message=stop_message, event_type="squat_stop")

    st.divider()

    if st.button("Export CSV", use_container_width=True):
        export_db_to_csv()
        st.success(f"CSV exported to {CSV_PATH.name}")

    if st.button("Clear Conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.squat_reps = 0
        st.session_state.squat_last_message = "Ready when you are."
        st.session_state.squat_session_active = False
        log_event(role="system", message="Conversation cleared", event_type="clear_conversation")
        st.success("Conversation cleared.")


# =========================================================
# Main UI
# =========================================================
st.title("Ecoach")
st.caption("")

if model is None:
    st.warning("Set GEMINI_API_KEY in your environment or Streamlit secrets to enable responses.")

mode = resolve_mode(st.session_state.mode_symbol)

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("User ID", st.session_state.user_id or "Not set")
with col2:
    st.metric("Squat Reps", st.session_state.squat_reps)
with col3:
    st.metric("Session", "On" if st.session_state.squat_session_active else "Off")

if st.session_state.squat_session_active:
    st.success(st.session_state.squat_last_message)
else:
    st.info("Start a squat session to receive motivational feedback every repetition.")

st.subheader("Chat")

if not st.session_state.messages:
    with st.chat_message("assistant"):
        st.markdown("Hi! I’m your AI fitness coach. Ask me anything about exercise, squats, recovery, or nutrition.")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

user_input = st.chat_input("Ask your fitness question...")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    log_event(role="user", message=user_input, event_type="chat")

    with st.chat_message("user"):
        st.markdown(user_input)

    reply = generate_response(
        user_message=user_input,
        mode=mode,
        user_id=st.session_state.user_id,
        chat_history=st.session_state.messages[:-1],
    )

    st.session_state.messages.append({"role": "assistant", "content": reply})
    log_event(role="assistant", message=reply, event_type="chat")

    with st.chat_message("assistant"):
        st.markdown(reply)


# =========================================================
# Research/debug view
# =========================================================
with st.expander("Research View", expanded=False):
    st.write(f"Database file: {DB_PATH}")
    st.write(f"CSV export file: {CSV_PATH}")
    st.write(f"Stored messages in current session: {len(st.session_state.messages)}")
    st.json(st.session_state.messages)

    total_rows = conn.execute("SELECT COUNT(*) AS count FROM chat_logs").fetchone()["count"]
    st.write(f"Total logged rows in database: {total_rows}")

    recent_rows = conn.execute(
        """
        SELECT timestamp, user_id, mode_symbol, role, message, squat_reps, event_type
        FROM chat_logs
        ORDER BY id DESC
        LIMIT 10
        """
    ).fetchall()

    st.write("Recent stored records:")
    st.dataframe([dict(row) for row in recent_rows], use_container_width=True)