"""
Graph RAG as a Service - Streamlit Frontend
"""

import streamlit as st
import requests
import json
import time
from datetime import datetime

# ─── Page Config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Graph RAG Service",
    page_icon="🕸️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Constants ───────────────────────────────────────────────────────────────
DEFAULT_API_URL = "http://localhost:8000"

# ─── Session State Init ──────────────────────────────────────────────────────
if "token" not in st.session_state:
    st.session_state.token = None
if "username" not in st.session_state:
    st.session_state.username = None
if "api_url" not in st.session_state:
    st.session_state.api_url = DEFAULT_API_URL
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


# ─── Helper Functions ────────────────────────────────────────────────────────
def get_headers():
    return {"Authorization": f"Bearer {st.session_state.token}"}


def api_get(path, params=None):
    try:
        r = requests.get(
            f"{st.session_state.api_url}{path}",
            headers=get_headers(),
            params=params,
            timeout=30
        )
        return r
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot connect to the backend. Make sure the server is running.")
        return None


def api_post(path, json_data=None, files=None):
    try:
        r = requests.post(
            f"{st.session_state.api_url}{path}",
            headers=get_headers() if st.session_state.token else {},
            json=json_data,
            files=files,
            timeout=60
        )
        return r
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot connect to the backend. Make sure the server is running.")
        return None


def api_put(path, json_data=None):
    try:
        r = requests.put(
            f"{st.session_state.api_url}{path}",
            headers=get_headers(),
            json=json_data,
            timeout=30
        )
        return r
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot connect to the backend. Make sure the server is running.")
        return None


def api_delete(path):
    try:
        r = requests.delete(
            f"{st.session_state.api_url}{path}",
            headers=get_headers(),
            timeout=30
        )
        return r
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot connect to the backend. Make sure the server is running.")
        return None


# ─── Login Page ──────────────────────────────────────────────────────────────
def page_login():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🕸️ Graph RAG as a Service")
        st.markdown("### Login")

        with st.form("login_form"):
            username = st.text_input("Username", placeholder="Enter username")
            password = st.text_input("Password", type="password", placeholder="Enter password")
            api_url = st.text_input("API URL", value=st.session_state.api_url)
            submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            st.session_state.api_url = api_url.rstrip("/")
            r = requests.post(
                f"{st.session_state.api_url}/api/auth/login",
                json={"username": username, "password": password},
                timeout=10
            ) if username and password else None

            if r and r.status_code == 200:
                data = r.json()
                st.session_state.token = data["access_token"]
                st.session_state.username = username
                st.success("✅ Logged in successfully!")
                time.sleep(0.5)
                st.rerun()
            elif not username or not password:
                st.warning("Please enter username and password.")
            else:
                st.error(f"Login failed: {r.json().get('detail', 'Unknown error') if r else 'Server unreachable'}")

        st.markdown("---")
        st.caption("💡 Tip: The backend accepts any non-empty username/password for demo purposes.")


# ─── Dashboard Page ───────────────────────────────────────────────────────────
def page_dashboard():
    st.markdown("## 📊 Dashboard")

    # Health Check
    health_r = api_get("/api/system/health")
    stats_r   = api_get("/api/system/stats")

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🩺 System Health")
        if health_r and health_r.status_code == 200:
            h = health_r.json()
            status_color = "🟢" if h["status"] == "healthy" else "🟡"
            st.markdown(f"**Status:** {status_color} {h['status'].upper()}")
            st.markdown(f"**Version:** `{h['version']}`")

            neo4j_icon = "✅" if h["neo4j_connected"] else "❌"
            redis_icon = "✅" if h["redis_connected"] else "❌"
            workers = h["workers_active"]

            st.markdown(f"- Neo4j: {neo4j_icon}")
            st.markdown(f"- Redis: {redis_icon}")
            st.markdown(f"- Active Workers: `{workers}`")
            st.caption(f"Checked at: {h['timestamp']}")
        else:
            st.warning("Could not fetch health status.")

    with col2:
        st.markdown("### 📈 Graph Statistics")
        if stats_r and stats_r.status_code == 200:
            s = stats_r.json()
            c1, c2 = st.columns(2)
            c1.metric("Documents",     s.get("documents_count", 0))
            c2.metric("Entities",      s.get("entities_count", 0))
            c1.metric("Relationships", s.get("relationships_count", 0))
            c2.metric("Chunks",        s.get("chunks_count", 0))
            st.markdown(f"**Ontology Version:** `{s.get('ontology_version', 'none')}`")
        else:
            st.warning("Could not fetch graph statistics.")

    # Refresh button
    if st.button("🔄 Refresh"):
        st.rerun()


