# src/ai_analysis/ai_analyzer.py

import os
import json
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from bs4 import BeautifulSoup

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.callbacks import BaseCallbackHandler
import logging

from src.storage.sqlite_manager import SQLiteManager
from langsmith import traceable

from utils.logger import get_logger

logger = get_logger(__name__)



os.environ["LANGCHAIN_TRACING_V2"] = "true"  

@dataclass
class EmailAnalysis:
    """Data structure for AI analysis results"""
    email_id: int
    gmail_id: str
    summary: str
    priority_score: int  # 1-5 (5 being highest priority)
    priority_reason: str
    sentiment: str  # positive, neutral, negative, urgent
    draft_reply: str
    action_required: bool
    suggested_actions: List[str]
    key_topics: List[str]
    analysis_timestamp: str
    processing_time_ms: int

class AIEmailAnalyzer:
    """AI-powered email analysis using LangChain and Gemini 2.5 Flash"""
    
    def __init__(self):
        self.db = SQLiteManager()
        self._setup_ai_model()
        self._create_analysis_tables()
        
    def _setup_ai_model(self):
        """Initialize Gemini 2.5 Flash model with LangChain"""
        try:
            self.llm = ChatGoogleGenerativeAI(
                model="gemini-2.5-flash",
                temperature=0.1,
                max_tokens=2048,
                timeout=30,
                max_retries=3,
            )
            logger.info("✅ Gemini 2.5 Flash model initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini model: {e}")
            raise
    
    def _create_analysis_tables(self):
        """Create database tables for storing AI analysis"""
        try:
            self.db.cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id INTEGER NOT NULL,
                    gmail_id TEXT NOT NULL,
                    summary TEXT,
                    priority_score INTEGER,
                    priority_reason TEXT,
                    sentiment TEXT,
                    draft_reply TEXT,
                    action_required BOOLEAN,
                    suggested_actions TEXT, -- JSON array
                    key_topics TEXT, -- JSON array
                    analysis_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    processing_time_ms INTEGER,
                    UNIQUE(email_id),
                    FOREIGN KEY(email_id) REFERENCES emails(id) ON DELETE CASCADE
                );
            """)
            
            # Add analysis status column to emails table if not exists
            try:
                self.db.cursor.execute("""
                    ALTER TABLE emails 
                    ADD COLUMN ai_analyzed BOOLEAN DEFAULT FALSE;
                """)
            except Exception:
                # Column probably already exists
                pass
            
            self.db.conn.commit()
            logger.info("✅ AI analysis tables created/verified")
            
        except Exception as e:
            logger.error(f"❌ Failed to create analysis tables: {e}")
    
    def analyze_email(self, email_data: Dict) -> Optional[EmailAnalysis]:
        """Analyze a single email using AI"""
        start_time = time.time()
        
        try:
            email_id = email_data.get('id')
            gmail_id = email_data.get('gmail_id', email_data.get('id', ''))
            
            logger.info(f"🤖 Analyzing email {email_id}: {email_data.get('subject', '')[:50]}...")
            
            # Check if already analyzed
            if self._is_already_analyzed(email_id):
                logger.info(f"⏭️ Email {email_id} already analyzed, skipping")
                return self._get_existing_analysis(email_id)
            
            # Prepare email content for analysis
            email_content = self._prepare_email_content(email_data)
            
            # Run AI analysis
            analysis_results = self._run_ai_analysis(email_content)
            
            # Create analysis object
            processing_time = int((time.time() - start_time) * 1000)
            
            analysis = EmailAnalysis(
                email_id=email_id,
                gmail_id=gmail_id,
                summary=analysis_results['summary'],
                priority_score=analysis_results['priority_score'],
                priority_reason=analysis_results['priority_reason'],
                sentiment=analysis_results['sentiment'],
                draft_reply=analysis_results['draft_reply'],
                action_required=analysis_results['action_required'],
                suggested_actions=analysis_results['suggested_actions'],
                key_topics=analysis_results['key_topics'],
                analysis_timestamp=datetime.now().isoformat(),
                processing_time_ms=processing_time
            )
            
            # Store in database
            self._store_analysis(analysis)
            
            # Mark email as analyzed
            self._mark_email_analyzed(email_id)
            
            logger.info(f"✅ Email {email_id} analyzed successfully in {processing_time}ms")
            return analysis
            
        except Exception as e:
            logger.error(f"❌ Failed to analyze email {email_data.get('id')}: {e}")
            return None
    
    def _prepare_email_content(self, email_data: Dict) -> str:
        """Prepare email content for AI analysis with HTML cleaning"""
        sender = email_data.get('sender', 'Unknown')
        subject = email_data.get('subject', 'No Subject')
        date = email_data.get('date', '')
        body = email_data.get('body', '')
        snippet = email_data.get('snippet', '')
        category = email_data.get('category', 'Other')
        
        # Clean HTML content using BeautifulSoup
        clean_body = self._clean_html_content(body) if body else ""
        clean_snippet = self._clean_html_content(snippet) if snippet else ""
        
        # Use cleaned body if available, otherwise snippet
        content = clean_body if clean_body else clean_snippet
        
        email_text = f"""
