import json
import sqlite3
from datetime import datetime
from groq import Groq
import streamlit as st

# =========================================================
# 1. SETUP & MODERN CLEAN STYLING
# =========================================================
st.set_page_config(
    page_title="AI Code Studio",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    /* Clean, modern aesthetic */
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    .header-box {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #1e293b;
        padding: 16px 22px;
        border-radius: 12px;
        margin-bottom: 18px;
        border: 1px solid #334155;
    }
    .badge-v {
        background: #10b981;
        color: white;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 0.85rem;
    }
    .stButton > button { border-radius: 8px; font-weight: 600; }
</style>
""",
    unsafe_allow_html=True,
)

if "GROQ_API_KEY" not in st.secrets:
    st.error(
        "⚠️ **GROQ_API_KEY missing!** Add it to `.streamlit/secrets.toml`."
    )
    st.stop()

GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
DB_FILE = "code_studio.db"


# =========================================================
# 2. DYNAMIC MODEL RESOLVER
# =========================================================
@st.cache_resource
def get_best_groq_model():
    client = Groq(api_key=GROQ_API_KEY)
    try:
        models = [m.id for m in client.models.list().data]
        priority = [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.8-27b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ]
        for candidate in priority:
            if candidate in models:
                return candidate
        for m in models:
            if not any(
                x in m.lower() for x in ["whisper", "guard", "audio", "embed"]
            ):
                return m
        return models[0]
    except Exception:
        return "openai/gpt-oss-120b"


GROQ_MODEL = get_best_groq_model()


# =========================================================
# 3. DATABASE (SQLite)
# =========================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            version_num INTEGER,
            code TEXT,
            change_note TEXT,
            summary TEXT,
            created_at TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    """)
    conn.commit()
    conn.close()


init_db()


def parse_files(raw_str):
    try:
        data = json.loads(raw_str)
        if isinstance(data, dict) and "app.py" in data:
            return data
    except Exception:
        pass
    return {"app.py": raw_str, "requirements.txt": "streamlit\ngroq\n"}


def get_projects():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id, name FROM projects ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return rows


def create_project(name, files_dict, note="Initial Code"):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO projects (name, created_at) VALUES (?, ?)", (name, now)
    )
    p_id = c.lastrowid
    c.execute(
        """
        INSERT INTO versions (project_id, version_num, code, change_note, summary, created_at)
        VALUES (?, 1, ?, ?, 'Initial project setup ready.', ?)
    """,
        (p_id, json.dumps(files_dict), note, now),
    )
    conn.commit()
    conn.close()
    return p_id


def save_version(p_id, files_dict, note, summary="Updated successfully."):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT MAX(version_num) FROM versions WHERE project_id = ?", (p_id,)
    )
    last_v = c.fetchone()[0] or 0
    new_v = last_v + 1
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        """
        INSERT INTO versions (project_id, version_num, code, change_note, summary, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (p_id, new_v, json.dumps(files_dict), note, summary, now),
    )
    conn.commit()
    conn.close()


def get_versions(p_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        SELECT version_num, change_note, created_at, code, summary 
        FROM versions WHERE project_id = ? ORDER BY version_num DESC
    """,
        (p_id,),
    )
    rows = c.fetchall()
    conn.close()
    return rows


def delete_project(p_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM versions WHERE project_id = ?", (p_id,))
    c.execute("DELETE FROM projects WHERE id = ?", (p_id,))
    conn.commit()
    conn.close()


# =========================================================
# 4. GROQ API ENGINE
# =========================================================
def call_groq(system_prompt, user_prompt):
    client = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())


# =========================================================
# 5. SIDEBAR: CLEAN & MINIMAL CONTROLS
# =========================================================
all_projects = get_projects()