# ─── Document Upload Page ─────────────────────────────────────────────────────
def page_upload():
    st.markdown("## 📄 Document Upload & Ingestion")

    uploaded_file = st.file_uploader(
        "Upload a document",
        type=["pdf", "txt", "md", "docx"],
        help="Supported formats: PDF, TXT, Markdown, DOCX"
    )

    if uploaded_file:
        st.info(f"**File:** {uploaded_file.name} ({uploaded_file.size:,} bytes)")

        if st.button("🚀 Upload & Ingest", use_container_width=True):
            with st.spinner("Uploading document..."):
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), uploaded_file.type)}
                r = requests.post(
                    f"{st.session_state.api_url}/api/documents/upload",
                    headers=get_headers(),
                    files=files,
                    timeout=60
                )

            if r and r.status_code == 200:
                data = r.json()
                st.success(f"✅ {data['message']}")
                task_id = data.get("task_id")

                if task_id:
                    st.markdown(f"**Task ID:** `{task_id}`")
                    st.markdown("---")
                    st.markdown("### ⏳ Ingestion Progress")

                    progress_bar = st.progress(0)
                    status_text  = st.empty()

                    for i in range(60):  # Poll up to 60 times
                        time.sleep(3)
                        status_r = api_get(f"/api/documents/status/{task_id}")

                        if status_r and status_r.status_code == 200:
                            s = status_r.json()
                            task_status = s["status"]
                            status_text.markdown(f"**Status:** `{task_status}`")

                            if task_status == "completed":
                                progress_bar.progress(100)
                                st.success("✅ Ingestion complete!")
                                if s.get("result"):
                                    st.json(s["result"])
                                break
                            elif task_status == "failed":
                                progress_bar.progress(0)
                                st.error(f"❌ Ingestion failed: {s.get('result', 'Unknown error')}")
                                break
                            elif task_status == "processing":
                                progress = s.get("progress") or {}
                                pct = progress.get("percentage", (i + 1) * 2)
                                progress_bar.progress(min(int(pct), 95))
                            else:
                                progress_bar.progress(min((i + 1) * 2, 40))
                        else:
                            break
            elif r:
                st.error(f"❌ Upload failed: {r.json().get('detail', r.text)}")

    st.markdown("---")
    st.markdown("### 📋 Check Existing Task Status")
    with st.form("check_task"):
        task_id_input = st.text_input("Task ID", placeholder="Paste task ID here")
        check = st.form_submit_button("Check Status")

    if check and task_id_input:
        r = api_get(f"/api/documents/status/{task_id_input}")
        if r and r.status_code == 200:
            st.json(r.json())
        elif r:
            st.error(r.json().get("detail", "Error"))


# ─── Query / Chat Page ────────────────────────────────────────────────────────
def page_query():
    st.markdown("## 💬 Query the Knowledge Graph")

    # ── Sidebar controls (right column) ──────────────────────────────────────
    selected_doc_id = None  # safe default in case API is unreachable
    col1, col2 = st.columns([3, 1])
    with col2:
        top_k = st.slider("Top K Results", 1, 20, 5)

        doc_r = api_get("/api/documents")
        doc_options: dict = {"All Documents": None}
        if doc_r and doc_r.status_code == 200:
            for d in doc_r.json().get("documents", []):
                doc_options[d["filename"]] = d["id"]
        selected_doc_name = st.selectbox("Filter by Document", list(doc_options.keys()))
        selected_doc_id = doc_options[selected_doc_name]

        if st.button("🗑️ Clear Chat"):
            st.session_state.chat_history = []
            st.rerun()

    # ── Chat history ──────────────────────────────────────────────────────────
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.chat_history:
            if msg["role"] == "user":
                with st.chat_message("user"):
                    st.markdown(msg["content"])
            else:
                with st.chat_message("assistant"):
                    st.markdown(msg["content"])
                    if msg.get("meta"):
                        meta = msg["meta"]
                        with st.expander("🔍 Details"):
                            c1, c2, c3 = st.columns(3)
                            c1.metric("Confidence",  f"{meta.get('confidence', 0):.0%}")
                            c2.metric("Method",       meta.get("retrieval_method", "—"))
                            c3.metric("Time",         f"{meta.get('processing_time_seconds', 0):.2f}s")

                            if meta.get("reasoning_chain"):
                                st.markdown("**Reasoning Chain:**")
                                for step in meta["reasoning_chain"]:
                                    st.markdown(f"- {step}")

                            if meta.get("sources"):
                                st.markdown("**Sources:**")
                                st.json(meta["sources"])

    user_query = st.chat_input("Ask anything about your documents...")

    if user_query:
        st.session_state.chat_history.append({"role": "user", "content": user_query})

        with st.spinner("Thinking..."):
            r = api_post("/api/query", json_data={"query": user_query, "top_k": top_k, "streaming": False, "document_id": selected_doc_id})

        if r and r.status_code == 200:
            data = r.json()
            st.session_state.chat_history.append({
                "role": "assistant",
                "content": data["answer"],
                "meta": {
                    "confidence":              data.get("confidence", 0),
                    "retrieval_method":        data.get("retrieval_method", ""),
                    "processing_time_seconds": data.get("processing_time_seconds", 0),
                    "reasoning_chain":         data.get("reasoning_chain", []),
                    "sources":                 data.get("sources", [])
                }
            })
        elif r:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text or f"HTTP {r.status_code}"
            st.session_state.chat_history.append({
                "role": "assistant",
                "content": f"❌ Error: {detail}"
            })

        st.rerun()