Email Metadata:
- From: {sender}
- Subject: {subject}
- Date: {date}
- Category: {category}

Email Content:
{content[:2000]}  # Limit content to avoid token limits
"""
        return email_text
    
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
        
    @traceable(name="analyze_single_email")
    def _run_ai_analysis(self, email_content: str) -> Dict:
        """Run comprehensive AI analysis on email content"""
        
        system_prompt = """You are an expert email analysis AI assistant. Your task is to analyze emails and provide:

1. **Summary**: A concise 2-3 sentence summary of the email's main points
2. **Priority Score**: Rate 1-5 (5 = highest priority, needs immediate attention)
3. **Priority Reason**: Brief explanation for the priority score
4. **Sentiment**: One of: positive, negative, neutral, urgent
5. **Action Required**: Boolean - does this email require action from the recipient?
6. **Suggested Actions**: List of specific actions the recipient should take
7. **Key Topics**: List of main topics/themes discussed
8. **Draft Reply**: A professional draft response (or "No reply needed" if appropriate)

Consider these factors for priority scoring:
- Time-sensitive requests (meetings, deadlines) = Higher priority
- Questions requiring answers = Medium-high priority  
- FYI/newsletters = Lower priority
- Urgent language/tone = Higher priority
- Important stakeholders = Higher priority

Respond in valid JSON format only."""

        user_prompt = f"""Analyze this email:

{email_content}

