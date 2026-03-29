import streamlit as st
import json
import re
import time
from io import BytesIO
from pathlib import Path

import pandas as pd
from pypdf import PdfReader
from docx import Document as DocxDocument

from openai import OpenAI

# -----------------------
# CONFIG
# -----------------------
st.set_page_config(page_title="IDP", layout="wide")

client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# -----------------------
# SESSION STATE
# -----------------------
for key in ["text", "doc_type", "data", "recommendations"]:
    if key not in st.session_state:
        st.session_state[key] = None

if "metrics" not in st.session_state:
    st.session_state.metrics = {"tokens": 0, "times": []}

# -----------------------
# UI HEADER
# -----------------------
st.title("📄 Intelligent Document Processor")

# -----------------------
# FILE UPLOAD
# -----------------------
file = st.file_uploader(
    "Upload document",
    type=["pdf", "txt", "docx", "png", "jpg", "jpeg"]
)

# -----------------------
# HELPERS
# -----------------------

def call_llm(prompt):
    start = time.time()

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    content = response.choices[0].message.content
    duration = time.time() - start

    st.session_state.metrics["times"].append(duration)
    st.session_state.metrics["tokens"] += len(prompt) // 4

    return content


def extract_text(file):
    suffix = Path(file.name).suffix.lower()

    if suffix == ".txt":
        return file.read().decode("utf-8", errors="ignore")

    elif suffix == ".pdf":
        reader = PdfReader(file)
        return "\n".join([p.extract_text() or "" for p in reader.pages])

    elif suffix == ".docx":
        doc = DocxDocument(file)
        return "\n".join([p.text for p in doc.paragraphs])

    else:
        return "Image uploaded (text extraction not implemented)"


def detect_doc_type(text):
    prompt = f"""
Classify into ONE:
Resume, Invoice, Report, Ticket, Other

{text[:2000]}
"""
    return call_llm(prompt).strip().lower()


def extract_json(text, doc_type):
    prompt = f"""
Extract structured JSON.

Doc Type: {doc_type}

Rules:
- Return ONLY JSON
- No explanation

{text[:4000]}
"""

    raw = call_llm(prompt)

    try:
        return json.loads(raw)
    except:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"error": "Invalid JSON", "raw": raw[:300]}


def generate_recommendations(doc_type, data):
    prompt = f"""
Give 3-5 actionable recommendations.

Type: {doc_type}
Data: {json.dumps(data)}

Plain text only.
"""
    return call_llm(prompt)


def json_to_excel(data):
    rows = []

    def flatten(prefix, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                flatten(f"{prefix}.{k}" if prefix else k, v)
        else:
            rows.append([prefix, str(obj)])

    flatten("", data)

    df = pd.DataFrame(rows, columns=["Field", "Value"])

    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    return buffer.getvalue()


# -----------------------
# PROCESS
# -----------------------
if file:

    st.info("Processing...")

    text = extract_text(file)
    st.session_state.text = text

    doc_type = detect_doc_type(text)
    st.session_state.doc_type = doc_type

    data = extract_json(text, doc_type)
    st.session_state.data = data

    recs = generate_recommendations(doc_type, data)
    st.session_state.recommendations = recs

    st.success(f"Detected: {doc_type.upper()}")

# -----------------------
# TABS
# -----------------------
tab1, tab2, tab3, tab4 = st.tabs(["Preview", "JSON", "Recommendations", "Metrics"])

# PREVIEW
with tab1:
    if file:
        st.text_area("Text", st.session_state.text, height=300)

# JSON
with tab2:
    if st.session_state.data:
        st.json(st.session_state.data)

        st.download_button(
            "Download JSON",
            json.dumps(st.session_state.data, indent=2),
            "data.json"
        )

        excel = json_to_excel(st.session_state.data)

        st.download_button(
            "Download Excel",
            excel,
            "data.xlsx"
        )

# RECOMMENDATIONS
with tab3:
    if st.session_state.recommendations:
        st.text_area("AI Insights", st.session_state.recommendations, height=200)

# METRICS
with tab4:
    times = st.session_state.metrics["times"]

    if times:
        st.metric("LLM Calls", len(times))
        st.metric("Avg Response Time", round(sum(times)/len(times), 2))

        df = pd.DataFrame({"time": times})
        st.line_chart(df)
