import pandas as pd
import base64
from io import BytesIO

def read_excel(data_base64):
    try:
        excel_bytes = base64.urlsafe_b64decode(data_base64)
        excel_file = BytesIO(excel_bytes)
        df = pd.read_excel(excel_file, sheet_name=None)  # Read all sheets
        text = ''
        for sheet_name, sheet in df.items():
            text += f"Sheet: {sheet_name}\n{sheet.to_string(index=False)}\n\n"
        return text.strip()
    except Exception as e:
        return f"[Error reading Excel] {e}"