# ─── Documents Management Page ───────────────────────────────────────────────
def page_documents():
    st.markdown("## 📂 Documents")

    r = api_get("/api/documents")
    if not r:
        return
    if r.status_code != 200:
        st.error(f"❌ {r.json().get('detail', r.text)}")
        return

    data = r.json()
    docs = data.get("documents", [])

    st.metric("Total Documents", data.get("total", 0))

    if not docs:
        st.info("No documents ingested yet. Go to **Upload Documents** to add some.")
        return

    st.markdown("---")
    # Header row
    hc1, hc2, hc3, hc4, hc5 = st.columns([3, 1, 1, 2, 1])
    hc1.markdown("**Filename**")
    hc2.markdown("**Type**")
    hc3.markdown("**Size**")
    hc4.markdown("**Uploaded**")
    hc5.markdown("**Action**")
    st.markdown("---")

    for doc in docs:
        c1, c2, c3, c4, c5 = st.columns([3, 1, 1, 2, 1])
        c1.markdown(f"**{doc['filename']}**")
        c2.markdown(f"`{doc['file_type']}`")

        size_kb = doc['size_bytes'] // 1024
        c3.markdown(f"{size_kb} KB" if size_kb > 0 else f"{doc['size_bytes']} B")
        c4.markdown(doc.get('upload_date', '—')[:19])

        if c5.button("🗑️ Delete", key=f"del_{doc['id']}"):
            dr = api_delete(f"/api/documents/{doc['id']}")
            if dr and dr.status_code == 200:
                st.success(f"✅ Deleted **{doc['filename']}**")
                st.rerun()
            elif dr:
                st.error(f"❌ {dr.json().get('detail', dr.text)}")

    st.markdown("---")
    if st.button("🔄 Refresh"):
        st.rerun()


# ─── Graph Visualization Page ─────────────────────────────────────────────────

# Color palette per entity type
_TYPE_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
    "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"
]