with st.sidebar:
    st.title("⚡ AI Code Studio")
    st.caption(f"Engine: `{GROQ_MODEL}`")
    st.divider()

    # Project selection or Creation
    if all_projects:
        p_dict = {name: pid for pid, name in all_projects}
        selected_p_name = st.selectbox(
            "📁 Active Project", list(p_dict.keys())
        )
        current_p_id = p_dict[selected_p_name]

        # Version Rollback
        versions = get_versions(current_p_id)
        current_v = versions[0]
        active_files = parse_files(current_v[3])
        active_v_num = current_v[0]

        st.subheader("⏪ Rollback History")
        version_names = [f"v{v[0]}: {v[1]} ({v[2]})" for v in versions]
        chosen_v_str = st.selectbox("Restore Past Version", version_names)
        chosen_v_num = int(chosen_v_str.split(":")[0].replace("v", ""))

        if chosen_v_num != active_v_num:
            if st.button("⏮️ Rollback to this Version", use_container_width=True):
                target_v = [v for v in versions if v[0] == chosen_v_num][0]
                save_version(
                    current_p_id,
                    parse_files(target_v[3]),
                    f"Rollback to v{chosen_v_num}",
                    f"Restored code from version {chosen_v_num}.",
                )
                st.success(f"Restored to v{chosen_v_num}!")
                st.rerun()

        st.divider()
        # Delete Project (clean, direct confirmation)
        with st.expander("🗑️ Delete this Project"):
            st.warning(f"Delete **{selected_p_name}** and all its history?")
            if st.button(
                "Yes, Delete Forever", type="primary", use_container_width=True
            ):
                delete_project(current_p_id)
                st.rerun()
    else:
        selected_p_name = None
        current_p_id = None
        current_v = None

    if st.button("➕ Start New Project", use_container_width=True):
        st.session_state["show_new"] = True
        st.rerun()


# =========================================================
# 6. SIMPLE CREATION VIEW (IF NO PROJECT OR "NEW" CLICKED)
# =========================================================
if not all_projects or st.session_state.get("show_new", False):
    st.subheader("🚀 Create a Project")

    col_a, col_b = st.columns([1, 1])
    with col_a:
        new_name = st.text_input(
            "Project Name", placeholder="e.g., My-Dashboard"
        )
        creation_type = st.radio(
            "How do you want to start?",
            [
                "✨ AI Builds from Scratch (Prompt)",
                "📋 Paste Existing Code",
            ],
        )

    with col_b:
        if creation_type == "✨ AI Builds from Scratch (Prompt)":
            new_prompt = st.text_area(
                "Describe what to build:",
                height=160,
                placeholder="e.g., Build a modern Streamlit expense tracker with charts, monthly summary, and category filters...",
            )
            if st.button("⚡ Generate Website", type="primary"):
                if new_name.strip() and new_prompt.strip():
                    with st.spinner("Building your project files..."):
                        sys_p = """
                        You are an expert developer. Generate a complete Streamlit app.
                        Return JSON:
                        {
                            "files": {
                                "app.py": "100% complete Python code without omissions",
                                "requirements.txt": "pip package names, one per line"
                            },
                            "summary": "Short summary of generated app"
                        }
                        """
                        try:
                            res = call_groq(sys_p, new_prompt)
                            create_project(
                                new_name.strip(),
                                res.get("files", {}),
                                "Initial Build",
                            )
                            st.session_state["show_new"] = False
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                else:
                    st.warning("Please provide both name and prompt.")
        else:
            pasted_app = st.text_area(
                "Paste your code (app.py):", height=160
            )
            if st.button("💾 Save Project", type="primary"):
                if new_name.strip() and pasted_app.strip():
                    create_project(
                        new_name.strip(),
                        {
                            "app.py": pasted_app,
                            "requirements.txt": "streamlit\n",
                        },
                        "Imported Code",
                    )
                    st.session_state["show_new"] = False
                    st.rerun()
                else:
                    st.warning("Please provide name and code.")

    if all_projects and st.button("Cancel"):
        st.session_state["show_new"] = False
        st.rerun()

    st.stop()


