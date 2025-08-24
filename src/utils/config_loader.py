import os
from dotenv import load_dotenv

class Config:
    def __init__(self):
        load_dotenv()
        self.GOOGLE_CLIENT_SECRET_FILE = os.getenv("GOOGLE_CLIENT_SECRET_FILE")
        self.GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE")
        self.OPENAI_API_KEY = os.getenv("GOOGLE_API_KEY")
        self.CACHE_DIR = os.getenv("CACHE_DIR", "data/cache")
        self.ATTACHMENTS_DIR = os.getenv("ATTACHMENTS_DIR", "data/attachments")
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    def __repr__(self):
        return f"<Config GOOGLE_CLIENT_SECRET_FILE={self.GOOGLE_CLIENT_SECRET_FILE}, LOG_LEVEL={self.LOG_LEVEL}>"

config = Config()
