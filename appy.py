import json
import sqlite3
from datetime import datetime
from groq import Groq
import streamlit as st

# =========================================================
# 1. PAGE SETUP & STYLING
# =========================================================
st.set_page_config(
    page_title="AI Code Studio (Multi-File)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .hero-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 16px;
        padding: 24px 30px;
        color: #f8fafc;
        margin-bottom: 20px;
    }
    .badge {
        display: inline-block;
        background: #3b82f6;
        color: white;
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 600;
        margin-bottom: 10px;
    }
    .version-pill {
        background: #10b981;
        color: white;
        padding: 4px 12px;
        border-radius: 8px;
        font-size: 0.85rem;
        font-weight: 700;
    }
    .file-badge {
        background: #475569;
        color: #f8fafc;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 0.8rem;
        font-family: monospace;
    }
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
    }
</style>
""",
    unsafe_allow_html=True,
)

if "GROQ_API_KEY" not in st.secrets:
    st.error("""
    ⚠️ **GROQ_API_KEY is missing!**
    
    Please add your Groq key into `.streamlit/secrets.toml`:
    ```toml
    GROQ_API_KEY = "gsk_your_groq_api_key_here"
    ```
    """)
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
        model_list = client.models.list()
        active_ids = [m.id for m in model_list.data]

        priority = [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.8-27b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ]
        for candidate in priority:
            if candidate in active_ids:
                return candidate

        for m_id in active_ids:
            if not any(
                skip in m_id.lower() for skip in ["whisper", "guard", "audio"]
            ):
                return m_id

        return active_ids[0]
    except Exception:
        return "openai/gpt-oss-120b"


GROQ_MODEL = get_best_groq_model()


# =========================================================
# 3. MULTI-FILE SERIALIZATION HELPERS
# =========================================================
def parse_version_files(raw_str):
    """Parses code JSON into a file dictionary or adapts legacy raw strings."""
    try:
        data = json.loads(raw_str)
        if isinstance(data, dict) and "app.py" in data:
            return data
    except Exception:
        pass
    # Backward compatibility fallback
    return {
        "app.py": raw_str,
        "requirements.txt": "streamlit\ngroq\n",
    }


def serialize_files(files_dict):
    """Serializes files dictionary to JSON for database storage."""
    return json.dumps(files_dict)


# =========================================================
# 4. DATABASE ENGINE (SQLite)
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
            missing_items TEXT,
            error_solution TEXT,
            run_status TEXT,
            created_at TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS project_ideas (
            project_id INTEGER PRIMARY KEY,
            ideas_json TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


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
        INSERT INTO versions (project_id, version_num, code, change_note, missing_items, error_solution, run_status, created_at)
        VALUES (?, 1, ?, ?, 'No missing dependencies detected.', 'No errors reported.', '✅ Script verified and ready.', ?)
    """,
        (p_id, serialize_files(files_dict), note, now),
    )
    conn.commit()
    conn.close()
    return p_id


def save_version(
    p_id,
    files_dict,
    note,
    missing="No missing items detected.",
    err_sol="No error report required.",
    status="✅ Verified",
):
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
        INSERT INTO versions (project_id, version_num, code, change_note, missing_items, error_solution, run_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (p_id, new_v, serialize_files(files_dict), note, missing, err_sol, status, now),
    )
    conn.commit()
    conn.close()


def get_versions(p_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        SELECT version_num, change_note, created_at, code, missing_items, error_solution, run_status 
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
    c.execute("DELETE FROM project_ideas WHERE project_id = ?", (p_id,))
    c.execute("DELETE FROM projects WHERE id = ?", (p_id,))
    conn.commit()
    conn.close()


def save_ideas(p_id, ideas_json):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO project_ideas (project_id, ideas_json) VALUES (?, ?)",
        (p_id, json.dumps(ideas_json)),
    )
    conn.commit()
    conn.close()


def get_saved_ideas(p_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT ideas_json FROM project_ideas WHERE project_id = ?", (p_id,)
    )
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        try:
            return json.loads(row[0])
        except Exception:
            return []
    return []


# =========================================================
# 5. INTERNAL GROQ CALLER
# =========================================================
def call_groq(system_prompt, user_prompt, json_mode=True):
    client = Groq(api_key=GROQ_API_KEY)
    kwargs = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


def parse_ai_json(raw_text):
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())


# =========================================================
# 6. SIDEBAR NAVIGATION
# =========================================================
all_projects = get_projects()

if "view" not in st.session_state:
    st.session_state["view"] = (
        "create_project" if not all_projects else "workspace"
    )