Provide analysis in this exact JSON format:
{{
    "summary": "Brief summary here",
    "priority_score": 1-5,
    "priority_reason": "Explanation for priority",
    "sentiment": "positive/negative/neutral/urgent",
    "action_required": true/false,
    "suggested_actions": ["action1", "action2"],
    "key_topics": ["topic1", "topic2"],
    "draft_reply": "Draft response or 'No reply needed'"
}}"""

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            # Fixed: Remove callbacks parameter that was causing the error
            response = self.llm.invoke(messages)
            
            # Parse JSON response
            response_text = response.content.strip()
            
            # Clean up response if it has markdown formatting
            if response_text.startswith('```json'):
                response_text = response_text.replace('```json', '').replace('```', '').strip()
            
            analysis_results = json.loads(response_text)
            
            # Validate and clean results
            return self._validate_analysis_results(analysis_results)
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse AI response as JSON: {e}")
            logger.error(f"Response was: {response.content}")
            return self._get_fallback_analysis()
            
        except Exception as e:
            logger.error(f" AI analysis failed: {e}")
            return self._get_fallback_analysis()
    
    def _validate_analysis_results(self, results: Dict) -> Dict:
        """Validate and clean AI analysis results"""
        validated = {
            'summary': str(results.get('summary', 'Analysis not available'))[:500],
            'priority_score': max(1, min(5, int(results.get('priority_score', 3)))),
            'priority_reason': str(results.get('priority_reason', 'Standard priority'))[:200],
            'sentiment': results.get('sentiment', 'neutral').lower(),
            'action_required': bool(results.get('action_required', False)),
            'suggested_actions': results.get('suggested_actions', [])[:5],  # Limit to 5 actions
            'key_topics': results.get('key_topics', [])[:10],  # Limit to 10 topics
            'draft_reply': str(results.get('draft_reply', 'No reply needed'))[:1000]
        }
        
        # Validate sentiment
        valid_sentiments = ['positive', 'negative', 'neutral', 'urgent']
        if validated['sentiment'] not in valid_sentiments:
            validated['sentiment'] = 'neutral'
        
        return validated
    
    def _get_fallback_analysis(self) -> Dict:
        """Provide fallback analysis when AI fails"""
        return {
            'summary': 'AI analysis temporarily unavailable',
            'priority_score': 3,
            'priority_reason': 'Default priority - analysis failed',
            'sentiment': 'neutral',
            'action_required': True,
            'suggested_actions': ['Review email manually'],
            'key_topics': ['Unknown'],
            'draft_reply': 'AI draft unavailable - please compose manually'
        }
    
    def _store_analysis(self, analysis: EmailAnalysis):
        """Store analysis results in database"""
        try:
            self.db.cursor.execute("""
                INSERT OR REPLACE INTO email_analysis 
                (email_id, gmail_id, summary, priority_score, priority_reason, 
                 sentiment, draft_reply, action_required, suggested_actions, 
                 key_topics, analysis_timestamp, processing_time_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                analysis.email_id,
                analysis.gmail_id,
                analysis.summary,
                analysis.priority_score,
                analysis.priority_reason,
                analysis.sentiment,
                analysis.draft_reply,
                analysis.action_required,
                json.dumps(analysis.suggested_actions),
                json.dumps(analysis.key_topics),
                analysis.analysis_timestamp,
                analysis.processing_time_ms
            ))
            self.db.conn.commit()
            
        except Exception as e:
            logger.error(f"❌ Failed to store analysis: {e}")
    
    def _is_already_analyzed(self, email_id: int) -> bool:
        """Check if email is already analyzed"""
        self.db.cursor.execute(
            "SELECT 1 FROM email_analysis WHERE email_id = ?", (email_id,)
        )
        return self.db.cursor.fetchone() is not None
    
    def _get_existing_analysis(self, email_id: int) -> Optional[EmailAnalysis]:
        """Get existing analysis from database"""
        try:
            self.db.cursor.execute("""
                SELECT * FROM email_analysis WHERE email_id = ?
            """, (email_id,))
            
            row = self.db.cursor.fetchone()
            if not row:
                return None
            
            return EmailAnalysis(
                email_id=row['email_id'],
                gmail_id=row['gmail_id'],
                summary=row['summary'],
                priority_score=row['priority_score'],
                priority_reason=row['priority_reason'],
                sentiment=row['sentiment'],
                draft_reply=row['draft_reply'],
                action_required=bool(row['action_required']),
                suggested_actions=json.loads(row['suggested_actions'] or '[]'),
                key_topics=json.loads(row['key_topics'] or '[]'),
                analysis_timestamp=row['analysis_timestamp'],
                processing_time_ms=row['processing_time_ms']
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to get existing analysis: {e}")
            return None
    
    def _mark_email_analyzed(self, email_id: int):
        """Mark email as analyzed in emails table"""
        try:
            self.db.cursor.execute(
                "UPDATE emails SET ai_analyzed = TRUE WHERE id = ?", (email_id,)
            )
            self.db.conn.commit()
        except Exception as e:
            logger.error(f"❌ Failed to mark email as analyzed: {e}")
    
    def batch_analyze_emails(self, limit: int = 10) -> List[EmailAnalysis]:
        """Analyze multiple emails in batch"""
        logger.info(f"🚀 Starting batch analysis of up to {limit} emails")
        
        # Get unanalyzed emails
        unanalyzed_emails = self._get_unanalyzed_emails(limit)
        
        if not unanalyzed_emails:
            logger.info("📭 No unanalyzed emails found")
            return []
        
        results = []
        for i, email in enumerate(unanalyzed_emails, 1):
            logger.info(f"📊 Processing {i}/{len(unanalyzed_emails)}")
            
            analysis = self.analyze_email(dict(email))
            if analysis:
                results.append(analysis)
            
            # Small delay to avoid rate limits
            time.sleep(0.5)
        
        logger.info(f"✅ Batch analysis complete: {len(results)} emails analyzed")
        return results
    
    def _get_unanalyzed_emails(self, limit: int) -> List:
        """Get emails that haven't been analyzed yet"""
        self.db.cursor.execute("""
            SELECT * FROM emails 
            WHERE ai_analyzed IS NOT TRUE 
            ORDER BY date DESC 
            LIMIT ?
        """, (limit,))
        
        return self.db.cursor.fetchall()
    
    def get_high_priority_emails(self, limit: int = 20) -> List[Dict]:
        """Get emails with high priority scores"""
        self.db.cursor.execute("""
            SELECT e.*, a.priority_score, a.priority_reason, a.summary, 
                   a.action_required, a.suggested_actions, a.sentiment
            FROM emails e
            JOIN email_analysis a ON e.id = a.email_id
            WHERE a.priority_score >= 4
            ORDER BY a.priority_score DESC, e.date DESC
            LIMIT ?
        """, (limit,))
        
        results = []
        for row in self.db.cursor.fetchall():
            row_dict = dict(row)
            row_dict['suggested_actions'] = json.loads(row_dict.get('suggested_actions', '[]'))
            results.append(row_dict)
        
        return results
    
    def get_analysis_stats(self) -> Dict:
        """Get analysis statistics"""
        try:
            # Total emails analyzed
            self.db.cursor.execute("SELECT COUNT(*) as total FROM email_analysis")
            total_analyzed = self.db.cursor.fetchone()['total']
            
            # Priority distribution
            self.db.cursor.execute("""
                SELECT priority_score, COUNT(*) as count 
                FROM email_analysis 
                GROUP BY priority_score
            """)
            priority_dist = {row['priority_score']: row['count'] 
                           for row in self.db.cursor.fetchall()}
            
            # Sentiment distribution
            self.db.cursor.execute("""
                SELECT sentiment, COUNT(*) as count 
                FROM email_analysis 
                GROUP BY sentiment
            """)
            sentiment_dist = {row['sentiment']: row['count'] 
                            for row in self.db.cursor.fetchall()}
            
            # Emails requiring action
            self.db.cursor.execute("""
                SELECT COUNT(*) as count 
                FROM email_analysis 
                WHERE action_required = 1
            """)
            action_required = self.db.cursor.fetchone()['count']
            
            return {
                'total_analyzed': total_analyzed,
                'priority_distribution': priority_dist,
                'sentiment_distribution': sentiment_dist,
                'emails_requiring_action': action_required,
                'analysis_completion_rate': self._get_analysis_completion_rate()
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get analysis stats: {e}")
            return {}
    
    def _get_analysis_completion_rate(self) -> float:
        """Calculate percentage of emails that have been analyzed"""
        try:
            self.db.cursor.execute("SELECT COUNT(*) as total FROM emails")
            total_emails = self.db.cursor.fetchone()['total']
            
            if total_emails == 0:
                return 0.0
            
            self.db.cursor.execute("SELECT COUNT(*) as analyzed FROM email_analysis")
            analyzed_emails = self.db.cursor.fetchone()['analyzed']
            
            return round((analyzed_emails / total_emails) * 100, 2)
            
        except Exception:
            return 0.0

# Singleton instance
ai_analyzer = AIEmailAnalyzer()