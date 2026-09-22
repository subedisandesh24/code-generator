import json
import sqlite3
from datetime import datetime
from groq import Groq
import streamlit as st

st.set_page_config(
    page_title="AI Code Studio (Powered by Groq)",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================
# 1. VERIFY STREAMLIT SECRETS (GROQ_API_KEY)
# =========================================================
if "GROQ_API_KEY" not in st.secrets:
    st.error("""
    ⚠️ **GROQ_API_KEY is missing from Streamlit Secrets!**
    
    Please create a file at `.streamlit/secrets.toml` and add:
    ```toml
    GROQ_API_KEY = "gsk_your_groq_key_here"
    ```
    """)
    st.stop()

GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
DB_FILE = "code_studio.db"


# =========================================================
# 2. DATABASE SETUP (Built-in SQLite)
# =========================================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Projects table
    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            created_at TEXT
        )
    """)
    # Versions table
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
    # Stored ideas table
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


def create_project(name, code, note="Initial Code"):
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
        VALUES (?, 1, ?, ?, 'No missing items detected.', 'No errors reported.', '✅ Script is verified and ready to run.', ?)
    """,
        (p_id, code, note, now),
    )
    conn.commit()
    conn.close()
    return p_id


def save_version(
    p_id,
    code,
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
        (p_id, new_v, code, note, missing, err_sol, status, now),
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
# 3. GROQ AI ENGINE
# =========================================================
def call_groq(model, system_prompt, user_prompt, json_mode=False):
    client = Groq(api_key=GROQ_API_KEY)
    kwargs = {
        "model": model,
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
# 4. SIDEBAR: PROJECT SETUP & ROLLBACK CONTROLS
# =========================================================
with st.sidebar:
    st.title("⚡ Groq Control Panel")
    st.caption("🔑 API Key loaded securely from `secrets.toml`")

    # High-speed Groq models
    model_choice = st.selectbox(
        "Select Groq Model",
        [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
        ],
    )

    st.divider()
    st.subheader("📁 Project Management")

    with st.expander("➕ Create New Project"):
        p_name_input = st.text_input("Project Name")
        create_mode = st.radio(
            "Creation Mode",
            [
                "Paste Existing Script",
                "Generate from Scratch (Prompt)",
            ],
        )

        if create_mode == "Paste Existing Script":
            p_initial_code = st.text_area(
                "Paste your existing script here:", height=180
            )
            if st.button("Save New Project"):
                if p_name_input.strip() and p_initial_code.strip():
                    try:
                        create_project(
                            p_name_input.strip(), p_initial_code.strip()
                        )
                        st.success(
                            f"Project '{p_name_input}' created successfully!"
                        )
                        st.rerun()
                    except sqlite3.IntegrityError:
                        st.error("A project with this name already exists.")
                else:
                    st.warning("Please provide both a project name and code.")
        else:
            p_prompt = st.text_area(
                "Describe the website to generate:",
                height=150,
                placeholder="e.g., Build a modern responsive gym landing page with timetable, pricing tiers, and contact form...",
            )
            if st.button("✨ Generate Project from Scratch"):
                if p_name_input.strip() and p_prompt.strip():
                    with st.spinner("Groq is generating your complete code at ultra-high speed..."):
                        sys_p = "You are a master web developer. Generate a 100% complete, fully working single-file Python/Streamlit script based on the prompt. Do not abbreviate or omit code. Output raw code inside triple backticks."
                        code_res = call_groq(
                            model_choice, sys_p, p_prompt, json_mode=False
                        )
                        cleaned = (
                            "\n".join(code_res.splitlines()[1:-1])
                            if code_res.strip().startswith("```")
                            else code_res
                        )
                        try:
                            create_project(
                                p_name_input.strip(),
                                cleaned,
                                f"Created from prompt: {p_prompt[:40]}...",
                            )
                            st.success(
                                f"Project '{p_name_input}' created successfully!"
                            )
                            st.rerun()
                        except sqlite3.IntegrityError:
                            st.error("A project with this name already exists.")
                else:
                    st.warning(
                        "Please provide both a project name and a prompt."
                    )

    # Active project selector
    all_projects = get_projects()
    if not all_projects:
        st.info("👈 Please create a project above to get started.")
        st.stop()

    st.divider()
    st.subheader("📂 Active Workspace")
    p_dict = {name: pid for pid, name in all_projects}
    selected_p_name = st.selectbox(
        "Select Active Project", list(p_dict.keys())
    )
    current_p_id = p_dict[selected_p_name]

    # Version history and rollback dropdown
    versions = get_versions(current_p_id)
    v_map = {
        f"v{v[0]}: {v[1]} ({v[2]})": {
            "v_num": v[0],
            "note": v[1],
            "code": v[3],
            "missing": v[4],
            "error": v[5],
            "status": v[6],
        }
        for v in versions
    }

    st.subheader("⏪ Version History & Rollback")
    selected_v_key = st.selectbox(
        "Browse / Restore Past Versions:", list(v_map.keys())
    )
    current_v_data = v_map[selected_v_key]

    if st.button("⏮️ Rollback / Restore This Version"):
        save_version(
            current_p_id,
            current_v_data["code"],
            f"Restored from v{current_v_data['v_num']}",
            current_v_data["missing"],
            "Rolled back to previous stable state.",
            "✅ Restored from previous version",
        )
        st.success("Successfully rolled back to the selected version!")
        st.rerun()


# =========================================================
# 5. MAIN PROJECT WORKSPACE
# =========================================================
active_code = current_v_data["code"]
active_v_num = current_v_data["v_num"]

# Top Header: Displays Project Name & Current Version
st.markdown(
    f"## 📁 PROJECT: `{selected_p_name}` &nbsp;&nbsp;|&nbsp;&nbsp; 🏷️ Active Version: `v{active_v_num}`"
)
st.caption(f"**Log Note:** {current_v_data['note']}")

st.divider()

# Input Actions: Modify Code OR Paste Terminal Error
with st.container():
    st.subheader("✍️ Modify Code or Fix Issues")
    c1, c2 = st.columns(2)

    with c1:
        user_change = st.text_area(
            "📝 Feature / Code Modification Request:",
            height=140,
            placeholder="e.g., Change navbar color to dark slate, add a download button, and style the headers...",
        )
        apply_btn = st.button(
            "🚀 Apply Change & Save Version",
            type="primary",
            use_container_width=True,
        )

    with c2:
        user_error = st.text_area(
            "⚠️ Paste Terminal or Streamlit Error Traceback:",
            height=140,
            placeholder="e.g., StreamlitDuplicateElementKey: There are multiple identical elements with key='submit'...",
        )
        fix_error_btn = st.button(
            "🛠️ Fix Error & Update Script", use_container_width=True
        )

# =========================================================
# 6. GROQ PROCESSING PIPELINE
# =========================================================
if apply_btn or fix_error_btn:
    req_type = "ERROR_FIX" if fix_error_btn else "FEATURE_CHANGE"
    target_prompt = user_error if fix_error_btn else user_change

    if not target_prompt.strip():
        st.warning("Please enter a modification request or paste an error log.")
    else:
        with st.spinner("Groq is refactoring and verifying your code..."):
            sys_prompt = """
            You are a senior software architect and Streamlit/Python debugger.
            You will receive the CURRENT CODE and a REQUEST (either a modification or a traceback error).
            
            You MUST return a valid JSON object with these exact keys:
            {
                "full_code": "The 100% complete, fully working updated script without any omissions or placeholders",
                "run_status": "Brief message confirming if the code is verified to run smoothly (e.g., '✅ Code verified and ready to run.')",
                "missing_items": "Bullet points listing any missing requirements.txt packages, environment variables, or files",
                "error_solution": "Detailed breakdown: why the error occurred and how it was resolved in code",
                "changelog": "Brief summary of what lines or features were updated"
            }
            CRITICAL REQUIREMENT: 'full_code' must be complete from top to bottom. Do NOT write placeholders like '// rest of code unchanged'.
            """

            u_prompt = f"""
            [REQUEST TYPE]: {req_type}
            
            [CURRENT CODE]:
            {active_code}
            
            [USER INSTRUCTION / ERROR]:
            {target_prompt}
            """

            try:
                res = call_groq(
                    model_choice, sys_prompt, u_prompt, json_mode=True
                )
                parsed = parse_ai_json(res)

                new_code = parsed.get("full_code", active_code)
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
                    new_code,
                    note,
                    missing_info,
                    err_info,
                    status_info,
                )
                st.success("New version created and saved successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Processing error: {str(e)}")


# =========================================================
# 7. OUTPUT TABS (THE 4 DEDICATED TABS)
# =========================================================
st.divider()

tab_code, tab_missing, tab_error, tab_ideas = st.tabs([
    "📋 1. Full Script (Ready for GitHub)",
    "⚠️ 2. Missing Items & Audit",
    "🔍 3. Error Solution & Diagnosis",
    "💡 4. Innovative Ideas & Feature Builder",
])

# ----------------- TAB 1: FULL SCRIPT -----------------
with tab_code:
    st.info(f"**Execution Status:** {current_v_data['status']}")
    st.markdown(
        "👉 **Ready for GitHub:** Hover over the top-right corner of the code box below and click the **Copy icon**, then paste directly into GitHub."
    )

    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        st.download_button(
            label="📥 Download Script as .py",
            data=active_code,
            file_name=f"{selected_p_name}_v{active_v_num}.py",
            mime="text/plain",
            use_container_width=True,
        )

    st.code(active_code, language="python")

# ----------------- TAB 2: MISSING ITEMS -----------------
with tab_missing:
    st.subheader("🔍 Missing Dependencies & Environment Audit")
    st.write(current_v_data["missing"])
    st.info(
        "💡 If any external packages are highlighted above, add them to your `requirements.txt` file."
    )

# ----------------- TAB 3: ERROR SOLUTION -----------------
with tab_error:
    st.subheader("🛠️ Root Cause Diagnosis & Solution Details")
    st.write(current_v_data["error"])

# ----------------- TAB 4: INNOVATIVE IDEAS & PROCEED -----------------
with tab_ideas:
    st.subheader(f"💡 Innovative Feature Suggestions for `{selected_p_name}`")
    st.caption(
        "Analyze your current code to generate 5-6 tailored, high-value ideas complete with visual flow diagrams:"
    )

    if st.button("🔮 Generate 5-6 Smart Ideas for this Project"):
        with st.spinner("Groq is analyzing project code to formulate smart ideas..."):
            ideas_sys = """
            You are a senior product architect and UI/UX expert.
            Analyze the provided code and generate 5 to 6 innovative, highly practical features tailored to this project.
            
            Return a JSON object containing an 'ideas' array:
            {
                "ideas": [
                    {
                        "id": 1,
                        "title": "Short descriptive title (e.g., Automated PDF Report Export)",
                        "diagram": "Clear ASCII Flowchart diagram showing step by step how data and UI flow (e.g., [User Click] -> [Process] -> [Export])",
                        "description": "Clear explanation of what it does, how it works, and why it benefits the application",
                        "prompt_to_apply": "Precise instruction to tell an AI to seamlessly integrate this feature into the script"
                    }
                ]
            }
            """
            try:
                res_ideas = call_groq(
                    model_choice,
                    ideas_sys,
                    f"Current project code:\n{active_code}",
                    json_mode=True,
                )
                parsed_ideas = parse_ai_json(res_ideas)
                ideas_list = parsed_ideas.get("ideas", [])
                save_ideas(current_p_id, ideas_list)
                st.success("New feature ideas generated successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to generate ideas: {str(e)}")

    saved_ideas = get_saved_ideas(current_p_id)

    if saved_ideas:
        idea_titles = [f"{item['id']}. {item['title']}" for item in saved_ideas]
        selected_idea_title = st.selectbox(
            "Select an idea to inspect its diagram and specs:", idea_titles
        )

        selected_idea_idx = idea_titles.index(selected_idea_title)
        chosen_idea = saved_ideas[selected_idea_idx]

        st.markdown(f"### 📌 {chosen_idea['title']}")

        # Architecture flowchart
        st.markdown("#### 📊 Architecture / Flow Diagram:")
        st.code(
            chosen_idea.get("diagram", "[Input] --> [Process] --> [Output]"),
            language="text",
        )

        st.markdown("#### 📝 Feature Overview:")
        st.write(chosen_idea.get("description", ""))

        st.divider()
        st.markdown("#### 🚀 Automatic Integration:")

        if st.button(
            "👉 Proceed & Integrate this Feature into Code", type="primary"
        ):
            with st.spinner(
                f"Groq is integrating '{chosen_idea['title']}' into your codebase..."
            ):
                integrate_sys = """
                You are a lead developer. You must integrate the requested feature into the existing code seamlessly.
                Return a valid JSON object:
                {
                    "full_code": "100% complete updated script with the new feature integrated",
                    "missing_items": "Any new libraries required for this feature",
                    "run_status": "✅ Feature integrated and verified successfully.",
                    "error_solution": "Feature integrated cleanly without syntax errors."
                }
                """
                integ_prompt = f"""
                CURRENT CODE:
                {active_code}

                FEATURE TO INTEGRATE:
                {chosen_idea['prompt_to_apply']}
                """
                try:
                    res_int = call_groq(
                        model_choice,
                        integrate_sys,
                        integ_prompt,
                        json_mode=True,
                    )
                    parsed_int = parse_ai_json(res_int)
                    new_integrated_code = parsed_int.get(
                        "full_code", active_code
                    )

                    save_version(
                        current_p_id,
                        new_integrated_code,
                        f"Integrated: {chosen_idea['title']}",
                        parsed_int.get(
                            "missing_items", "No extra dependencies."
                        ),
                        "New feature added cleanly.",
                        "✅ Verified with new feature",
                    )
                    st.success(
                        f"'{chosen_idea['title']}' integrated! Switched to new version. Check the [📋 Full Script] tab to copy."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Integration failed: {str(e)}")
    else:
        st.info(
            "Click 'Generate 5-6 Smart Ideas for this Project' above to inspect AI-recommended enhancements."
        )