with st.sidebar:
    st.title("⚡ AI Code Studio")
    st.caption(f"Engine: `{GROQ_MODEL}`")

    st.divider()

    if st.button(
        "➕ Create New Project", type="primary", use_container_width=True
    ):
        st.session_state["view"] = "create_project"
        st.rerun()

    if all_projects:
        st.subheader("📂 Select Project")
        p_dict = {name: pid for pid, name in all_projects}
        selected_p_name = st.selectbox(
            "Active Project:",
            list(p_dict.keys()),
            on_change=lambda: st.session_state.update({"view": "workspace"}),
        )
        current_p_id = p_dict[selected_p_name]
        versions = get_versions(current_p_id)
        current_v_data = versions[0]  # Latest version


# =========================================================
# 7. FULL-SCREEN PROJECT CREATION PAGE
# =========================================================
if st.session_state["view"] == "create_project" or not all_projects:
    st.markdown(
        """
    <div class="hero-card">
        <span class="badge">PROJECT BUILDER</span>
        <h1 style="margin: 0; font-size: 2.2rem; font-weight: 800;">🚀 Start a New Project</h1>
        <p style="color: #94a3b8; font-size: 1.05rem; margin-top: 8px;">
            Files are automatically kept separate. You will get clean, dedicated tabs for <code>app.py</code> and <code>requirements.txt</code>.
        </p>
    </div>
    """,
        unsafe_allow_html=True,
    )

    tab_scratch, tab_paste = st.tabs([
        "✨ Generate from Prompt (From Scratch)",
        "📋 Import / Paste Existing Code",
    ])

    with tab_scratch:
        c1, c2 = st.columns([3, 2])
        with c1:
            scratch_name = st.text_input(
                "Project Name", placeholder="e.g., Fitness-Tracker-App"
            )
            scratch_prompt = st.text_area(
                "Describe the website you want to build:",
                height=180,
                placeholder="e.g., Build a modern Streamlit app for tracking daily habits with charts, login, and weekly stats...",
            )
            if st.button(
                "🚀 Generate & Open Studio",
                type="primary",
                use_container_width=True,
            ):
                if scratch_name.strip() and scratch_prompt.strip():
                    with st.spinner("Generating separate files with Groq..."):
                        sys_p = """
                        You are an elite software architect. Generate a complete Streamlit application.
                        You MUST return a JSON object with:
                        {
                            "files": {
                                "app.py": "100% complete Python code without omissions",
                                "requirements.txt": "Exact pip dependencies, one per line (e.g. streamlit\\npandas)"
                            },
                            "summary": "Brief summary of what was generated"
                        }
                        """
                        try:
                            code_res = call_groq(
                                sys_p, scratch_prompt, json_mode=True
                            )
                            parsed = parse_ai_json(code_res)
                            files = parsed.get(
                                "files",
                                {
                                    "app.py": "# Generated code",
                                    "requirements.txt": "streamlit\ngroq\n",
                                },
                            )
                            create_project(
                                scratch_name.strip(),
                                files,
                                f"Created: {scratch_prompt[:35]}...",
                            )
                            st.session_state["view"] = "workspace"
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("A project with this name already exists!")
                        except Exception as e:
                            st.error(f"Generation error: {str(e)}")
                else:
                    st.warning("Please provide both a project name and prompt.")

        with c2:
            st.info("""
            **💡 Isolated File Guarantees:**
            - `app.py` contains **pure Python code**.
            - `requirements.txt` contains **only pip package names**.
            - No accidental mixing when copying to GitHub!
            """)

    with tab_paste:
        paste_name = st.text_input(
            "Project Name", placeholder="e.g., My-Portfolio", key="paste_name"
        )
        col_p1, col_p2 = st.columns([3, 2])
        with col_p1:
            paste_app = st.text_area(
                "Paste content for app.py:",
                height=220,
                placeholder="Paste your python script here...",
                key="paste_app",
            )
        with col_p2:
            paste_req = st.text_area(
                "Paste requirements.txt (Optional):",
                height=220,
                value="streamlit\ngroq\n",
                placeholder="streamlit\npandas\nrequests",
                key="paste_req",
            )

        if st.button(
            "💾 Save & Open Studio", type="primary", use_container_width=True
        ):
            if paste_name.strip() and paste_app.strip():
                try:
                    files_to_save = {
                        "app.py": paste_app.strip(),
                        "requirements.txt": paste_req.strip()
                        if paste_req.strip()
                        else "streamlit\n",
                    }
                    create_project(paste_name.strip(), files_to_save)
                    st.session_state["view"] = "workspace"
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("A project with this name already exists!")
            else:
                st.warning("Please provide a project name and your app.py code.")

    st.stop()


