import docx
import base64
from io import BytesIO

def read_docx(data_base64):
    try:
        doc_bytes = base64.urlsafe_b64decode(data_base64)
        doc_file = BytesIO(doc_bytes)
        doc = docx.Document(doc_file)
        text = '\n'.join([p.text for p in doc.paragraphs])
        return text.strip()
    except Exception as e:
        return f"[Error reading DOCX] {e}"
