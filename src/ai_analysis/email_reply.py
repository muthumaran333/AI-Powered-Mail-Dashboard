# src/ai_analysis/email_reply.py

import base64
import email.mime.text
import email.mime.multipart
from datetime import datetime
from typing import Optional, Dict, List
import re
import json
from bs4 import BeautifulSoup

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.auth.gmail_auth import authenticate_gmail
from src.storage.sqlite_manager import SQLiteManager

from utils.logger import get_logger

logger = get_logger(__name__)   # name = "services.email_service"




class AIEmailReply:
    """AI-powered email reply system with draft generation and sending"""
    
    def __init__(self):
        self.db = SQLiteManager()
        self.gmail_service = None
        self._setup_gmail_service()
        self._setup_ai_model()
        self._create_reply_tables()
    
    def _setup_gmail_service(self):
        """Initialize Gmail service for sending emails"""
        try:
            self.gmail_service = authenticate_gmail()
            logger.info("✅ Gmail service for replies initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gmail service: {e}")
            raise
    
    def _setup_ai_model(self):
        """Initialize AI model for reply generation"""
        try:
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.3,  # Slightly higher for more creative replies
                max_tokens=1024,
                timeout=30,
            )
            logger.info("✅ AI model for reply generation initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize AI model: {e}")
            raise
    
    def _create_reply_tables(self):
        """Create tables for tracking sent replies"""
        try:
            self.db.cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_email_id INTEGER NOT NULL,
                    reply_gmail_id TEXT,
                    reply_subject TEXT,
                    reply_body TEXT,
                    reply_type TEXT, -- ai_generated, manual, edited_ai
                    sent_status TEXT, -- draft, sent, failed
                    sent_timestamp DATETIME,
                    created_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(original_email_id) REFERENCES emails(id) ON DELETE CASCADE
                );
            """)
            
            # Add index for faster lookups
            self.db.cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_replies_original_email 
                ON email_replies(original_email_id);
            """)
            
            self.db.conn.commit()
            logger.info("✅ Reply tracking tables created/verified")
            
        except Exception as e:
            logger.error(f"❌ Failed to create reply tables: {e}")
    
    def generate_ai_reply(self, email_data: Dict, reply_type: str = "standard") -> Optional[str]:
        """Generate AI reply for an email"""
        try:
            logger.info(f"🤖 Generating AI reply for email: {email_data.get('subject', '')[:50]}...")
            
            # Get email analysis for context
            analysis = self._get_email_analysis(email_data['id'])
            
            # Prepare context for reply generation
            context = self._prepare_reply_context(email_data, analysis, reply_type)
            
            # Generate reply using AI
            reply_content = self._generate_reply_content(context, reply_type)
            
            logger.info("✅ AI reply generated successfully")
            return reply_content
            
        except Exception as e:
            logger.error(f"❌ Failed to generate AI reply: {e}")
            return None
    
    def _get_email_analysis(self, email_id: int) -> Optional[Dict]:
        """Get email analysis from database"""
        try:
            self.db.cursor.execute("SELECT * FROM email_analysis WHERE email_id = ?", (email_id,))
            row = self.db.cursor.fetchone()
            if row:
                analysis = dict(row)
                # Parse JSON fields
                analysis['suggested_actions'] = json.loads(analysis.get('suggested_actions', '[]'))
                analysis['key_topics'] = json.loads(analysis.get('key_topics', '[]'))
                return analysis
            return None
        except Exception as e:
            logger.error(f"❌ Failed to get email analysis: {e}")
            return None
    
    def _prepare_reply_context(self, email_data: Dict, analysis: Optional[Dict], reply_type: str) -> Dict:
        """Prepare context for reply generation"""
        return {
            'original_email': {
                'subject': email_data.get('subject', ''),
                'sender': email_data.get('sender', ''),
                'date': email_data.get('date', ''),
                'body': email_data.get('body', ''),
                'snippet': email_data.get('snippet', '')
            },
            'analysis': analysis,
            'reply_type': reply_type,
            'recipient_info': self._extract_sender_info(email_data.get('sender', ''))
        }
    
    def _extract_sender_info(self, sender: str) -> Dict:
        """Extract sender information from email address"""
        email_match = re.search(r'<(.+?)>', sender)
        email_addr = email_match.group(1) if email_match else sender
        
        name_match = re.match(r'^([^<]+)<', sender.strip())
        name = name_match.group(1).strip().strip('"') if name_match else email_addr.split('@')[0]
        
        return {
            'name': name,
            'email': email_addr,
            'domain': email_addr.split('@')[1] if '@' in email_addr else ''
        }
    
    def _generate_reply_content(self, context: Dict, reply_type: str) -> str:
        """Generate reply content using AI"""
        
        # Different prompts for different reply types
        reply_prompts = {
            'standard': self._get_standard_reply_prompt(),
            'acknowledge': self._get_acknowledge_reply_prompt(),
            'decline': self._get_decline_reply_prompt(),
            'request_info': self._get_info_request_prompt(),
            'follow_up': self._get_follow_up_prompt()
        }
        
        system_prompt = reply_prompts.get(reply_type, reply_prompts['standard'])
        
        # Build user prompt with context
        user_prompt = self._build_user_prompt(context)
        
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = self.llm.invoke(messages)
            return response.content.strip()
            
        except Exception as e:
            logger.error(f"❌ AI reply generation failed: {e}")
            return self._get_fallback_reply(context)
    
    def _get_standard_reply_prompt(self) -> str:
        return """You are a professional email assistant. Generate a thoughtful, appropriate reply to the given email.

Guidelines:
- Be professional but warm
- Address the main points from the original email
- Keep it concise but complete
- Use proper email etiquette
- Match the tone of the original sender
- Include next steps if applicable
- Don't repeat information unnecessarily

Generate only the email body, not subject line or signatures."""

    def _get_acknowledge_reply_prompt(self) -> str:
        return """Generate a brief acknowledgment reply that confirms receipt and understanding.

Guidelines:
- Acknowledge receipt of the email
- Confirm understanding of key points
- Provide timeline if action is needed
- Keep it short and professional
- Express appreciation if appropriate"""

    def _get_decline_reply_prompt(self) -> str:
        return """Generate a polite decline/rejection email.

Guidelines:
- Be respectful and diplomatic
- Provide a brief reason if appropriate
- Thank them for the opportunity/request
- Suggest alternatives if possible
- Keep the door open for future opportunities
- Be firm but kind"""

    def _get_info_request_prompt(self) -> str:
        return """Generate a professional request for additional information.

Guidelines:
- Clearly state what information is needed
- Explain why the information is important
- Provide context about the request
- Set a reasonable timeline
- Make it easy for them to respond
- Be specific about what you need"""

    def _get_follow_up_prompt(self) -> str:
        return """Generate a follow-up email for previous communication.

Guidelines:
- Reference previous communication
- Restate key points if needed
- Be persistent but not pushy
- Provide value or new information
- Include clear call to action
- Show understanding of their time constraints"""

    def _build_user_prompt(self, context: Dict) -> str:
        """Build user prompt with email context"""
        original = context['original_email']
        analysis = context.get('analysis', {})
        recipient = context['recipient_info']
        
        # Clean HTML content using BeautifulSoup
        body_text = self._clean_html_content(original['body'])
        snippet_text = self._clean_html_content(original['snippet'])
        
        prompt = f"""
Original Email Details:
- From: {original['sender']}
- Subject: {original['subject']}
- Date: {original['date']}

Recipient Information:
- Name: {recipient['name']}
- Email: {recipient['email']}
- Domain: {recipient['domain']}

Email Content:
{body_text[:1500] if body_text else snippet_text}

"""
        
        if analysis:
            prompt += f"""
AI Analysis Context:
- Priority: {analysis.get('priority_score', 'N/A')}/5
- Sentiment: {analysis.get('sentiment', 'neutral')}
- Action Required: {analysis.get('action_required', False)}
- Key Topics: {', '.join(analysis.get('key_topics', []))}
- Summary: {analysis.get('summary', '')}

"""

        prompt += f"""
Reply Type: {context['reply_type']}

Generate an appropriate reply email body based on the above context."""

        return prompt
    
    def _clean_html_content(self, html_content: str) -> str:
        """Clean HTML content using BeautifulSoup"""
        if not html_content:
            return ""
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get text and clean it up
            text = soup.get_text()
            
            # Break into lines and remove leading and trailing space on each
            lines = (line.strip() for line in text.splitlines())
            
            # Break multi-headlines into a line each
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            
            # Drop blank lines
            text = ' '.join(chunk for chunk in chunks if chunk)
            
            return text
        except Exception as e:
            logger.error(f"❌ Failed to clean HTML content: {e}")
            return html_content
    
    def _get_fallback_reply(self, context: Dict) -> str:
        """Provide fallback reply when AI fails"""
        sender_name = context['recipient_info']['name']
        
        return f"""Dear {sender_name},

Thank you for your email. I have received your message and will review it carefully.

I will get back to you with a proper response shortly.

Best regards"""
    
    def create_reply_draft(self, email_data: Dict, reply_content: str, reply_type: str = "ai_generated") -> Optional[int]:
        """Create a reply draft in Gmail"""
        try:
            # Prepare reply message
            reply_message = self._prepare_reply_message(email_data, reply_content)
            
            # Create draft in Gmail
            draft_response = self.gmail_service.users().drafts().create(
                userId="me",
                body={"message": reply_message}
            ).execute()
            
            draft_id = draft_response['id']
            gmail_message_id = draft_response['message']['id']
            
            # Store in database
            reply_record_id = self._store_reply_record(
                email_data['id'],
                gmail_message_id,
                f"Re: {email_data.get('subject', '')}",
                reply_content,
                reply_type,
                "draft"
            )
            
            logger.info(f"✅ Reply draft created with ID: {draft_id}")
            return reply_record_id
            
        except Exception as e:
            logger.error(f"❌ Failed to create reply draft: {e}")
            return None
    
    def send_reply(self, email_data: Dict, reply_content: str, reply_type: str = "ai_generated") -> Optional[int]:
        """Send a reply email directly"""
        try:
            # Prepare reply message
            reply_message = self._prepare_reply_message(email_data, reply_content)
            
            # Send email
            send_response = self.gmail_service.users().messages().send(
                userId="me",
                body=reply_message
            ).execute()
            
            gmail_message_id = send_response['id']
            
            # Store in database
            reply_record_id = self._store_reply_record(
                email_data['id'],
                gmail_message_id,
                f"Re: {email_data.get('subject', '')}",
                reply_content,
                reply_type,
                "sent"
            )
            
            # Mark original email as read
            self.db.mark_email_as_read(email_data['id'], True)
            
            logger.info(f"✅ Reply sent successfully with ID: {gmail_message_id}")
            return reply_record_id
            
        except Exception as e:
            logger.error(f"❌ Failed to send reply: {e}")
            return None
    
    def _prepare_reply_message(self, email_data: Dict, reply_content: str) -> Dict:
        """Prepare Gmail message format for reply"""
        
        # Extract sender email for reply-to
        sender_email = self._extract_email_address(email_data.get('sender', ''))
        
        # Create MIME message
        msg = email.mime.multipart.MIMEMultipart()
        msg['To'] = sender_email
        msg['Subject'] = f"Re: {email_data.get('subject', '')}"
        
        # Add In-Reply-To and References headers if available
        gmail_id = email_data.get('gmail_id')
        if gmail_id:
            msg['In-Reply-To'] = f"<{gmail_id}>"
            msg['References'] = f"<{gmail_id}>"
        
        # Add body
        msg.attach(email.mime.text.MIMEText(reply_content, 'plain', 'utf-8'))
        
        # Encode message
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
        
        return {'raw': raw_message}
    
    def _extract_email_address(self, sender: str) -> str:
        """Extract email address from sender field"""
        if not sender:
            return ""
        
        # Extract email from "Name <email>" format
        email_match = re.search(r'<(.+?)>', sender)
        if email_match:
            return email_match.group(1)
        
        # If no brackets, assume the whole string is email
        return sender.strip()
    
    def _store_reply_record(self, original_email_id: int, gmail_id: str, subject: str, 
                          body: str, reply_type: str, status: str) -> int:
        """Store reply record in database"""
        try:
            self.db.cursor.execute("""
                INSERT INTO email_replies 
                (original_email_id, reply_gmail_id, reply_subject, reply_body, 
                 reply_type, sent_status, sent_timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                original_email_id,
                gmail_id,
                subject,
                body,
                reply_type,
                status,
                datetime.now().isoformat() if status == "sent" else None
            ))
            
            reply_id = self.db.cursor.lastrowid
            self.db.conn.commit()
            
            return reply_id
            
        except Exception as e:
            logger.error(f"❌ Failed to store reply record: {e}")
            return 0
    
    def get_reply_stats(self) -> Dict:
        """Get reply statistics"""
        try:
            # Total replies sent
            self.db.cursor.execute("SELECT COUNT(*) as total FROM email_replies WHERE sent_status = 'sent'")
            total_sent = self.db.cursor.fetchone()['total']
            
            # Total drafts created
            self.db.cursor.execute("SELECT COUNT(*) as total FROM email_replies WHERE sent_status = 'draft'")
            total_drafts = self.db.cursor.fetchone()['total']
            
            # AI generated vs manual
            self.db.cursor.execute("SELECT reply_type, COUNT(*) as count FROM email_replies GROUP BY reply_type")
            reply_type_dist = {row['reply_type']: row['count'] for row in self.db.cursor.fetchall()}
            
            # Recent reply activity (last 7 days)
            self.db.cursor.execute("""
                SELECT COUNT(*) as count 
                FROM email_replies 
                WHERE sent_status = 'sent' 
                AND datetime(sent_timestamp) >= datetime('now', '-7 days')
            """)
            recent_replies = self.db.cursor.fetchone()['count']
            
            return {
                'total_replies_sent': total_sent,
                'total_drafts_created': total_drafts,
                'reply_type_distribution': reply_type_dist,
                'recent_replies_7d': recent_replies,
                'total_replies': total_sent + total_drafts
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get reply stats: {e}")
            return {
                'total_replies_sent': 0,
                'total_drafts_created': 0,
                'reply_type_distribution': {},
                'recent_replies_7d': 0,
                'total_replies': 0
            }
    
    def get_replies_for_email(self, email_id: int) -> List[Dict]:
        """Get all replies for a specific email"""
        try:
            self.db.cursor.execute("""
                SELECT * FROM email_replies 
                WHERE original_email_id = ? 
                ORDER BY created_timestamp DESC
            """, (email_id,))
            
            return [dict(row) for row in self.db.cursor.fetchall()]
            
        except Exception as e:
            logger.error(f"❌ Failed to get replies for email {email_id}: {e}")
            return []
    
    def delete_reply(self, reply_id: int) -> bool:
        """Delete a reply record"""
        try:
            self.db.cursor.execute("DELETE FROM email_replies WHERE id = ?", (reply_id,))
            self.db.conn.commit()
            return self.db.cursor.rowcount > 0
            
        except Exception as e:
            logger.error(f"❌ Failed to delete reply {reply_id}: {e}")
            return False
    
    def update_reply_status(self, reply_id: int, new_status: str) -> bool:
        """Update reply status (e.g., from draft to sent)"""
        try:
            self.db.cursor.execute("""
                UPDATE email_replies 
                SET sent_status = ?, sent_timestamp = ? 
                WHERE id = ?
            """, (
                new_status,
                datetime.now().isoformat() if new_status == "sent" else None,
                reply_id
            ))
            
            self.db.conn.commit()
            return self.db.cursor.rowcount > 0
            
        except Exception as e:
            logger.error(f"❌ Failed to update reply status {reply_id}: {e}")
            return False

# Singleton instance
email_reply_system = AIEmailReply()