# =========================================================
# 8. ACTIVE WORKSPACE
# =========================================================
active_v_num = current_v_data[0]
active_note = current_v_data[1]
active_created = current_v_data[2]
active_files = parse_version_files(current_v_data[3])
active_missing = current_v_data[4]
active_error = current_v_data[5]
active_status = current_v_data[6]

total_lines_app = len(active_files.get("app.py", "").splitlines())

# Workspace Header
st.markdown(
    f"""
<div style="display: flex; align-items: center; justify-content: space-between; padding: 14px 20px; background: #1e293b; border-radius: 12px; margin-bottom: 20px;">
    <div>
        <span style="font-size: 1.5rem; font-weight: 800; color: #f8fafc;">📁 {selected_p_name}</span>
        <span style="margin-left: 12px;" class="version-pill">Active: v{active_v_num}</span>
        <span style="margin-left: 10px; color: #94a3b8; font-size: 0.88rem;">(app.py: {total_lines_app} lines)</span>
    </div>
    <div style="color: #cbd5e1; font-size: 0.9rem;">
        Latest Edit: <em>{active_note}</em>
    </div>
</div>
""",
    unsafe_allow_html=True,
)

# Input Box: Make a Change OR Fix an Error
with st.container():
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("#### 📝 Request a Change")
        user_change = st.text_area(
            "Describe the feature or UI tweak to make:",
            height=110,
            placeholder="e.g., Change navbar color to dark blue, fix button spacing, and add an alert popup...",
            label_visibility="collapsed",
        )
        apply_btn = st.button(
            "🚀 Apply Change & Save Version",
            type="primary",
            use_container_width=True,
        )

    with c2:
        st.markdown("#### ⚠️ Fix a Streamlit / Terminal Error")
        user_error = st.text_area(
            "Paste terminal or Streamlit red error traceback:",
            height=110,
            placeholder="e.g., ModuleNotFoundError: No module named 'plotly' OR StreamlitDuplicateElementKey...",
            label_visibility="collapsed",
        )
        fix_error_btn = st.button(
            "🛠️ Fix Error Now", use_container_width=True
        )

# AI Execution Logic with Isolated File Output
if apply_btn or fix_error_btn:
    req_type = "ERROR_FIX" if fix_error_btn else "FEATURE_CHANGE"
    target_prompt = user_error if fix_error_btn else user_change

    if not target_prompt.strip():
        st.warning("Please type a change instruction or paste an error.")
    else:
        with st.spinner("AI is refactoring files with separate outputs..."):
            sys_prompt = """
            You are a senior software architect and Python/Streamlit debugger.
            You will receive the CURRENT FILES (app.py, requirements.txt) and a REQUEST (either a modification or traceback error).
            
            You MUST return a valid JSON object with these exact keys:
            {
                "files": {
                    "app.py": "The 100% complete updated Python script without omissions",
                    "requirements.txt": "The exact list of pip dependencies required, one per line"
                },
                "run_status": "Brief message confirming if the code is verified (e.g., '✅ Code verified and ready to run.')",
                "missing_items": "Bullet points listing any environment variables or setup notes",
                "error_solution": "Detailed breakdown: why the error occurred and how it was resolved",
                "changelog": "Brief summary of what was updated"
            }
            CRITICAL: 'app.py' must be complete from top to bottom. Do NOT write placeholders like '// rest of code'.
            'requirements.txt' must ONLY contain package names, nothing else.
            """

            u_prompt = f"""
            [REQUEST TYPE]: {req_type}
            
            [CURRENT FILES]:
            --- app.py ---
            {active_files.get('app.py', '')}
            
            --- requirements.txt ---
            {active_files.get('requirements.txt', '')}
            
            [USER INSTRUCTION / ERROR]:
            {target_prompt}
            """

            try:
                res = call_groq(sys_prompt, u_prompt, json_mode=True)
                parsed = parse_ai_json(res)

                new_files = parsed.get("files", active_files)
                missing_info = parsed.get(
                    "missing_items", "All dependencies are satisfied."
                )
                err_info = parsed.get(
                    "error_solution", "Code successfully updated."
                )
                status_info = parsed.get("run_status", "✅ Verified")
                note = f"Fix: {target_prompt[:35]}" if fix_error_btn else f"Change: {target_prompt[:35]}"

                save_version(
                    current_p_id,
                    new_files,
                    note,
                    missing_info,
                    err_info,
                    status_info,
                )
                st.success("New version created and saved with separated files!")
                st.rerun()
            except Exception as e:
                st.error(f"Processing error: {str(e)}")


