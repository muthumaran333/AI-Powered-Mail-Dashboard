# src/ai_analysis/email_summarizer.py

import os
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.prompts.chat import SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser, PydanticOutputParser
from langchain.schema import BaseOutputParser
import logging
from langsmith import traceable


from src.storage.sqlite_manager import SQLiteManager
from utils.logger import get_logger

logger = get_logger(__name__)   # name = "services.email_service"


@dataclass
class EmailSummary:
    """Data structure for email summary results"""
    email_id: int
    gmail_id: str
    brief_summary: str
    detailed_summary: str
    key_points: List[str]
    action_items: List[str]
    important_dates: List[str]
    mentioned_people: List[str]
    summary_type: str  # brief, detailed, bullet_points, executive
    word_count_original: int
    word_count_summary: int
    compression_ratio: float
    summary_timestamp: str
    processing_time_ms: int

class EmailSummaryOutputParser(BaseOutputParser):
    """Custom output parser for email summaries"""
    
    def parse(self, text: str) -> Dict:
        """Parse AI response to extract summary components"""
        try:
            # Try to parse as JSON first
            if text.strip().startswith('{') and text.strip().endswith('}'):
                return json.loads(text)
            
            # If not JSON, parse structured text
            lines = text.strip().split('\n')
            result = {
                'brief_summary': '',
                'detailed_summary': '',
                'key_points': [],
                'action_items': [],
                'important_dates': [],
                'mentioned_people': []
            }
            
            current_section = None
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Identify sections
                if 'brief summary:' in line.lower():
                    current_section = 'brief_summary'
                    result['brief_summary'] = line.split(':', 1)[1].strip()
                elif 'detailed summary:' in line.lower():
                    current_section = 'detailed_summary'
                    result['detailed_summary'] = line.split(':', 1)[1].strip()
                elif 'key points:' in line.lower():
                    current_section = 'key_points'
                elif 'action items:' in line.lower():
                    current_section = 'action_items'
                elif 'important dates:' in line.lower():
                    current_section = 'important_dates'
                elif 'mentioned people:' in line.lower():
                    current_section = 'mentioned_people'
                elif line.startswith('-') or line.startswith('•') or line.startswith('*'):
                    # List item
                    item = line[1:].strip()
                    if current_section and isinstance(result[current_section], list):
                        result[current_section].append(item)
                elif current_section and isinstance(result[current_section], str):
                    # Continue adding to string fields
                    result[current_section] += ' ' + line
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Failed to parse summary output: {e}")
            return {
                'brief_summary': text[:200] + '...' if len(text) > 200 else text,
                'detailed_summary': text,
                'key_points': [],
                'action_items': [],
                'important_dates': [],
                'mentioned_people': []
            }