def _build_pyvis_html(nodes, edges):
    """Build an interactive pyvis network and return its HTML string."""
    from pyvis.network import Network

    # Assign a color to each unique entity type
    types = list({n.get("type", "Unknown") for n in nodes})
    type_color = {t: _TYPE_COLORS[i % len(_TYPE_COLORS)] for i, t in enumerate(types)}

    net = Network(
        height="620px",
        width="100%",
        bgcolor="#0e1117",
        font_color="white",
        notebook=False,
        directed=True,
    )

    id_map = {}  # neo4j string id -> pyvis int id
    for i, n in enumerate(nodes):
        nid = n["id"]
        label = n.get("label", nid)
        ntype = n.get("type", "Entity")
        color = type_color.get(ntype, "#888888")
        net.add_node(
            i,
            label=label,
            title=f"<b>{label}</b><br>Type: {ntype}",
            color={"background": color, "border": "#ffffff", "highlight": {"background": color, "border": "#ffffff"}},
            size=28,
            font={"size": 13, "color": "#ffffff", "strokeWidth": 3, "strokeColor": "#0e1117"},
            borderWidth=2,
        )
        id_map[nid] = i

    for e in edges:
        src = id_map.get(e["source"])
        tgt = id_map.get(e["target"])
        if src is not None and tgt is not None:
            rel_type = e.get("type", "")
            net.add_edge(
                src, tgt,
                # label hidden by default; shown in tooltip on hover
                title=rel_type,
                color={"color": "#555555", "highlight": "#aaaaaa", "hover": "#cccccc"},
                width=1.5,
                arrows={"to": {"enabled": True, "scaleFactor": 0.5}},
                smooth={"type": "curvedCW", "roundness": 0.15},
            )

    net.set_options("""
    {
      "nodes": {
        "shape": "dot",
        "shadow": {"enabled": true, "size": 8, "x": 3, "y": 3}
      },
      "edges": {
        "font": {"size": 0},
        "selectionWidth": 2
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 80,
        "navigationButtons": false,
        "keyboard": {"enabled": true}
      },
      "physics": {
        "barnesHut": {
          "gravitationalConstant": -12000,
          "centralGravity": 0.1,
          "springLength": 200,
          "springConstant": 0.04,
          "damping": 0.09,
          "avoidOverlap": 0.5
        },
        "stabilization": {"iterations": 200, "updateInterval": 25}
      }
    }
    """)

    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        net.save_graph(f.name)
        html = open(f.name, encoding="utf-8").read()
    os.unlink(f.name)

    # Remove the white body background pyvis injects so it matches Streamlit dark theme
    html = html.replace(
        "body {",
        "body { background-color: #0e1117 !important; margin: 0; padding: 0; /* orig: "
    ).replace(
        "background-color: white;",
        "background-color: #0e1117;"
    )
    return html


def page_graph():
    st.markdown("## 🕸️ Graph Visualization")

    limit = st.slider("Node Limit", 10, 200, 50)

    if st.button("🔄 Load Graph", use_container_width=True):
        with st.spinner("Fetching graph data..."):
            r = api_get("/api/graph/visualization", params={"limit": limit})

        if r and r.status_code == 200:
            data = r.json()
            nodes = data.get("nodes", [])
            edges = data.get("edges", [])

            if not nodes:
                st.info("No graph data yet. Upload and ingest some documents first.")
                return

            col1, col2, col3 = st.columns(3)
            col1.metric("Nodes",      len(nodes))
            col2.metric("Edges",      len(edges))
            col3.metric("Node Limit", limit)

            # ── Interactive network graph ────────────────────────────
            st.markdown("### 🕸️ Network Graph")

            # Legend
            types = list({n.get("type", "Unknown") for n in nodes})
            type_color = {t: _TYPE_COLORS[i % len(_TYPE_COLORS)] for i, t in enumerate(types)}
            legend_html = " &nbsp; ".join(
                f'<span style="background:{c};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{t}</span>'
                for t, c in type_color.items()
            )
            st.markdown(legend_html, unsafe_allow_html=True)

            try:
                html = _build_pyvis_html(nodes, edges)
                st.components.v1.html(html, height=620, scrolling=False)
            except ImportError:
                st.warning("pyvis not installed. Run: `pip install pyvis`")

            # ── Entity type breakdown ────────────────────────────────
            st.markdown("### 📊 Entity Type Breakdown")
            type_counts = {}
            for n in nodes:
                t = n.get("type", "Unknown")
                type_counts[t] = type_counts.get(t, 0) + 1
            cols = st.columns(min(len(type_counts), 5))
            for i, (t, count) in enumerate(type_counts.items()):
                cols[i % len(cols)].metric(t, count)

            # ── Tables ───────────────────────────────────────────────
            with st.expander("🗂️ Nodes Table"):
                node_rows = [{"ID": n["id"], "Label": n["label"], "Type": n["type"]} for n in nodes]
                st.dataframe(node_rows, use_container_width=True)

            with st.expander("🔗 Edges Table"):
                if edges:
                    edge_rows = [{"Source": e["source"], "Target": e["target"], "Type": e["type"]} for e in edges]
                    st.dataframe(edge_rows, use_container_width=True)
                else:
                    st.info("No edges found.")

            with st.expander("📄 Raw JSON"):
                st.json(data)

        elif r:
            st.error(f"Error: {r.json().get('detail', r.text)}")