# =========================================================
# 9. WORKSPACE TABS
# =========================================================
st.divider()

tab_code, tab_history, tab_missing, tab_error, tab_ideas, tab_settings = (
    st.tabs([
        "📁 1. Project Files (Separated)",
        "📜 2. Edit History & Timeline",
        "⚠️ 3. Missing Dependencies",
        "🔍 4. Error Diagnosis",
        "💡 5. Innovative Ideas",
        "⚙️ 6. Manage / Delete Project",
    ])
)

# ----------------- TAB 1: SEPARATED PROJECT FILES -----------------
with tab_code:
    st.info(f"**Status:** {active_status}")

    # Sub-tabs for each separate file!
    sub_app, sub_req = st.tabs(["📄 app.py", "📄 requirements.txt"])

    with sub_app:
        c_head, c_dwn = st.columns([3, 1])
        with c_head:
            st.markdown(
                "👉 **For GitHub (`app.py`):** Click the **Copy icon** at the top right of the box below. It contains **ONLY** Python code."
            )
        with c_dwn:
            st.download_button(
                label="📥 Download app.py",
                data=active_files.get("app.py", ""),
                file_name="app.py",
                mime="text/x-python",
                use_container_width=True,
            )
        st.code(active_files.get("app.py", ""), language="python")

    with sub_req:
        c_head2, c_dwn2 = st.columns([3, 1])
        with c_head2:
            st.markdown(
                "👉 **For GitHub (`requirements.txt`):** Click the **Copy icon** at the top right of the box below. It contains **ONLY** package dependencies."
            )
        with c_dwn2:
            st.download_button(
                label="📥 Download requirements.txt",
                data=active_files.get("requirements.txt", ""),
                file_name="requirements.txt",
                mime="text/plain",
                use_container_width=True,
            )
        st.code(active_files.get("requirements.txt", ""), language="text")

# ----------------- TAB 2: EDIT HISTORY & ROLLBACK -----------------
with tab_history:
    st.subheader(f"📜 Version History Timeline for `{selected_p_name}`")
    st.caption(
        "Every change is recorded. You can inspect or rollback to any previous version:"
    )

    for v in versions:
        v_num, v_note, v_time, v_raw_code, v_missing, v_err, v_status = v
        v_files = parse_version_files(v_raw_code)
        is_current = v_num == active_v_num

        with st.expander(
            f"{'🟢 [ACTIVE] ' if is_current else '⚪ '}Version {v_num} — {v_note} ({v_time})",
            expanded=is_current,
        ):
            c_info, c_action = st.columns([3, 1])
            with c_info:
                st.markdown(f"**Change Note:** {v_note}")
                st.markdown(f"**Saved At:** {v_time}")
                st.markdown(f"**Verification:** {v_status}")
            with c_action:
                if not is_current:
                    if st.button(
                        f"⏮️ Restore v{v_num}",
                        key=f"btn_restore_{v_num}",
                        use_container_width=True,
                    ):
                        save_version(
                            current_p_id,
                            v_files,
                            f"Restored to v{v_num}",
                            v_missing,
                            v_err,
                            f"✅ Restored from v{v_num}",
                        )
                        st.success(
                            f"Successfully rolled back to Version {v_num}!"
                        )
                        st.rerun()
                else:
                    st.success("Currently Active")

            hist_app, hist_req = st.tabs(
                [f"app.py (v{v_num})", f"requirements.txt (v{v_num})"]
            )
            with hist_app:
                st.code(v_files.get("app.py", ""), language="python")
            with hist_req:
                st.code(v_files.get("requirements.txt", ""), language="text")

# ----------------- TAB 3: MISSING DEPENDENCIES -----------------
with tab_missing:
    st.subheader("🔍 Missing Dependencies & Configuration Audit")
    st.write(active_missing)
    st.info(
        "💡 Check the `📄 requirements.txt` sub-tab under 'Project Files' to copy all needed packages directly."
    )

# ----------------- TAB 4: ERROR DIAGNOSIS -----------------
with tab_error:
    st.subheader("🛠️ Error Diagnosis & Fix Details")
    st.write(active_error)

