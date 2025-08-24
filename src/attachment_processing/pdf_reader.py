import PyPDF2
import base64
from io import BytesIO

def read_pdf(data_base64):
    try:
        pdf_bytes = base64.urlsafe_b64decode(data_base64)
        reader = PyPDF2.PdfReader(BytesIO(pdf_bytes))
        text = ''
        for page in reader.pages:
            text += page.extract_text() + '\n'
        return text.strip()
    except Exception as e:
        return f"[Error reading PDF] {e}"
