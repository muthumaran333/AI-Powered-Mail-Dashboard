from PIL import Image
import base64
from io import BytesIO

def read_image(data_base64):
    try:
        img_bytes = base64.urlsafe_b64decode(data_base64)
        img = Image.open(BytesIO(img_bytes))
        return f"[Image] {img.format}, size={img.size}, mode={img.mode}"
    except Exception as e:
        return f"[Error reading Image] {e}"