# ─── Ontology Page ────────────────────────────────────────────────────────────
def _ontology_schema_html(entity_types, rel_types):
    """Render a pyvis schema graph: entity nodes connected via relationship edges."""
    from pyvis.network import Network
    import tempfile, os, math

    net = Network(height="420px", width="100%", bgcolor="#0e1117",
                  font_color="white", notebook=False, directed=True)

    # Place entity nodes in a circle
    n = max(len(entity_types), 1)
    for i, et in enumerate(entity_types):
        angle = 2 * math.pi * i / n
        x = 350 * math.cos(angle)
        y = 350 * math.sin(angle)
        color = _TYPE_COLORS[i % len(_TYPE_COLORS)]
        net.add_node(
            et, label=et, x=x, y=y, fixed=True,
            color={"background": color, "border": "#ffffff"},
            size=32,
            font={"size": 14, "color": "#ffffff",
                  "strokeWidth": 3, "strokeColor": "#0e1117"},
            borderWidth=2,
            title=f"<b>Entity Type</b><br>{et}",
            shape="dot",
        )

    # Add relationship edges — cycle through entity pairs
    if entity_types and rel_types:
        pairs = []
        for i in range(len(entity_types)):
            for j in range(i + 1, len(entity_types)):
                pairs.append((entity_types[i], entity_types[j]))

        for k, rt in enumerate(rel_types):
            if pairs:
                src, tgt = pairs[k % len(pairs)]
                net.add_edge(
                    src, tgt, label=rt, title=rt,
                    color={"color": "#555555", "hover": "#aaaaaa"},
                    width=1.5,
                    font={"size": 10, "color": "#cccccc",
                          "strokeWidth": 2, "strokeColor": "#0e1117",
                          "align": "middle"},
                    arrows={"to": {"enabled": True, "scaleFactor": 0.5}},
                    smooth={"type": "curvedCW", "roundness": 0.2},
                )

    net.set_options("""
    {
      "physics": {"enabled": false},
      "interaction": {"hover": true, "tooltipDelay": 80, "dragNodes": false}
    }
    """)

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False,
                                     mode="w", encoding="utf-8") as f:
        net.save_graph(f.name)
        html = open(f.name, encoding="utf-8").read()
    os.unlink(f.name)
    html = html.replace("background-color: white;", "background-color: #0e1117;")
    return html


