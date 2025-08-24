# ---------------- gmail_auth.py ----------------
import os
import logging
from pathlib import Path
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from src.utils.config_loader import config

logger = logging.getLogger(__name__)
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly',
              'https://www.googleapis.com/auth/gmail.modify',
              'https://www.googleapis.com/auth/gmail.compose',
              'https://www.googleapis.com/auth/gmail.send',
              ]

def authenticate_gmail():
    creds = None
    token_path = Path(config.GOOGLE_TOKEN_FILE)
    creds_path = Path(config.GOOGLE_CLIENT_SECRET_FILE)

    # Load token.json if exists
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            logger.info("Loaded Gmail credentials from token.json")
        except Exception as e:
            logger.warning(f"Failed to load token.json: {e}")

    # Refresh or run OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Gmail credentials...")
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                raise FileNotFoundError(f"{config.GOOGLE_CLIENT_SECRET_FILE} not found.")
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
            logger.info("OAuth flow completed.")
        # Save token.json
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
            logger.info(f"Saved new credentials to {token_path}")

    service = build('gmail', 'v1', credentials=creds)
    logger.info("Gmail API client created successfully.")
    return service