class AIEmailSummarizer:
    """AI-powered email summarization using LangChain with advanced prompt templates"""
    
    def __init__(self):
        self.db = SQLiteManager()
        self._setup_ai_model()
        self._setup_prompt_templates()
        self._create_summary_tables()
        self.output_parser = EmailSummaryOutputParser()
        
    def _setup_ai_model(self):
        """Initialize Gemini 2.5 Flash model with LangChain"""
        try:
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.1,  # Low temperature for consistent summaries
                max_tokens=2048,
                timeout=30,
                max_retries=3,
            )
            logger.info("✅ Gemini 2.0 Flash model initialized for summarization")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini model: {e}")
            raise
    
    def _setup_prompt_templates(self):
        """Setup advanced prompt templates for different summary types"""
        
        # System message template
        self.system_template = SystemMessagePromptTemplate.from_template(
            """You are an expert email summarization AI assistant. Your role is to create clear, 
            concise, and actionable summaries of email content.

            Your capabilities include:
            - Extracting key information and main points
            - Identifying action items and deadlines
            - Recognizing important people and dates
            - Creating both brief and detailed summaries
            - Maintaining professional tone and accuracy

            Guidelines:
            - Focus on actionable information
            - Preserve important context and nuance
            - Use clear, professional language
            - Extract specific dates, names, and numbers accurately
            - Identify urgent or time-sensitive items
            - Maintain the sender's intent and tone"""
        )
        
        # Different summary type templates
        self.summary_templates = {
            'brief': PromptTemplate(
                input_variables=["email_content", "sender", "subject", "date"],
                template="""Create a BRIEF summary (max 2-3 sentences) of this email:

                From: {sender}
                Subject: {subject}
                Date: {date}
                
                Email Content:
                {email_content}
                
                Provide a concise summary that captures the main purpose and any urgent actions needed."""
            ),
            
            'detailed': PromptTemplate(
                input_variables=["email_content", "sender", "subject", "date"],
                template="""Create a DETAILED summary of this email with structured analysis:

                From: {sender}
                Subject: {subject}
                Date: {date}
                
                Email Content:
                {email_content}
                
                Please provide a comprehensive summary in JSON format:
                {{
                    "brief_summary": "2-3 sentence overview",
                    "detailed_summary": "Comprehensive paragraph summary",
                    "key_points": ["point 1", "point 2", "point 3"],
                    "action_items": ["action 1", "action 2"],
                    "important_dates": ["date 1", "date 2"],
                    "mentioned_people": ["person 1", "person 2"]
                }}"""
            ),
            
            'bullet_points': PromptTemplate(
                input_variables=["email_content", "sender", "subject", "date"],
                template="""Summarize this email in clear bullet points:

                From: {sender}
                Subject: {subject}
                Date: {date}
                
                Email Content:
                {email_content}
                
                Format as:
                Brief Summary: [1-2 sentences]
                
                Key Points:
                • Point 1
                • Point 2
                • Point 3
                
                Action Items:
                • Action 1 (if any)
                • Action 2 (if any)
                
                Important Dates:
                • Date 1 (if any)
                • Date 2 (if any)"""
            ),
            
            'executive': PromptTemplate(
                input_variables=["email_content", "sender", "subject", "date"],
                template="""Create an EXECUTIVE summary for leadership review:

                From: {sender}
                Subject: {subject}
                Date: {date}
                
                Email Content:
                {email_content}
                
                Focus on:
                1. Business impact and implications
                2. Decisions or approvals needed
                3. Strategic relevance
                4. Risk factors or opportunities
                5. Recommended next steps
                
                Keep it executive-level: high-impact information only."""
            )
        }
        
        # Create chat prompt template
        self.chat_template = ChatPromptTemplate.from_messages([
            self.system_template,
            HumanMessagePromptTemplate.from_template("{user_input}")
        ])
        
        logger.info("✅ Advanced prompt templates configured")
    
    def _create_summary_tables(self):
        """Create database tables for storing email summaries"""
        try:
            self.db.cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id INTEGER NOT NULL,
                    gmail_id TEXT NOT NULL,
                    brief_summary TEXT,
                    detailed_summary TEXT,
                    key_points TEXT, -- JSON array
                    action_items TEXT, -- JSON array
                    important_dates TEXT, -- JSON array
                    mentioned_people TEXT, -- JSON array
                    summary_type TEXT, -- brief, detailed, bullet_points, executive
                    word_count_original INTEGER,
                    word_count_summary INTEGER,
                    compression_ratio REAL,
                    summary_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    processing_time_ms INTEGER,
                    UNIQUE(email_id, summary_type),
                    FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE CASCADE
                );
            """)
            
            # Add summarization status column to emails table if not exists
            try:
                self.db.cursor.execute("""
                    ALTER TABLE emails 
                    ADD COLUMN ai_summarized BOOLEAN DEFAULT FALSE;
                """)
            except Exception:
                # Column probably already exists
                pass
            
            self.db.conn.commit()
            logger.info("✅ AI summarization tables created/verified")
            
        except Exception as e:
            logger.error(f"❌ Failed to create summary tables: {e}")
    


    @traceable(name="summarize_single_email")

    def summarize_email(self, email_data: Dict, summary_type: str = "detailed") -> Optional[EmailSummary]:
        """Summarize a single email with specified type"""
        start_time = time.time()
        
        try:
            email_id = email_data.get('id')
            gmail_id = email_data.get('gmail_id', email_data.get('id', ''))
            
            logger.info(f"📝 Summarizing email {email_id} ({summary_type}): {email_data.get('subject', '')[:50]}...")
            
            # Check if already summarized with this type
            if self._is_already_summarized(email_id, summary_type):
                logger.info(f"⏭️ Email {email_id} already summarized ({summary_type}), retrieving existing")
                return self._get_existing_summary(email_id, summary_type)
            
            # Prepare email content for summarization
            email_content = self._prepare_email_content(email_data)
            
            # Count original words
            word_count_original = len(email_content.split())
            
            # Generate summary using AI
            summary_results = self._generate_summary(email_data, summary_type)
            
            # Count summary words
            all_summary_text = ' '.join([
                summary_results.get('brief_summary', ''),
                summary_results.get('detailed_summary', ''),
                ' '.join(summary_results.get('key_points', [])),
                ' '.join(summary_results.get('action_items', []))
            ])
            word_count_summary = len(all_summary_text.split())
            
            # Calculate compression ratio
            compression_ratio = round((word_count_summary / word_count_original * 100), 2) if word_count_original > 0 else 0
            
            # Create summary object
            processing_time = int((time.time() - start_time) * 1000)
            
            summary = EmailSummary(
                email_id=email_id,
                gmail_id=gmail_id,
                brief_summary=summary_results.get('brief_summary', ''),
                detailed_summary=summary_results.get('detailed_summary', ''),
                key_points=summary_results.get('key_points', []),
                action_items=summary_results.get('action_items', []),
                important_dates=summary_results.get('important_dates', []),
                mentioned_people=summary_results.get('mentioned_people', []),
                summary_type=summary_type,
                word_count_original=word_count_original,
                word_count_summary=word_count_summary,
                compression_ratio=compression_ratio,
                summary_timestamp=datetime.now().isoformat(),
                processing_time_ms=processing_time
            )
            
            # Store in database
            self._store_summary(summary)
            
            # Mark email as summarized
            self._mark_email_summarized(email_id)
            
            logger.info(f"✅ Email {email_id} summarized successfully in {processing_time}ms (compression: {compression_ratio}%)")
            return summary
            
        except Exception as e:
            logger.error(f"❌ Failed to summarize email {email_data.get('id')}: {e}")
            return None
    
    def _prepare_email_content(self, email_data: Dict) -> str:
        """Prepare email content for summarization with HTML cleaning"""
        body = email_data.get('body', '')
        snippet = email_data.get('snippet', '')
        
        # Clean HTML content using BeautifulSoup
        clean_body = self._clean_html_content(body) if body else ""
        clean_snippet = self._clean_html_content(snippet) if snippet else ""
        
        # Use cleaned body if available, otherwise snippet
        content = clean_body if clean_body else clean_snippet
        
        # Limit content to avoid token limits (keep first 3000 chars)
        return content[:3000] if content else ""
    
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
    
    def _generate_summary(self, email_data: Dict, summary_type: str) -> Dict:
        """Generate summary using advanced prompt templates"""
        
        try:
            # Get the appropriate prompt template
            prompt_template = self.summary_templates.get(summary_type, self.summary_templates['detailed'])
            
            # Prepare email content
            email_content = self._prepare_email_content(email_data)
            sender = email_data.get('sender', 'Unknown')
            subject = email_data.get('subject', 'No Subject')
            date = email_data.get('date', '')
            
            # Format the prompt
            if summary_type == 'detailed':
                # Use chat template for detailed summaries
                formatted_prompt = prompt_template.format(
                    email_content=email_content,
                    sender=sender,
                    subject=subject,
                    date=date
                )
                
                # Create messages
                messages = self.chat_template.format_messages(user_input=formatted_prompt)
                
                # Get AI response
                response = self.llm.invoke(messages)
                
                # Parse the response
                summary_results = self.output_parser.parse(response.content)
                
            else:
                # Use simple prompt template for other types
                formatted_prompt = prompt_template.format(
                    email_content=email_content,
                    sender=sender,
                    subject=subject,
                    date=date
                )
                
                # Create simple message
                messages = [
                    SystemMessage(content="You are an expert email summarization assistant."),
                    HumanMessage(content=formatted_prompt)
                ]
                
                response = self.llm.invoke(messages)
                
                # Parse the response
                summary_results = self.output_parser.parse(response.content)
            
            # Validate and clean results
            return self._validate_summary_results(summary_results, summary_type)
            
        except Exception as e:
            logger.error(f"❌ Summary generation failed: {e}")
            return self._get_fallback_summary(email_data)
    
    def _validate_summary_results(self, results: Dict, summary_type: str) -> Dict:
        """Validate and clean summary results"""
        validated = {
            'brief_summary': str(results.get('brief_summary', 'Summary not available'))[:500],
            'detailed_summary': str(results.get('detailed_summary', 'Detailed summary not available'))[:1500],
            'key_points': results.get('key_points', [])[:10],  # Limit to 10 points
            'action_items': results.get('action_items', [])[:10],  # Limit to 10 actions
            'important_dates': results.get('important_dates', [])[:10],  # Limit to 10 dates
            'mentioned_people': results.get('mentioned_people', [])[:20],  # Limit to 20 people
        }
        
        # Ensure all list items are strings
        for key in ['key_points', 'action_items', 'important_dates', 'mentioned_people']:
            validated[key] = [str(item)[:200] for item in validated[key] if item]
        
        return validated
    
    def _get_fallback_summary(self, email_data: Dict) -> Dict:
        """Provide fallback summary when AI fails"""
        content = self._prepare_email_content(email_data)
        
        return {
            'brief_summary': f"Email from {email_data.get('sender', 'Unknown')} about {email_data.get('subject', 'Unknown')}",
            'detailed_summary': content[:300] + '...' if len(content) > 300 else content,
            'key_points': ['AI summarization temporarily unavailable'],
            'action_items': ['Review email manually'],
            'important_dates': [],
            'mentioned_people': []
        }
    
    def _store_summary(self, summary: EmailSummary):
        """Store summary results in database"""
        try:
            self.db.cursor.execute("""
                INSERT OR REPLACE INTO email_summaries 
                (email_id, gmail_id, brief_summary, detailed_summary, key_points, 
                 action_items, important_dates, mentioned_people, summary_type,
                 word_count_original, word_count_summary, compression_ratio,
                 summary_timestamp, processing_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                summary.email_id,
                summary.gmail_id,
                summary.brief_summary,
                summary.detailed_summary,
                json.dumps(summary.key_points),
                json.dumps(summary.action_items),
                json.dumps(summary.important_dates),
                json.dumps(summary.mentioned_people),
                summary.summary_type,
                summary.word_count_original,
                summary.word_count_summary,
                summary.compression_ratio,
                summary.summary_timestamp,
                summary.processing_time_ms
            ))
            self.db.conn.commit()
            
        except Exception as e:
            logger.error(f"❌ Failed to store summary: {e}")
    
    def _is_already_summarized(self, email_id: int, summary_type: str) -> bool:
        """Check if email is already summarized with specified type"""
        self.db.cursor.execute(
            "SELECT 1 FROM email_summaries WHERE email_id = ? AND summary_type = ?", 
            (email_id, summary_type)
        )
        return self.db.cursor.fetchone() is not None
    
    def _get_existing_summary(self, email_id: int, summary_type: str) -> Optional[EmailSummary]:
        """Get existing summary from database"""
        try:
            self.db.cursor.execute("""
                SELECT * FROM email_summaries 
                WHERE email_id = ? AND summary_type = ?
            """, (email_id, summary_type))
            
            row = self.db.cursor.fetchone()
            if not row:
                return None
            
            return EmailSummary(
                email_id=row['email_id'],
                gmail_id=row['gmail_id'],
                brief_summary=row['brief_summary'],
                detailed_summary=row['detailed_summary'],
                key_points=json.loads(row['key_points'] or '[]'),
                action_items=json.loads(row['action_items'] or '[]'),
                important_dates=json.loads(row['important_dates'] or '[]'),
                mentioned_people=json.loads(row['mentioned_people'] or '[]'),
                summary_type=row['summary_type'],
                word_count_original=row['word_count_original'],
                word_count_summary=row['word_count_summary'],
                compression_ratio=row['compression_ratio'],
                summary_timestamp=row['summary_timestamp'],
                processing_time_ms=row['processing_time_ms']
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to get existing summary: {e}")
            return None
    
    def _mark_email_summarized(self, email_id: int):
        """Mark email as summarized in emails table"""
        try:
            self.db.cursor.execute(
                "UPDATE emails SET ai_summarized = TRUE WHERE id = ?", (email_id,)
            )
            self.db.conn.commit()
        except Exception as e:
            logger.error(f"❌ Failed to mark email as summarized: {e}")
    
    def batch_summarize_emails(self, limit: int = 10, summary_type: str = "detailed") -> List[EmailSummary]:
        """Summarize multiple emails in batch"""
        logger.info(f"🚀 Starting batch summarization of up to {limit} emails ({summary_type})")
        
        # Get unsummarized emails
        unsummarized_emails = self._get_unsummarized_emails(limit)
        
        if not unsummarized_emails:
            logger.info("📭 No unsummarized emails found")
            return []
        
        results = []
        for i, email in enumerate(unsummarized_emails, 1):
            logger.info(f"📝 Processing {i}/{len(unsummarized_emails)}")
            
            summary = self.summarize_email(dict(email), summary_type)
            if summary:
                results.append(summary)
            
            # Small delay to avoid rate limits
            time.sleep(0.5)
        
        logger.info(f"✅ Batch summarization complete: {len(results)} emails summarized")
        return results
    
    def _get_unsummarized_emails(self, limit: int) -> List:
        """Get emails that haven't been summarized yet"""
        self.db.cursor.execute("""
            SELECT * FROM emails 
            WHERE ai_summarized IS NOT TRUE 
            ORDER BY date DESC 
            LIMIT ?
        """, (limit,))
        
        return self.db.cursor.fetchall()
    
    def get_email_summaries(self, email_id: int) -> List[Dict]:
        """Get all summaries for a specific email"""
        try:
            self.db.cursor.execute("""
                SELECT * FROM email_summaries 
                WHERE email_id = ? 
                ORDER BY summary_timestamp DESC
            """, (email_id,))
            
            results = []
            for row in self.db.cursor.fetchall():
                summary_dict = dict(row)
                # Parse JSON fields
                summary_dict['key_points'] = json.loads(summary_dict.get('key_points', '[]'))
                summary_dict['action_items'] = json.loads(summary_dict.get('action_items', '[]'))
                summary_dict['important_dates'] = json.loads(summary_dict.get('important_dates', '[]'))
                summary_dict['mentioned_people'] = json.loads(summary_dict.get('mentioned_people', '[]'))
                results.append(summary_dict)
            
            return results
            
        except Exception as e:
            logger.error(f"❌ Failed to get email summaries: {e}")
            return []
    
    def get_summary_stats(self) -> Dict:
        """Get summarization statistics"""
        try:
            # Total emails summarized
            self.db.cursor.execute("SELECT COUNT(DISTINCT email_id) as total FROM email_summaries")
            total_summarized = self.db.cursor.fetchone()['total']
            
            # Summary type distribution
            self.db.cursor.execute("""
                SELECT summary_type, COUNT(*) as count 
                FROM email_summaries 
                GROUP BY summary_type
            """)
            type_dist = {row['summary_type']: row['count'] 
                        for row in self.db.cursor.fetchall()}
            
            # Average compression ratio
            self.db.cursor.execute("SELECT AVG(compression_ratio) as avg_compression FROM email_summaries")
            avg_compression = self.db.cursor.fetchone()['avg_compression'] or 0
            
            # Average processing time
            self.db.cursor.execute("SELECT AVG(processing_time_ms) as avg_time FROM email_summaries")
            avg_processing_time = self.db.cursor.fetchone()['avg_time'] or 0
            
            # Total action items identified
            self.db.cursor.execute("""
                SELECT COUNT(*) as total_actions FROM (
                    SELECT action_items FROM email_summaries 
                    WHERE action_items != '[]'
                )
            """)
            emails_with_actions = self.db.cursor.fetchone()['total_actions']
            
            return {
                'total_emails_summarized': total_summarized,
                'summary_type_distribution': type_dist,
                'average_compression_ratio': round(avg_compression, 2),
                'average_processing_time_ms': round(avg_processing_time, 2),
                'emails_with_action_items': emails_with_actions,
                'summarization_completion_rate': self._get_summarization_completion_rate()
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get summary stats: {e}")
            return {}
    
    def _get_summarization_completion_rate(self) -> float:
        """Calculate percentage of emails that have been summarized"""
        try:
            self.db.cursor.execute("SELECT COUNT(*) as total FROM emails")
            total_emails = self.db.cursor.fetchone()['total']
            
            if total_emails == 0:
                return 0.0
            
            self.db.cursor.execute("SELECT COUNT(DISTINCT email_id) as summarized FROM email_summaries")
            summarized_emails = self.db.cursor.fetchone()['summarized']
            
            return round((summarized_emails / total_emails) * 100, 2)
            
        except Exception:
            return 0.0
    
    def delete_summary(self, email_id: int, summary_type: str = None) -> bool:
        """Delete summaries for an email"""
        try:
            if summary_type:
                self.db.cursor.execute(
                    "DELETE FROM email_summaries WHERE email_id = ? AND summary_type = ?", 
                    (email_id, summary_type)
                )
            else:
                self.db.cursor.execute(
                    "DELETE FROM email_summaries WHERE email_id = ?", 
                    (email_id,)
                )
            
            self.db.conn.commit()
            return self.db.cursor.rowcount > 0
            
        except Exception as e:
            logger.error(f"❌ Failed to delete summary: {e}")
            return False

# Singleton instance
email_summarizer = AIEmailSummarizer()