def page_ontology():
    st.markdown("## 🧬 Ontology Viewer & Editor")

    r = api_get("/api/ontology")

    if r and r.status_code == 404:
        st.info("💡 No ontology yet. Upload and ingest a document first — it will be auto-generated.")
        return
    elif r and r.status_code != 200:
        st.error(f"Error: {r.json().get('detail', r.text)}")
        return

    ontology = r.json()
    entity_types = ontology.get("entity_types", [])
    rel_types    = ontology.get("relationship_types", [])
    approved     = ontology.get("approved", False)
    version      = ontology.get("version", "—")
    created      = ontology.get("created_at", "")[:19].replace("T", " ")

    # ── Header bar ────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Version", version)
    c2.metric("Entity Types", len(entity_types))
    c3.metric("Relationship Types", len(rel_types))
    c4.metric("Status", "✅ Approved" if approved else "🟡 Pending")
    st.caption(f"Last updated: {created}")
    st.markdown("---")

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📌 Entity Types", "🔗 Relationship Types", "🗺️ Schema Diagram", "✏️ Edit"]
    )

    # ── Tab 1 — Entity Types ──────────────────────────────────────────────────
    with tab1:
        if not entity_types:
            st.info("No entity types defined.")
        else:
            st.markdown(f"**{len(entity_types)} entity types** defined in this ontology:")
            st.markdown("")
            # Render as color-coded pill badges
            badge_html = ""
            for i, et in enumerate(entity_types):
                color = _TYPE_COLORS[i % len(_TYPE_COLORS)]
                badge_html += (
                    f'<span style="background:{color};color:#fff;padding:6px 16px;'
                    f'border-radius:20px;font-size:14px;font-weight:600;'
                    f'margin:4px;display:inline-block">{et}</span>'
                )
            st.markdown(badge_html, unsafe_allow_html=True)

            # Properties table
            props = ontology.get("properties", {})
            if props:
                st.markdown("#### Properties per entity type")
                rows = [
                    {"Entity Type": et, "Properties": ", ".join(props.get(et, [])) or "—"}
                    for et in entity_types
                ]
                st.dataframe(rows, use_container_width=True, hide_index=True)

    # ── Tab 2 — Relationship Types ────────────────────────────────────────────
    with tab2:
        if not rel_types:
            st.info("No relationship types defined.")
        else:
            st.markdown(f"**{len(rel_types)} relationship types** defined:")
            st.markdown("")
            badge_html = ""
            for i, rt in enumerate(rel_types):
                badge_html += (
                    f'<span style="background:#2d3748;color:#e2e8f0;padding:6px 16px;'
                    f'border:1px solid #4a5568;border-radius:6px;font-size:13px;'
                    f'font-family:monospace;margin:4px;display:inline-block">{rt}</span>'
                )
            st.markdown(badge_html, unsafe_allow_html=True)

    # ── Tab 3 — Schema Diagram ────────────────────────────────────────────────
    with tab3:
        if not entity_types:
            st.info("No entities to visualize yet.")
        else:
            st.caption("Entity types as nodes · relationship types as edge labels · static layout")
            try:
                html = _ontology_schema_html(entity_types, rel_types)
                st.components.v1.html(html, height=430, scrolling=False)
            except ImportError:
                st.warning("pyvis not available.")

    # ── Tab 4 — Edit ─────────────────────────────────────────────────────────
    with tab4:
        st.info("⚠️ Editing requires **admin** scope.")

        # ── AI-Assisted Refinement ────────────────────────────────────────────
        st.markdown("#### 🤖 AI-Assisted Refinement")
        feedback_input = st.text_area(
            "Optional feedback for AI (leave blank for auto-suggest)",
            height=80,
            placeholder="e.g. 'Add more granular relationship types for financial data'",
            key="ai_refine_feedback"
        )
        if st.button("✨ Suggest Improvements with AI", use_container_width=True):
            with st.spinner("LLM analysing current graph and suggesting ontology improvements..."):
                refine_r = api_post("/api/ontology/refine", json_data={"feedback": feedback_input or None})
            if refine_r and refine_r.status_code == 200:
                rd = refine_r.json()
                changes_text = rd.get("changes", "")
                st.success(f"✅ Refined to version **{rd['version']}**" + (f". Changes: {changes_text}" if changes_text else ""))
                st.rerun()
            elif refine_r:
                st.error(f"❌ {refine_r.json().get('detail', refine_r.text)}")

        st.markdown("---")

        with st.form("edit_ontology"):
            col_a, col_b = st.columns(2)
            with col_a:
                new_entities = st.text_area(
                    "Entity Types (one per line)",
                    value="\n".join(entity_types),
                    height=180,
                )
            with col_b:
                new_rels = st.text_area(
                    "Relationship Types (one per line)",
                    value="\n".join(rel_types),
                    height=180,
                )
            new_approved = st.checkbox("Mark as Approved", value=approved)
            save = st.form_submit_button("💾 Save Ontology", use_container_width=True)

        if save:
            payload = {
                "entity_types":       [e.strip() for e in new_entities.split("\n") if e.strip()],
                "relationship_types": [r.strip() for r in new_rels.split("\n") if r.strip()],
                "approved":           new_approved,
            }
            update_r = api_put("/api/ontology", json_data=payload)
            if update_r and update_r.status_code == 200:
                st.success("✅ Ontology updated!")
                st.rerun()
            elif update_r:
                st.error(f"❌ {update_r.json().get('detail', update_r.text)}")


# ─── Sidebar & Navigation ─────────────────────────────────────────────────────
def sidebar():
    with st.sidebar:
        st.markdown("## 🕸️ Graph RAG")
        st.markdown("---")

        if st.session_state.token:
            st.markdown(f"👤 **{st.session_state.username}**")
            st.caption(f"API: `{st.session_state.api_url}`")
            st.markdown("---")

            page = st.radio(
                "Navigation",
                ["📊 Dashboard", "📄 Upload Documents", "📂 Documents", "💬 Query", "🕸️ Graph View", "🧬 Ontology"],
                label_visibility="collapsed"
            )

            st.markdown("---")
            if st.button("🚪 Logout", use_container_width=True):
                st.session_state.token    = None
                st.session_state.username = None
                st.session_state.chat_history = []
                st.rerun()

            return page
        return None


# ─── Main App ─────────────────────────────────────────────────────────────────
def main():
    page = sidebar()

    if not st.session_state.token:
        page_login()
        return

    if page == "📊 Dashboard":
        page_dashboard()
    elif page == "📄 Upload Documents":
        page_upload()
    elif page == "📂 Documents":
        page_documents()
    elif page == "💬 Query":
        page_query()
    elif page == "🕸️ Graph View":
        page_graph()
    elif page == "🧬 Ontology":
        page_ontology()


if __name__ == "__main__":
    main()
