from streamlit import session_state as st_state
from langchain_openai import ChatOpenAI


def detect_document_type(text):

    # ------------------------------
    # SAFETY CHECK
    # ------------------------------
    if "api_key" not in st_state:
        return "other"

    llm = ChatOpenAI(
        model=st_state.get("model_choice", "gpt-4o-mini"),
        temperature=0,
        api_key=st_state["api_key"]
    )

    prompt = f"""
Classify document into ONE label:

resume
invoice
receipt
report
ticket
other

STRICT RULES:
- Return ONLY one word
- No explanation
- No sentence

{text[:2000]}
"""

    try:
        raw = llm.invoke(prompt).content.lower().strip()
    except Exception:
        return "other"

    # ------------------------------
    # ROBUST MATCHING
    # ------------------------------
    labels = ["resume", "invoice", "receipt", "report", "ticket"]

    for label in labels:
        if label in raw:
            return label

    return "other"

def extract_structured_json(text, doc_type):

    # ✅ Clean text
        clean_text = re.sub(r"[^\x00-\x7F]+", " ", text)
        clean_text = clean_text.replace("{", "").replace("}", "")

        # 🎯 Different prompt based on document type
        if doc_type == "resume":

            prompt = f"""
        You are a strict JSON generator.

        Return ONLY valid JSON.

        MANDATORY SCHEMA:
        {{
        "name": "",
        "email": "",
        "phone": "",
        "skills": [],
        "education": [],
        "experience": []
        }}

        RULES:
        - ALWAYS include "name"
        - Do not add extra keys

        Content:
        {clean_text[:4000]}
        """

        else:
            # ✅ Invoice / Report / Ticket → FULL EXTRACTION
            prompt = f"""
        Extract ALL possible key-value pairs from the document.

        Return ONLY valid JSON.

        RULES:
        - Capture every identifiable field
        - Preserve original field names where possible
        - Include nested structures if present
        - Do NOT summarize
        - Do NOT skip fields

        Examples:
        Invoice → invoice_number, date, total, vendor, line_items
        Report → title, author, summary, sections
        Ticket → issue, status, priority, requester

        Content:
        {clean_text[:4000]}
        """

        try:
            response = tracked_llm_call(prompt).content.replace("```json", "").replace("```", "").strip()
            parsed = safe_json_parse(response)

            # ✅ Ensure parsed is always a dictionary
            if isinstance(parsed, list):
                try:
                    merged = {}
                    for item in parsed:
                        if isinstance(item, dict):
                            merged.update(item)
                    parsed = merged
                except:
                    parsed = {"data": parsed}

            # AI fallback if name missing
            if doc_type == "resume" and isinstance(parsed, dict) and not parsed.get("name"):
                try:
                    fallback_prompt = f"""
            Extract only the full name of the person from this text.
            Return only the name. No explanation.

            {text[:2000]}
            """
                    fallback_name = tracked_llm_call(fallback_prompt).content.strip()
                    parsed["name"] = fallback_name
                except:
                    parsed["name"] = "candidate"

            # ✅ Optional: format name nicely
            if parsed.get("name"):
                parsed["name"] = parsed["name"].title()

            return parsed


        except Exception as e:
            return {
                "error": "LLM request failed",
                "details": str(e)[:300]
            }

def build_resume(data, template_file):
    summary = generate_resume_summary(data)

    # ------------------------------
    # LOAD TEMPLATE OR CREATE NEW
    # ------------------------------
    if template_file:

        if isinstance(template_file, bytes):
            temp = BytesIO(template_file)
            doc = DocxDocument(temp)
        else:
            path = save_temp_file(template_file)
            doc = DocxDocument(path)

    else:
        doc = DocxDocument()

    # ------------------------------
    # PLACEHOLDERS (ALWAYS RUN)
    # ------------------------------
    placeholders = {
        "{{name}}": data.get("name", ""),
        "{{email}}": data.get("email", ""),
        "{{phone}}": data.get("phone", ""),
        "{{summary}}": summary,
    }

    replace_placeholders(doc, placeholders)

    buffer = BytesIO()
    doc.save(buffer)

    return buffer.getvalue()

def json_to_kv_dataframe(data):
    rows = []

    def flatten(prefix, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                flatten(f"{prefix}.{k}" if prefix else k, v)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                flatten(f"{prefix}[{i}]", item)
        else:
            rows.append({"Field": prefix, "Value": json.dumps(obj) if isinstance(obj, (dict, list)) else str(obj)})

    flatten("", data)
    return pd.DataFrame(rows)



def generate_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='data')
    return output.getvalue()