# =========================================================
# 7. MAIN WORKSPACE: CLEAN, SIMPLE & SPACIOUS
# =========================================================
# Top Header Banner
st.markdown(
    f"""
<div class="header-box">
    <div>
        <span style="font-size: 1.4rem; font-weight: 800; color: #f8fafc;">📁 {selected_p_name}</span>
        <span style="margin-left: 10px;" class="badge-v">v{active_v_num}</span>
    </div>
    <div style="color: #94a3b8; font-size: 0.9rem;">
        Note: {current_v[1]} ({current_v[2]})
    </div>
</div>
""",
    unsafe_allow_html=True,
)

# Single Unified Input Box for Changes AND Errors
st.markdown("#### 💬 What do you want to change or fix?")
col_in, col_btn = st.columns([5, 1])

with col_in:
    user_instruction = st.text_area(
        "Enter instructions or paste terminal/Streamlit error here:",
        height=90,
        placeholder="Type any change (e.g. 'Add dark mode toggle and download button') OR paste any red error traceback...",
        label_visibility="collapsed",
    )

with col_btn:
    st.write("")  # alignment spacer
    run_action = st.button(
        "🚀 Update Code", type="primary", use_container_width=True
    )

# Execution Logic
if run_action:
    if not user_instruction.strip():
        st.warning("Please type an instruction or paste an error first.")
    else:
        with st.spinner("Updating files..."):
            sys_prompt = """
            You are a senior software engineer.
            Given current files (app.py, requirements.txt) and user instructions (or error traceback):
            1. Apply the modification or fix the error completely.
            2. Add any new pip dependencies needed to requirements.txt.
            
            Return JSON:
            {
                "files": {
                    "app.py": "Complete updated Python script without abbreviations or placeholders",
                    "requirements.txt": "Full pip package list, one per line"
                },
                "summary": "1-2 sentence explanation of what was changed or fixed"
            }
            """
            user_prompt = f"""
            --- CURRENT app.py ---
            {active_files.get('app.py', '')}
            
            --- CURRENT requirements.txt ---
            {active_files.get('requirements.txt', '')}
            
            --- USER REQUEST / ERROR LOG ---
            {user_instruction}
            """
            try:
                res = call_groq(sys_prompt, user_prompt)
                new_files = res.get("files", active_files)
                summary_text = res.get("summary", "Updated.")

                save_version(
                    current_p_id,
                    new_files,
                    user_instruction[:35],
                    summary_text,
                )
                st.success("✅ Code successfully updated!")
                st.rerun()
            except Exception as e:
                st.error(f"Error updating: {e}")

st.divider()

# =========================================================
# 8. TWO SEPARATED FILES (READY TO COPY)
# =========================================================
tab_app, tab_req, tab_summary = st.tabs([
    "📄 app.py (Full Script)",
    "📦 requirements.txt (Dependencies)",
    "📝 What Changed?",
])

with tab_app:
    c_info, c_dl = st.columns([4, 1])
    with c_info:
        st.caption(
            "👉 **For GitHub:** Hover over the top-right corner of the code box below and click the **Copy icon**."
        )
    with c_dl:
        st.download_button(
            "📥 Download app.py",
            active_files.get("app.py", ""),
            file_name="app.py",
            mime="text/x-python",
            use_container_width=True,
        )
    st.code(active_files.get("app.py", ""), language="python")

with tab_req:
    c_info2, c_dl2 = st.columns([4, 1])
    with c_info2:
        st.caption(
            "👉 **For GitHub:** Click the **Copy icon** below. It contains **ONLY** pip packages."
        )
    with c_dl2:
        st.download_button(
            "📥 Download requirements.txt",
            active_files.get("requirements.txt", ""),
            file_name="requirements.txt",
            mime="text/plain",
            use_container_width=True,
        )
    st.code(active_files.get("requirements.txt", ""), language="text")

with tab_summary:
    st.markdown("### 📋 Latest Version Summary")
    st.write(current_v[4])
    st.markdown(f"**Triggered by:** `{current_v[1]}`")
    st.markdown(f"**Saved on:** `{current_v[2]}`")