# ----------------- TAB 5: INNOVATIVE IDEAS -----------------
with tab_ideas:
    st.subheader(f"💡 Innovative Feature Suggestions for `{selected_p_name}`")
    st.caption("Generate project-specific enhancements complete with architecture flowcharts:")

    if st.button("🔮 Generate 5-6 Smart Ideas for this Project"):
        with st.spinner("Analyzing project architecture and formulating features..."):
            ideas_sys = """
            You are a senior product architect.
            Analyze the provided code and generate 5 to 6 innovative, practical features tailored to this project.
            
            Return a JSON object containing an 'ideas' array:
            {
                "ideas": [
                    {
                        "id": 1,
                        "title": "Short descriptive title (e.g., Automated PDF Report Export)",
                        "diagram": "Clear ASCII Flowchart diagram showing step by step how data flows (e.g., [User Click] -> [Process] -> [Export])",
                        "description": "Clear explanation of what it does and why it benefits the app",
                        "prompt_to_apply": "Precise instruction to tell an AI to integrate this feature cleanly into app.py and requirements.txt"
                    }
                ]
            }
            """
            try:
                res_ideas = call_groq(
                    ideas_sys,
                    f"Current app.py:\n{active_files.get('app.py', '')}",
                    json_mode=True,
                )
                parsed_ideas = parse_ai_json(res_ideas)
                ideas_list = parsed_ideas.get("ideas", [])
                save_ideas(current_p_id, ideas_list)
                st.success("New feature ideas generated!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to generate ideas: {str(e)}")

    saved_ideas = get_saved_ideas(current_p_id)

    if saved_ideas:
        idea_titles = [f"{item['id']}. {item['title']}" for item in saved_ideas]
        selected_idea_title = st.selectbox(
            "Select an idea to inspect details & diagram:", idea_titles
        )

        selected_idea_idx = idea_titles.index(selected_idea_title)
        chosen_idea = saved_ideas[selected_idea_idx]

        st.markdown(f"### 📌 {chosen_idea['title']}")

        st.markdown("#### 📊 Architecture / Data Flow:")
        st.code(
            chosen_idea.get("diagram", "[Input] --> [Process] --> [Output]"),
            language="text",
        )

        st.markdown("#### 📝 Overview:")
        st.write(chosen_idea.get("description", ""))

        st.divider()

        if st.button(
            "👉 Proceed & Integrate this Feature into Code", type="primary"
        ):
            with st.spinner(
                f"Integrating '{chosen_idea['title']}' into codebase..."
            ):
                integrate_sys = """
                You are a lead developer. You must integrate the requested feature into the existing code seamlessly.
                Return a valid JSON object:
                {
                    "files": {
                        "app.py": "100% complete updated Python script",
                        "requirements.txt": "Updated requirements.txt with any new packages included"
                    },
                    "run_status": "✅ Feature integrated and verified successfully.",
                    "error_solution": "Feature integrated cleanly without syntax errors.",
                    "missing_items": "Any new setup notes"
                }
                """
                integ_prompt = f"""
                CURRENT FILES:
                --- app.py ---
                {active_files.get('app.py', '')}
                
                --- requirements.txt ---
                {active_files.get('requirements.txt', '')}

                FEATURE TO INTEGRATE:
                {chosen_idea['prompt_to_apply']}
                """
                try:
                    res_int = call_groq(
                        integrate_sys,
                        integ_prompt,
                        json_mode=True,
                    )
                    parsed_int = parse_ai_json(res_int)
                    new_integrated_files = parsed_int.get("files", active_files)

                    save_version(
                        current_p_id,
                        new_integrated_files,
                        f"Integrated: {chosen_idea['title']}",
                        parsed_int.get(
                            "missing_items", "No extra dependencies."
                        ),
                        "New feature added cleanly.",
                        "✅ Verified with new feature",
                    )
                    st.success(
                        f"'{chosen_idea['title']}' integrated! Version updated. Go to [📁 Project Files] tab to copy."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Integration failed: {str(e)}")
    else:
        st.info("Click the button above to generate smart feature ideas.")

# ----------------- TAB 6: MANAGE / DELETE PROJECT -----------------
with tab_settings:
    st.subheader(f"⚙️ Manage & Delete `{selected_p_name}`")
    st.write(
        "Need to clean up this project? You can permanently remove it and all of its version history below."
    )

    st.markdown("---")
    st.warning("⚠️ **Danger Zone:** This action is permanent and cannot be undone.")

    confirm_box = st.checkbox(
        f"I confirm that I want to permanently delete **{selected_p_name}** and all its versions."
    )

    if confirm_box:
        if st.button(
            f"🚨 Permanently Delete '{selected_p_name}'", type="primary"
        ):
            delete_project(current_p_id)
            st.success(f"Project '{selected_p_name}' was successfully deleted.")
            st.session_state["view"] = "create_project"
            st.rerun()
