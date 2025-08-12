import io, os, re, tempfile, streamlit as st
import xml.etree.ElementTree as ET
from lxml import etree

# ====== Your core functions (slightly trimmed to keep in one file) ======
def extract_numbered_elements(root, tag_name):
    numbers, texts = [], []
    for elem in root.iter():
        if etree.QName(elem.tag).localname == tag_name:
            text = (elem.text or "").strip()
            texts.append(text)
            match = re.match(r"(\d+)[\.\s\t\u200B]+", text)
            numbers.append(int(match.group(1)) if match else None)
    return texts, numbers

def extract_answer_keys(root):
    flat_numbers, texts = [], []
    for elem in root.iter():
        if etree.QName(elem.tag).localname == "Answer":
            text = (elem.text or "").strip()
            texts.append(text)
            matches = re.findall(r"(\d+)\.\s*\(([a-eA-E])\)", text)
            for m in matches: flat_numbers.append(int(m[0]))
    return texts, flat_numbers

def detect_issues(numbers):
    issues = {"missing": [], "duplicates": [], "sequence_errors": []}
    valid = [n for n in numbers if isinstance(n, int)]
    if valid:
        expected = list(range(1, max(valid) + 1))
        issues["missing"] = sorted(set(expected) - set(valid))
    issues["duplicates"] = sorted({x for x in valid if valid.count(x) > 1})
    for i in range(len(valid) - 1):
        if valid[i + 1] != valid[i] + 1:
            issues["sequence_errors"].append((valid[i], valid[i + 1]))
    return issues

def extract_questions_with_options(xml_file_path):
    tree = ET.parse(xml_file_path)
    root = tree.getroot()
    questions_data, current_question, current_qno, current_options = [], None, None, []
    for elem in root.iter():
        if elem.tag == "Question":
            if current_question and current_options:
                questions_data.append((current_qno, current_question, list(current_options)))
            current_question = elem.text.strip() if elem.text else ""
            current_qno = current_question.split('.')[0].strip() if '.' in current_question else "?"
            current_options = []
        elif elem.tag == "Option-2":
            current_options.append(elem.text.strip() if elem.text else "")
    if current_question and current_options:
        questions_data.append((current_qno, current_question, current_options))
    return questions_data

def validate_options(questions_data):
    report_lines = []
    for qno, qtext, option_blocks in questions_data:
        full = " ".join(option_blocks).replace('\n',' ').replace('\t',' ')
        pattern = re.compile(r"\(([a-z])\)\s*(.*?)\s*(?=\([a-z]\)|$)")
        matches = pattern.findall(full)
        extracted, issues = {}, []
        for label, content in matches:
            if label in ['a','b','c','d']: extracted[label] = content.strip()
        all_labels = re.findall(r"\(([a-z])\)", full)
        invalid = [lbl for lbl in all_labels if lbl not in ['a','b','c','d']]
        if invalid: issues.append(f"Invalid option labels: {', '.join(sorted(set(invalid)))}")
        missing = [o for o in ['a','b','c','d'] if o not in extracted]
        if missing: issues.append(f"Missing options: {', '.join(missing)}")
        for label, content in extracted.items():
            if not content.strip(): issues.append(f"Option {label} is empty")
        seen = {}
        for label, content in extracted.items():
            if content in seen: issues.append(f"Duplicate content in {seen[content]} and {label}: '{content}'")
            else: seen[content] = label
        if issues:
            report_lines.append(f"Question {qno} issues:\n  - " + "\n  - ".join(issues))
    return "\n".join(report_lines) if report_lines else "No option issues found."

def build_sequence_report(tag, numbers, issues):
    lines = [f"Validation for {tag}s",
             f"Total numbered {tag}s found: {len([n for n in numbers if n is not None])}"]
    if issues["missing"]: lines.append(f"Missing {tag} numbers: {issues['missing']}")
    if issues["duplicates"]: lines.append(f"Duplicate {tag} numbers: {issues['duplicates']}")
    if issues["sequence_errors"]:
        for prev,curr in issues["sequence_errors"]:
            lines.append(f"After {tag} number {prev}, found {curr} — sequence is incorrect.")
    if not any(issues.values()):
        lines.append(f"All {tag}s are in correct sequence and unique.")
    return "\n".join(lines)

# ====== Streamlit UI ======
st.set_page_config(page_title="XML Editorial Validator", layout="wide")
st.title("🧰 XML Editorial Validator (Questions • Answers • Explanations • Options)")

uploaded = st.file_uploader("Upload an InDesign-exported XML file", type=["xml"])
run_btn = st.button("Run Validation", disabled=uploaded is None)

if run_btn and uploaded:
    with st.spinner("Parsing and validating..."):
        # Persist upload to a temp file for both lxml and ElementTree
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name

        try:
            tree = etree.parse(tmp_path)
            root = tree.getroot()

            # Part 1: sequences
            _, q_numbers = extract_numbered_elements(root, "Question")
            q_issues = detect_issues(q_numbers)
            _, e_numbers = extract_numbered_elements(root, "Explanations")
            e_issues = detect_issues(e_numbers)
            _, a_numbers = extract_answer_keys(root)
            a_issues = detect_issues(a_numbers)

            seq_report = "\n\n".join([
                build_sequence_report("Question", q_numbers, q_issues),
                build_sequence_report("Explanations", e_numbers, e_issues),
                build_sequence_report("Answer", a_numbers, a_issues),
            ])

            # Part 2: options
            questions_data = extract_questions_with_options(tmp_path)
            option_report = validate_options(questions_data)

            # Output
            st.subheader("Results")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### Sequence & Numbering")
                st.code(seq_report, language="text")
            with col2:
                st.markdown("### Option Integrity")
                st.code(option_report, language="text")

            # Download report
            final_report = f"{seq_report}\n\n---\n\n{option_report}\n"
            st.download_button(
                label="⬇️ Download Full Report (.txt)",
                file_name="validation_report.txt",
                data=final_report.encode("utf-8"),
                mime="text/plain"
            )
        finally:
            try: os.remove(tmp_path)
            except: pass
