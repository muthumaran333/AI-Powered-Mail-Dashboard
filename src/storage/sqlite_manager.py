# src/storage/sqlite_manager.py

import sqlite3
from pathlib import Path
import threading
from typing import List, Dict, Optional, Tuple, Any

DB_PATH = Path("storage/mailmind.db")
DB_PATH.parent.mkdir(exist_ok=True)


class SQLiteManager:
    """
    Thread-safe singleton SQLite manager for MailMind.

    Features:
    - Rich schema with categories (Inbox, Sent, Drafts, Promotions, Important, No Reply, Other).
    - Upserts emails by gmail_id (updates thread_id, labels, category, body, etc).
    - Persists attachment metadata (+ optional blob).
    - Sync metadata KV store (last_page_token, last_sync_time, etc).
    - Filters, pagination, unread counts, category stats.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
                cls._instance.conn.row_factory = sqlite3.Row
                cls._instance.cursor = cls._instance.conn.cursor()
                cls._instance._create_tables()
                cls._instance._enable_foreign_keys()
            return cls._instance

    # ---------------------------------------------------------------------
    # Schema
    # ---------------------------------------------------------------------
    def _enable_foreign_keys(self):
        self.cursor.execute("PRAGMA foreign_keys = ON;")
        self.conn.commit()

    def _create_tables(self):
        """Create database tables if they don't exist."""
        # Emails
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gmail_id TEXT UNIQUE,
                thread_id TEXT,
                history_id TEXT,
                sender TEXT,
                to_recipients TEXT,
                subject TEXT,
                date TEXT,
                snippet TEXT,
                body TEXT,
                labels TEXT,           -- CSV of Gmail labelIds
                category TEXT,          -- Derived: Inbox, Sent, Drafts, Promotions, Important, No Reply, Other
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_read INTEGER DEFAULT 0
            );
            """
        )

        # Attachments
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_id INTEGER NOT NULL,
                filename TEXT,
                size INTEGER,
                content_preview TEXT,
                content BLOB,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (email_id, filename, size),
                FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE CASCADE
            );
            """
        )

        # Metadata (KV store)
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )

        # Indexes
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_gmail_id ON emails(gmail_id);")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_thread_id ON emails(thread_id);")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_date ON emails(date);")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender);")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_category ON emails(category);")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_is_read ON emails(is_read);")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_attachments_email_id ON attachments(email_id);")

        self.conn.commit()

    # ---------------------------------------------------------------------
    # Sync Metadata
    # ---------------------------------------------------------------------
    def update_sync_metadata(self, key: str, value: str) -> None:
        self.cursor.execute(
            """
            INSERT INTO sync_metadata(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value;
            """,
            (key, value),
        )
        self.conn.commit()

    def get_sync_metadata(self, key: str) -> Optional[str]:
        self.cursor.execute("SELECT value FROM sync_metadata WHERE key = ?;", (key,))
        row = self.cursor.fetchone()
        return row["value"] if row else None

    def get_fetch_metadata(self) -> Dict[str, Any]:
        """Convenience helper for last token & counters."""
        return {
            "last_fetch_token": self.get_sync_metadata("last_page_token"),
            "total_emails_fetched": int(self.get_sync_metadata("total_emails_fetched") or "0"),
            "last_fetch_time": self.get_sync_metadata("last_sync_time"),
        }

    def update_fetch_metadata(self, page_token: Optional[str] = None, emails_fetched: int = 0) -> None:
        if page_token is not None:
            self.update_sync_metadata("last_page_token", page_token)
        current = int(self.get_sync_metadata("total_emails_fetched") or "0")
        self.update_sync_metadata("total_emails_fetched", str(current + max(0, emails_fetched)))

    # ---------------------------------------------------------------------
    # Email & Attachment Upserts
    # ---------------------------------------------------------------------
    def upsert_email(
        self,
        *,
        gmail_id: str,
        thread_id: Optional[str],
        history_id: Optional[str],
        sender: str,
        to_recipients: str,
        subject: str,
        date: str,
        snippet: str,
        body: str,
        labels: str,
        category: str,
        is_read: Optional[int] = None,
    ) -> int:
        """
        Insert or update an email by gmail_id. Returns local email id.
        """
        labels = labels or ""
        to_recipients = to_recipients or ""
        category = category or "Other"
        is_read_val = 1 if (is_read and int(is_read) == 1) else 0

        self.cursor.execute(
            """
            INSERT INTO emails (
                gmail_id, thread_id, history_id, sender, to_recipients,
                subject, date, snippet, body, labels, category, is_read, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(gmail_id) DO UPDATE SET
                thread_id = excluded.thread_id,
                history_id = excluded.history_id,
                sender = excluded.sender,
                to_recipients = excluded.to_recipients,
                subject = excluded.subject,
                date = excluded.date,
                snippet = excluded.snippet,
                body = excluded.body,
                labels = excluded.labels,
                category = excluded.category,
                is_read = CASE
                    WHEN excluded.is_read IS NOT NULL THEN excluded.is_read
                    ELSE emails.is_read
                END,
                updated_at = CURRENT_TIMESTAMP;
            """,
            (
                gmail_id,
                thread_id,
                history_id,
                sender,
                to_recipients,
                subject,
                date,
                snippet,
                body,
                labels,
                category,
                is_read_val,
            ),
        )
        self.conn.commit()

        self.cursor.execute("SELECT id FROM emails WHERE gmail_id = ?;", (gmail_id,))
        return int(self.cursor.fetchone()["id"])

    def insert_attachment(
        self,
        email_id: int,
        filename: str,
        content: Optional[bytes],
        content_preview: Optional[str],
        size: Optional[int] = None,
    ) -> Optional[int]:
        try:
            size = size if size is not None else (len(content) if content else 0)
            self.cursor.execute(
                """
                INSERT INTO attachments (email_id, filename, size, content_preview, content)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(email_id, filename, size) DO UPDATE SET
                    content_preview = COALESCE(excluded.content_preview, attachments.content_preview),
                    content = COALESCE(excluded.content, attachments.content);
                """,
                (email_id, filename or "unknown", size, content_preview or "", content),
            )
            self.conn.commit()
            self.cursor.execute(
                "SELECT id FROM attachments WHERE email_id = ? AND filename = ? AND size = ?;",
                (email_id, filename or "unknown", size),
            )
            row = self.cursor.fetchone()
            return int(row["id"]) if row else None
        except Exception as e:
            print(f"Error inserting attachment: {e}")
            return None

    # ---------------------------------------------------------------------
    # Reads / Stats / Filters
    # ---------------------------------------------------------------------
    

    def get_total_email_count(self, category=None, sender_filter=None, subject_filter=None, include_unread_only=False):
        """Get total email count with filtering options"""
        try:
            where_conditions = []
            params = []
            
            if category and category != "All":
                where_conditions.append("category = ?")
                params.append(category)
                
            if sender_filter:
                where_conditions.append("sender LIKE ?")
                params.append(f"%{sender_filter}%")
                
            if subject_filter:
                where_conditions.append("subject LIKE ?")
                params.append(f"%{subject_filter}%")
                
            if include_unread_only:
                where_conditions.append("is_read = 0")
            
            where_clause = ""
            if where_conditions:
                where_clause = "WHERE " + " AND ".join(where_conditions)
            
            query = f"SELECT COUNT(*) as count FROM emails {where_clause}"
            self.cursor.execute(query, params)
            
            result = self.cursor.fetchone()
            return result['count'] if result else 0
            
        except Exception as e:
            print(f"Error getting email count: {e}")
            return 0





    def get_unread_count(self, category: Optional[str] = None) -> int:
        if category:
            self.cursor.execute(
                "SELECT COUNT(*) AS total FROM emails WHERE is_read = 0 AND category = ?;", (category,)
            )
        else:
            self.cursor.execute("SELECT COUNT(*) AS total FROM emails WHERE is_read = 0;")
        return int(self.cursor.fetchone()["total"])

    def mark_email_as_read(self, email_id: int, read: bool = True) -> None:
        self.cursor.execute(
            "UPDATE emails SET is_read = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (1 if read else 0, email_id),
        )
        self.conn.commit()

    def update_email_labels_and_category(self, gmail_id: str, labels_csv: str, category: str) -> None:
        self.cursor.execute(
            """
            UPDATE emails
            SET labels = ?, category = ?, updated_at = CURRENT_TIMESTAMP
            WHERE gmail_id = ?;
            """,
            (labels_csv or "", category or "Other", gmail_id),
        )
        self.conn.commit()

    def delete_email(self, email_id: int) -> None:
        self.cursor.execute("DELETE FROM emails WHERE id = ?;", (email_id,))
        self.conn.commit()

    def search_emails(self, query: str, limit: int = 60) -> List[Dict]:
        like = f"%{query}%"
        self.cursor.execute(
            """
            SELECT * FROM emails
            WHERE subject LIKE ? OR sender LIKE ? OR to_recipients LIKE ? OR body LIKE ?
            ORDER BY date DESC
            LIMIT ?;
            """,
            (like, like, like, like, limit),
        )
        return [dict(r) for r in self.cursor.fetchall()]

    # ---------------------------------------------------------------------
    # Pagination
    # ---------------------------------------------------------------------
    def get_emails_paginated(
        self,
        *,
        page: int,
        page_size: int,
        category: Optional[str] = None,
        sender_filter: Optional[str] = None,
        subject_filter: Optional[str] = None,
        include_unread_only: bool = False,
    ) -> Tuple[List[Dict], int]:
        where = []
        params: List[Any] = []

        if category:
            where.append("category = ?")
            params.append(category)

        if sender_filter:
            where.append("sender LIKE ?")
            params.append(f"%{sender_filter}%")

        if subject_filter:
            where.append("subject LIKE ?")
            params.append(f"%{subject_filter}%")

        if include_unread_only:
            where.append("is_read = 0")

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""

        # Count
        self.cursor.execute(f"SELECT COUNT(*) AS total FROM emails {where_clause};", params)
        total = int(self.cursor.fetchone()["total"])

        # Page
        offset = max(0, (page - 1) * page_size)
        self.cursor.execute(
            f"""
            SELECT * FROM emails
            {where_clause}
            ORDER BY date DESC
            LIMIT ? OFFSET ?;
            """,
            (*params, page_size, offset),
        )
        return [dict(r) for r in self.cursor.fetchall()], total

    # ---------------------------------------------------------------------
    # No Reply detection
    # ---------------------------------------------------------------------
    def has_incoming_after(self, thread_id: str, after_date: str) -> bool:
        if not thread_id:
            return False
        self.cursor.execute(
            """
            SELECT 1 FROM emails
            WHERE thread_id = ?
              AND date > ?
              AND (labels IS NULL OR instr(labels, 'SENT') = 0)
            LIMIT 1;
            """,
            (thread_id, after_date),
        )
        return self.cursor.fetchone() is not None

    def has_reply(self, thread_id: Optional[str], sent_date: str) -> bool:
        return self.has_incoming_after(thread_id or "", sent_date)

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------
    def get_unique_senders(self) -> List[str]:
        self.cursor.execute("SELECT DISTINCT sender FROM emails ORDER BY sender;")
        return [r["sender"] for r in self.cursor.fetchall()]

    def close(self):
        if hasattr(self, "conn"):
            self.conn.close()


# ---------------------------------------------------------------------
# Gmail Label → Category Mapper
# ---------------------------------------------------------------------
def map_labels_to_category(labels: List[str]) -> str:
    """Convert Gmail API labels into one of our categories."""
    labels = set(labels or [])
    if "INBOX" in labels:
        return "Inbox"
    if "SENT" in labels:
        return "Sent"
    if "DRAFT" in labels:
        return "Drafts"
    if "CATEGORY_PROMOTIONS" in labels:
        return "Promotions"
    if "IMPORTANT" in labels:
        return "Important"
    return "Other"


