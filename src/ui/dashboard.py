

# src/ui/dashboard.py

import streamlit as st
import time
import json
from datetime import datetime, timedelta
import re
from bs4 import BeautifulSoup

from src.storage.sqlite_manager import SQLiteManager
from src.email_processing.fetch_emails import email_fetcher
from src.ai_analysis.ai_analyzer import ai_analyzer, EmailAnalysis
from src.ai_analysis.email_reply import email_reply_system
from src.ai_analysis.email_summarizer import email_summarizer  # Import the summarizer

db = SQLiteManager()

class EmailDashboard:
    def __init__(self):
        self._init_state()

    def _init_state(self):
        defaults = {
            "current_page": 1,
            "page_size": 15,
            "last_fetch_time": None,
            "is_fetching": False,
            "is_analyzing": False,
            "is_summarizing": False,  # Add summarization state
            "sender_filter": "",
            "subject_filter": "",
            "active_category": "Inbox",
            "selected_email": None,
            "show_unread_only": False,
            "show_ai_analysis": False,
            "show_ai_summary": False,  # Add summary toggle
            "priority_filter": None,  # None, "high", "medium", "low"
            "show_reply_modal": False,
            "selected_reply_type": "standard",
            "generated_reply": "",
            "show_email_detail": False,
            "show_summary_modal": False,  # Add summary modal state
            "selected_summary_type": "detailed",  # Add summary type selection
        }
        for k, v in defaults.items():
            if k not in st.session_state:
                st.session_state[k] = v

    def _clean_html_content(self, html_content: str) -> tuple[str, str]:
        """Clean HTML content using BeautifulSoup and return both plain text and formatted HTML"""
        if not html_content:
            return "", ""
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get plain text
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            plain_text = ' '.join(chunk for chunk in chunks if chunk)
            
            # Get formatted HTML (preserve some formatting)
            formatted_html = str(soup)
            
            return plain_text, formatted_html
        except Exception as e:
            return html_content, html_content

    def _format_date(self, date_str):
        """Format email date for display"""
        try:
            if not date_str or date_str == "Unknown Date":
                return "Unknown"
            
            # Parse various date formats
            date_formats = [
                "%a, %d %b %Y %H:%M:%S %z",  # RFC 2822
                "%a, %d %b %Y %H:%M:%S %Z",  # With timezone name
                "%d %b %Y %H:%M:%S %z",      # Without day name
                "%Y-%m-%d %H:%M:%S",         # ISO format
                "%a, %d %b %Y %H:%M:%S",     # Without timezone
            ]
            
            parsed_date = None
            for fmt in date_formats:
                try:
                    # Clean the date string
                    clean_date = re.sub(r'\s+\([^)]+\)', '', date_str.strip())
                    parsed_date = datetime.strptime(clean_date, fmt)
                    break
                except ValueError:
                    continue
            
            if not parsed_date:
                return date_str[:20] + "..." if len(date_str) > 20 else date_str
            
            now = datetime.now()
            diff = now - parsed_date.replace(tzinfo=None)
            
            if diff.days == 0:
                return parsed_date.strftime("%H:%M")
            elif diff.days == 1:
                return "Yesterday"
            elif diff.days < 7:
                return parsed_date.strftime("%a")
            elif diff.days < 365:
                return parsed_date.strftime("%b %d")
            else:
                return parsed_date.strftime("%m/%d/%y")
                
        except Exception:
            return date_str[:10] if date_str else "Unknown"

    def _truncate_text(self, text, length=50):
        """Truncate text with ellipsis"""
        if not text:
            return ""
        return text[:length] + "..." if len(text) > length else text

    def _extract_sender_name(self, sender):
        """Extract just the name or email from sender field"""
        if not sender:
            return "Unknown"
        
        # Extract name from "Name <email>" format
        match = re.match(r'^([^<]+)<[^>]+>$', sender.strip())
        if match:
            name = match.group(1).strip().strip('"')
            return name if name else sender
        
        # If no name, just return email or sender as-is
        return sender

    def _get_priority_emoji(self, priority_score):
        """Get emoji for priority score"""
        if priority_score >= 5:
            return "🔴"  # High priority
        elif priority_score >= 4:
            return "🟡"  # Medium-high
        elif priority_score >= 3:
            return "🟢"  # Medium
        else:
            return "⚪"  # Low priority

    def _get_sentiment_emoji(self, sentiment):
        """Get emoji for sentiment"""
        sentiment_map = {
            "positive": "😊",
            "negative": "😟",
            "urgent": "🚨",
            "neutral": "😐"
        }
        return sentiment_map.get(sentiment, "😐")

    # ---------------- Sidebar ----------------
    def render_sidebar(self):
        st.sidebar.markdown("### 📧 Mail Controls")

        # Stats
        total_in_db = db.get_total_email_count()
        unread_count = db.get_unread_count()
        
        # AI Analysis stats
        ai_stats = ai_analyzer.get_analysis_stats()
        analyzed_count = ai_stats.get('total_analyzed', 0)
        completion_rate = ai_stats.get('analysis_completion_rate', 0)
        
        # AI Summarization stats
        summary_stats = email_summarizer.get_summary_stats()
        summarized_count = summary_stats.get('total_emails_summarized', 0)
        summary_completion_rate = summary_stats.get('summarization_completion_rate', 0)
        
        col1, col2 = st.sidebar.columns(2)
        col1.metric("📬 Total", total_in_db)
        col2.metric("📩 Unread", unread_count)
        
        # AI stats
        col3, col4 = st.sidebar.columns(2)
        col3.metric("Analyzed", analyzed_count)
        col4.metric("Summarized", summarized_count)
        
        # Progress bars for AI completion
        st.sidebar.metric("Analysis Progress", f"{completion_rate}%")
        st.sidebar.metric("Summary Progress", f"{summary_completion_rate}%")

        if st.session_state.last_fetch_time:
            st.sidebar.caption(f"⏱ Last sync: {st.session_state.last_fetch_time}")

        # Refresh button
        if st.session_state.is_fetching:
            st.sidebar.button("🔄 Syncing...", disabled=True, use_container_width=True)
        else:
            if st.sidebar.button("🔄 Sync Gmail", use_container_width=True, type="primary"):
                self.fetch_from_gmail()

        # AI Analysis button
        if st.session_state.is_analyzing:
            st.sidebar.button("🤖 Analyzing...", disabled=True, use_container_width=True)
        else:
            if st.sidebar.button("🤖 Analyze Emails", use_container_width=True):
                self.run_ai_analysis()

        # AI Summarization button
        if st.session_state.is_summarizing:
            st.sidebar.button("📝 Summarizing...", disabled=True, use_container_width=True)
        else:
            col_sum1, col_sum2 = st.sidebar.columns(2)
            with col_sum1:
                if st.button("Sumarize", use_container_width=True):
                    self.run_ai_summarization()
            with col_sum2:
                if st.button("Stats", use_container_width=True):
                    self.show_ai_stats_modal()

        # First time info
        if total_in_db == 0:
            st.sidebar.info("👆 Click 'Sync Gmail' to fetch your emails for the first time!")

        st.sidebar.divider()

        # View options
        st.sidebar.markdown("### ⚙️ View Options")
        
        st.session_state.show_unread_only = st.sidebar.checkbox(
            "📩 Show unread only", 
            value=st.session_state.show_unread_only
        )
        
        st.session_state.show_ai_analysis = st.sidebar.checkbox(
            "🤖 Show AI analysis", 
            value=st.session_state.show_ai_analysis
        )
        
        st.session_state.show_ai_summary = st.sidebar.checkbox(
            "📝 Show AI summaries", 
            value=st.session_state.show_ai_summary
        )
        
        # Priority filter
        priority_options = {
            None: "All Priorities",
            "high": "🔴 High Priority (4-5)",
            "medium": "🟡 Medium Priority (3)",
            "low": "🟢 Low Priority (1-2)"
        }
        
        selected_priority = st.sidebar.selectbox(
            "Priority Filter",
            options=list(priority_options.keys()),
            format_func=lambda x: priority_options[x],
            index=list(priority_options.keys()).index(st.session_state.priority_filter)
        )
        
        if selected_priority != st.session_state.priority_filter:
            st.session_state.priority_filter = selected_priority
            st.session_state.current_page = 1
            st.rerun()
        
        st.session_state.page_size = st.sidebar.selectbox(
            "Emails per page",
            [1, 5, 10, 15, 25, 50],
            index=[1, 5, 10, 15, 25, 50].index(st.session_state.page_size),
        )

        # Filters
        st.sidebar.markdown("### 🔍 Filters")
        
        new_sender = st.sidebar.text_input(
            "👤 From", 
            value=st.session_state.sender_filter,
            placeholder="Enter sender email or name"
        )
        
        new_subject = st.sidebar.text_input(
            "📋 Subject", 
            value=st.session_state.subject_filter,
            placeholder="Enter subject keywords"
        )

        # Update filters and reset page if changed
        if new_sender != st.session_state.sender_filter or new_subject != st.session_state.subject_filter:
            st.session_state.sender_filter = new_sender
            st.session_state.subject_filter = new_subject
            st.session_state.current_page = 1
            st.rerun()

        if st.sidebar.button("🧹 Clear Filters", use_container_width=True):
            st.session_state.sender_filter = ""
            st.session_state.subject_filter = ""
            st.session_state.current_page = 1
            st.session_state.show_unread_only = False
            st.session_state.priority_filter = None
            st.rerun()

    # ---------------- AI Summarization Functions ----------------
    def run_ai_summarization(self):
        """Run AI summarization on unsummarized emails"""
        st.session_state.is_summarizing = True
        
        with st.sidebar:
            progress_bar = st.progress(0)
            status_text = st.empty()
        
        try:
            status_text.info("📝 Starting AI summarization...")
            progress_bar.progress(0.1)
            
            # Summarize batch of emails
            results = email_summarizer.batch_summarize_emails(limit=10)
            
            progress_bar.progress(0.8)
            
            if results:
                status_text.success(f"✅ Summarized {len(results)} emails!")
            else:
                status_text.info("📭 No new emails to summarize")
            
            progress_bar.progress(1.0)
            time.sleep(2)
            progress_bar.empty()
            status_text.empty()
            
        except Exception as e:
            progress_bar.empty()
            status_text.error(f"❌ Summarization failed: {str(e)}")
        finally:
            st.session_state.is_summarizing = False
            st.rerun()

    # ---------------- AI Analysis Functions ----------------
    def run_ai_analysis(self):
        """Run AI analysis on unanalyzed emails"""
        st.session_state.is_analyzing = True
        
        with st.sidebar:
            progress_bar = st.progress(0)
            status_text = st.empty()
        
        try:
            status_text.info("🤖 Starting AI analysis...")
            progress_bar.progress(0.1)
            
            # Analyze batch of emails
            results = ai_analyzer.batch_analyze_emails(limit=10)
            
            progress_bar.progress(0.8)
            
            if results:
                status_text.success(f"✅ Analyzed {len(results)} emails!")
            else:
                status_text.info("📭 No new emails to analyze")
            
            progress_bar.progress(1.0)
            time.sleep(2)
            progress_bar.empty()
            status_text.empty()
            
        except Exception as e:
            progress_bar.empty()
            status_text.error(f"❌ Analysis failed: {str(e)}")
        finally:
            st.session_state.is_analyzing = False
            st.rerun()

    def show_ai_stats_modal(self):
        """Show comprehensive AI statistics"""
        stats = ai_analyzer.get_analysis_stats()
        summary_stats = email_summarizer.get_summary_stats()
        
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 🤖 AI Statistics")
        
        if stats or summary_stats:
            # Analysis stats
            st.sidebar.markdown("**Analysis Stats:**")
            st.sidebar.metric("Total Analyzed", stats.get('total_analyzed', 0))
            st.sidebar.metric("Need Action", stats.get('emails_requiring_action', 0))
            st.sidebar.metric("Completion Rate", f"{stats.get('analysis_completion_rate', 0)}%")
            
            # Summary stats
            st.sidebar.markdown("**Summary Stats:**")
            st.sidebar.metric("Total Summarized", summary_stats.get('total_emails_summarized', 0))
            st.sidebar.metric("Avg Compression", f"{summary_stats.get('average_compression_ratio', 0)}%")
            st.sidebar.metric("Emails w/ Actions", summary_stats.get('emails_with_action_items', 0))
            
            # Priority distribution
            priority_dist = stats.get('priority_distribution', {})
            if priority_dist:
                st.sidebar.markdown("**Priority Distribution:**")
                for priority, count in sorted(priority_dist.items()):
                    emoji = self._get_priority_emoji(int(priority))
                    st.sidebar.caption(f"{emoji} Priority {priority}: {count} emails")
            
            # Summary type distribution
            summary_type_dist = summary_stats.get('summary_type_distribution', {})
            if summary_type_dist:
                st.sidebar.markdown("**Summary Types:**")
                for stype, count in summary_type_dist.items():
                    st.sidebar.caption(f"📝 {stype.title()}: {count}")

    # ---------------- Gmail Fetch ----------------
    def fetch_from_gmail(self):
        """Fetch emails from Gmail with improved UX"""
        st.session_state.is_fetching = True
        
        with st.sidebar:
            progress_bar = st.progress(0)
            status_text = st.empty()
        
        try:
            total_in_db = db.get_total_email_count()
            is_first_fetch = total_in_db == 0
            
            if is_first_fetch:
                status_text.info("🚀 First sync - fetching emails...")
                page_token = None
                batch_size = 100
            else:
                status_text.info("🔄 Checking for new emails...")
                page_token = db.get_sync_metadata("last_page_token")
                batch_size = 50
            
            progress_bar.progress(0.3)
            
            emails, next_token = email_fetcher.fetch_email_batch(
                page_token=page_token, 
                batch_size=batch_size
            )
            
            progress_bar.progress(0.8)
            
            # Update metadata
            db.update_sync_metadata("last_page_token", next_token or "")
            current_total = int(db.get_sync_metadata("total_emails_fetched") or "0")
            db.update_sync_metadata("total_emails_fetched", str(current_total + len(emails)))
            
            st.session_state.last_fetch_time = datetime.now().strftime("%H:%M")
            st.session_state.current_page = 1
            
            progress_bar.progress(1.0)
            
            if len(emails) > 0:
                status_text.success(f"✅ Synced {len(emails)} emails!")
            else:
                status_text.info("📭 No new emails")
                
            time.sleep(2)
            progress_bar.empty()
            status_text.empty()

        except Exception as e:
            progress_bar.empty()
            status_text.error(f"❌ Sync failed: {str(e)}")
            st.sidebar.error("Check your Gmail credentials and connection.")
        finally:
            st.session_state.is_fetching = False
            st.rerun()

    # ---------------- Enhanced Email Detail View ----------------
    def _show_email_detail_modal(self, email):
        """Enhanced email details modal with AI summaries"""
        subject = email.get("subject", "No Subject")
        sender = email.get("sender", "Unknown")
        date = email.get("date", "")
        body = email.get("body", "")
        to_recipients = email.get("to_recipients", "")
        email_id = email.get("id")

        # Get AI analysis
        analysis = None
        try:
            db.cursor.execute("SELECT * FROM email_analysis WHERE email_id = ?", (email_id,))
            analysis_row = db.cursor.fetchone()
            if analysis_row:
                analysis = dict(analysis_row)
        except Exception:
            pass

        # Get AI summaries
        summaries = email_summarizer.get_email_summaries(email_id)

        # Get replies for this email
        replies = email_reply_system.get_replies_for_email(email_id)

        # Create a modal-like experience with improved layout
        st.markdown("---")
        
        # Header with close button
        col_header1, col_header2 = st.columns([4, 1])
        with col_header1:
            st.markdown(f"## 📧 {subject}")
        with col_header2:
            if st.button("✖️ Close", key="close_modal", type="secondary"):
                st.session_state.selected_email = None
                st.session_state.show_email_detail = False
                st.rerun()

        # Email metadata in a nice layout
        col_meta1, col_meta2 = st.columns([3, 2])
        with col_meta1:
            st.markdown(f"**From:** {sender}")
            st.markdown(f"**To:** {to_recipients}")
        with col_meta2:
            st.markdown(f"**Date:** {self._format_date(date)}")
            st.markdown(f"**Category:** {email.get('category', 'Other')}")


        
        # AI Analysis Section (if available)
        if analysis:
            st.markdown("### 🤖 AI Analysis")
            
            # Analysis metrics in columns
            col_ai1, col_ai2, col_ai3, col_ai4 = st.columns(4)
            
            with col_ai1:
                priority_emoji = self._get_priority_emoji(analysis.get('priority_score', 0))
                st.metric(
                    f"{priority_emoji} Priority", 
                    f"{analysis.get('priority_score', 0)}/5"
                )
            
            with col_ai2:
                sentiment_emoji = self._get_sentiment_emoji(analysis.get('sentiment', 'neutral'))
                st.metric(f"{sentiment_emoji} Sentiment", analysis.get('sentiment', 'neutral').title())
            
            with col_ai3:
                action_required = analysis.get('action_required', False)
                st.metric("Action Required", "✅ Yes" if action_required else "❌ No")
                
            with col_ai4:
                processing_time = analysis.get('processing_time_ms', 0)
                st.metric("Analysis Time", f"{processing_time}ms")
            
            # Summary and details in expandable sections
            if analysis.get('summary'):
                with st.expander("📝 AI Summary", expanded=True):
                    st.info(analysis['summary'])
                    st.caption(f"**Reason:** {analysis.get('priority_reason', 'N/A')}")
            
            # Suggested actions
            suggested_actions = json.loads(analysis.get('suggested_actions', '[]'))
            if suggested_actions:
                with st.expander("🎯 Suggested Actions"):
                    for i, action in enumerate(suggested_actions, 1):
                        st.markdown(f"{i}. {action}")
            
            # Key topics as badges
            key_topics = json.loads(analysis.get('key_topics', '[]'))
            if key_topics:
                st.markdown("**🏷️ Key Topics:**")
                topic_cols = st.columns(min(len(key_topics), 5))
                for i, topic in enumerate(key_topics[:5]):
                    with topic_cols[i]:
                        st.markdown(f"`{topic}`")

        # Email Content Section with better rendering
        st.markdown("### 📄 Message Content")
        
        if body:
            # Clean and format the content
            plain_text, formatted_html = self._clean_html_content(body)
            
            # Show content in tabs
            tab1, tab2 = st.tabs(["📄 Formatted View", "📝 Plain Text"])
            
            with tab1:
                if len(formatted_html) > 5000:
                    st.markdown("**Note:** Long email content - showing preview")
                    with st.expander("Show Full Content", expanded=False):
                        st.markdown(formatted_html, unsafe_allow_html=True)
                else:
                    st.markdown(formatted_html, unsafe_allow_html=True)
            
            with tab2:
                st.text_area("Plain Text Content", value=plain_text, height=300, disabled=True)
        else:
            st.info("No email body content available")

        # Attachments Section
        try:
            db.cursor.execute("SELECT * FROM attachments WHERE email_id = ?", (email_id,))
            attachments = [dict(row) for row in db.cursor.fetchall()]
            
            if attachments:
                st.markdown("### 📎 Attachments")
                for att in attachments:
                    col_att1, col_att2 = st.columns([3, 1])
                    with col_att1:
                        st.markdown(f"📄 **{att['filename']}** ({att.get('size', 'Unknown')} bytes)")
                    with col_att2:
                        if att.get("content_preview"):
                            with st.expander(f"Preview"):
                                st.text(att["content_preview"][:1000])
        except Exception as e:
            st.caption(f"Could not load attachments: {e}")

        # Replies Section
        if replies:
            st.markdown("### ↩️ Email Replies")
            for reply in replies:
                with st.expander(f"Reply - {reply['sent_status'].title()} ({reply['created_timestamp'][:16]})"):
                    st.markdown(f"**Subject:** {reply['reply_subject']}")
                    st.markdown(f"**Type:** {reply['reply_type']}")
                    st.markdown(f"**Status:** {reply['sent_status']}")
                    if reply['sent_timestamp']:
                        st.markdown(f"**Sent:** {reply['sent_timestamp'][:16]}")
                    
                    st.markdown("**Content:**")
                    st.text_area("", value=reply['reply_body'], height=200, disabled=True, key=f"reply_{reply['id']}")

        # Action Buttons
        st.markdown("### 🎯 Actions")
        col_action1, col_action2, col_action3, col_action4, col_action5 = st.columns(5)
        
        with col_action1:
            if st.button("🤖 Analyze", key="detail_analyze", type="primary"):
                self._analyze_single_email(email_id, dict(email))
        
        with col_action2:
            if st.button("📝 Summarize", key="detail_summarize", type="primary"):
                self._show_summary_modal(email_id, dict(email))
        
        with col_action3:
            if st.button("↩️ Reply", key="detail_reply", type="primary"):
                self._show_reply_modal(email_id, dict(email))
        
        with col_action4:
            is_read = email.get("is_read", 0)
            if not is_read and st.button("✅ Mark Read", key="detail_mark_read"):
                db.mark_email_as_read(email_id)
                st.success("Marked as read!")
                time.sleep(1)
                st.rerun()
        
        with col_action5:
            if st.button("🗑️ Delete", key="detail_delete", type="secondary"):
                if st.session_state.get("confirm_delete", False):
                    db.delete_email(email_id)
                    st.session_state.selected_email = None
                    st.session_state.show_email_detail = False
                    st.success("Email deleted!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.session_state.confirm_delete = True
                    st.warning("Click again to confirm deletion")

        st.markdown("---")

    def _render_summary_content(self, summary):
        """Render summary content in a structured format"""
        # Brief summary
        if summary.get('brief_summary'):
            st.markdown("**📋 Brief Summary:**")
            st.info(summary['brief_summary'])
        
        # Detailed summary
        if summary.get('detailed_summary'):
            st.markdown("**📄 Detailed Summary:**")
            st.write(summary['detailed_summary'])
        
        # Key points, action items, etc.
        col1, col2 = st.columns(2)
        
        with col1:
            if summary.get('key_points'):
                st.markdown("**🔑 Key Points:**")
                for point in summary['key_points']:
                    st.markdown(f"• {point}")
            
            if summary.get('important_dates'):
                st.markdown("**📅 Important Dates:**")
                for date in summary['important_dates']:
                    st.markdown(f"• {date}")
        
        with col2:
            if summary.get('action_items'):
                st.markdown("**🎯 Action Items:**")
                for action in summary['action_items']:
                    st.markdown(f"• {action}")
            
            if summary.get('mentioned_people'):
                st.markdown("**👥 Mentioned People:**")
                for person in summary['mentioned_people'][:5]:  # Limit to 5
                    st.markdown(f"• {person}")
        
        # Summary stats
        col_stat1, col_stat2, col_stat3 = st.columns(3)
        with col_stat1:
            st.metric("Original Words", summary.get('word_count_original', 0))
        with col_stat2:
            st.metric("Summary Words", summary.get('word_count_summary', 0))
        with col_stat3:
            st.metric("Compression", f"{summary.get('compression_ratio', 0)}%")

    # ---------------- Summary Modal ----------------
    def _show_summary_modal(self, email_id: int, email_data: dict):
        """Show summary generation modal"""
        st.markdown("---")
        st.markdown("## 📝 Generate Email Summary")
        st.markdown(f"**Email:** {email_data.get('subject', 'No Subject')}")
        st.markdown(f"**From:** {email_data.get('sender', 'Unknown')}")
        
        # Summary type selection
        summary_types = {
            'brief': {'name': '📋 Brief Summary', 'desc': 'Quick 2-3 sentence overview'},
            'detailed': {'name': '📄 Detailed Summary', 'desc': 'Comprehensive analysis with key points'},
            'bullet_points': {'name': '🔸 Bullet Points', 'desc': 'Structured list format'},
            'executive': {'name': '💼 Executive Summary', 'desc': 'High-level business impact focus'}
        }
        
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            selected_type = st.selectbox(
                "Summary Type:",
                options=list(summary_types.keys()),
                format_func=lambda x: summary_types[x]['name'],
                key="summary_type_selector"
            )
        
        with col2:
            st.info(summary_types[selected_type]['desc'])
        
        with col3:
            if st.button("✖️ Close", key="close_summary_modal"):
                st.session_state.show_summary_modal = False
                st.session_state.selected_email = None
                st.rerun()
        
        # Generate summary
        col_gen1, col_gen2 = st.columns([2, 1])
        
        with col_gen1:
            if st.button("📝 Generate Summary", key="generate_summary", type="primary", use_container_width=True):
                with st.spinner("📝 Generating AI summary..."):
                    summary = email_summarizer.summarize_email(email_data, selected_type)
                    if summary:
                        st.success("✅ Summary generated successfully!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("❌ Failed to generate summary")
        
        with col_gen2:
            if st.button("📊 View All", key="view_all_summaries"):
                existing_summaries = email_summarizer.get_email_summaries(email_id)
                if existing_summaries:
                    st.session_state.show_all_summaries = True
                else:
                    st.info("No existing summaries found")
        
        # Show existing summaries if any
        existing_summaries = email_summarizer.get_email_summaries(email_id)
        if existing_summaries:
            st.markdown("### 📄 Existing Summaries")
            for summary in existing_summaries:
                with st.expander(f"{summary_types.get(summary['summary_type'], {}).get('name', summary['summary_type'].title())} - {summary['summary_timestamp'][:16]}"):
                    self._render_summary_content(summary)
        
        st.markdown("---")

    # ---------------- Enhanced Reply Modal ----------------
    def _show_reply_modal(self, email_id: int, email_data: dict):
        """Enhanced reply generation modal"""
        st.session_state.show_reply_modal = True
        st.session_state.selected_email = email_id
        
        st.markdown("---")
        st.markdown(f"## ↩️ Compose Reply")
        st.markdown(f"**Original:** {email_data.get('subject', 'No Subject')}")
        st.markdown(f"**To:** {email_data.get('sender', 'Unknown')}")
        
        # Reply type selection with descriptions
        reply_types = {
            'standard': {'name': '📝 Standard Reply', 'desc': 'Professional response addressing main points'},
            'acknowledge': {'name': '✅ Quick Acknowledgment', 'desc': 'Brief confirmation of receipt'}, 
            'decline': {'name': '❌ Polite Decline', 'desc': 'Respectful rejection or decline'},
            'request_info': {'name': '❓ Request Information', 'desc': 'Ask for additional details'},
            'follow_up': {'name': '📞 Follow-up', 'desc': 'Follow up on previous communication'}
        }
        
        col1, col2, col3 = st.columns([2, 2, 1])
        
        with col1:
            selected_type = st.selectbox(
                "Reply Type:",
                options=list(reply_types.keys()),
                format_func=lambda x: reply_types[x]['name'],
                key="reply_type_selector"
            )
        
        with col2:
            st.info(reply_types[selected_type]['desc'])
        
        with col3:
            if st.button("✖️ Close", key="close_reply_modal"):
                st.session_state.show_reply_modal = False
                st.session_state.selected_email = None
                st.session_state.generated_reply = ""
                st.rerun()
        
        # Generate and manage reply
        col_gen1, col_gen2 = st.columns([2, 1])
        
        with col_gen1:
            if st.button("🤖 Generate AI Reply", key="generate_reply", type="primary", use_container_width=True):
                with st.spinner("🤖 Generating intelligent reply..."):
                    reply_content = email_reply_system.generate_ai_reply(email_data, selected_type)
                    if reply_content:
                        st.session_state.generated_reply = reply_content
                        st.success("✅ Reply generated successfully!")
                    else:
                        st.error("❌ Failed to generate reply")
        
        with col_gen2:
            if st.button("🧹 Clear Reply", key="clear_reply"):
                st.session_state.generated_reply = ""
                st.rerun()
        
        # Show generated reply with editing capability
        if st.session_state.get('generated_reply'):
            st.markdown("### 📝 Generated Reply")
            
            # Preview/Edit tabs
            tab1, tab2 = st.tabs(["✏️ Edit Reply", "👁️ Preview"])
            
            with tab1:
                edited_reply = st.text_area(
                    "Edit reply content:",
                    value=st.session_state.generated_reply,
                    height=250,
                    key="reply_editor",
                    help="You can edit the AI-generated reply before sending"
                )
                
                if edited_reply != st.session_state.generated_reply:
                    st.session_state.generated_reply = edited_reply
                
                # Character count
                char_count = len(edited_reply)
                if char_count > 1000:
                    st.warning(f"⚠️ Reply is quite long ({char_count} characters)")
                else:
                    st.caption(f"📊 {char_count} characters")
            
            with tab2:
                st.markdown("**Reply Preview:**")
                st.info(st.session_state.generated_reply)
            
            # Action buttons for the reply
            col_act1, col_act2, col_act3 = st.columns(3)
            
            with col_act1:
                if st.button("📄 Create Draft", key="create_draft", type="secondary", use_container_width=True):
                    with st.spinner("Creating draft in Gmail..."):
                        draft_id = email_reply_system.create_reply_draft(
                            email_data, st.session_state.generated_reply, 'ai_generated'
                        )
                        if draft_id:
                            st.success("✅ Draft created in Gmail!")
                        else:
                            st.error("❌ Failed to create draft")
            
            with col_act2:
                if st.button("📤 Send Reply", key="send_reply", type="primary", use_container_width=True):
                    if st.session_state.get("confirm_send", False):
                        with st.spinner("Sending reply..."):
                            reply_id = email_reply_system.send_reply(
                                email_data, st.session_state.generated_reply, 'ai_generated'
                            )
                            if reply_id:
                                st.success("✅ Reply sent successfully!")
                                st.session_state.show_reply_modal = False
                                st.session_state.generated_reply = ""
                                st.session_state.confirm_send = False
                                time.sleep(2)
                                st.rerun()
                            else:
                                st.error("❌ Failed to send reply")
                    else:
                        st.session_state.confirm_send = True
                        st.warning("Click again to confirm sending")
            
            with col_act3:
                if st.button("🔄 Regenerate", key="regenerate_reply", use_container_width=True):
                    with st.spinner("Regenerating reply..."):
                        new_reply = email_reply_system.generate_ai_reply(email_data, selected_type)
                        if new_reply:
                            st.session_state.generated_reply = new_reply
                            st.success("✅ Reply regenerated!")
                        else:
                            st.error("❌ Failed to regenerate")
        
        st.markdown("---")

    # ---------------- Email List UI ----------------
    def render_email_list(self, emails, tab_name):
        """Render email list with enhanced AI analysis and summary integration"""
        if not emails:
            st.markdown("""
            <div style='text-align: center; padding: 3rem; color: #666;'>
                <h3>📭 No emails found</h3>
                <p>Try adjusting your filters or sync with Gmail</p>
            </div>
            """, unsafe_allow_html=True)
            return

        # Enhanced CSS for email list styling
        st.markdown("""
        <style>
        .email-item {
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            margin: 8px 0;
            padding: 16px;
            background: white;
            transition: all 0.2s ease;
            cursor: pointer;
        }
        .email-item:hover {
            border-color: #1f77b4;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transform: translateY(-1px);
        }
        .email-unread {
            background: #f8f9fa;
            border-left: 4px solid #1f77b4;
            font-weight: 500;
        }
        .email-high-priority {
            border-left: 4px solid #ff4444;
            background: #fff5f5;
        }
        .email-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .sender-name {
            font-weight: 600;
            color: #333;
            font-size: 14px;
        }
        .email-date {
            color: #666;
            font-size: 12px;
        }
        .email-subject {
            font-size: 16px;
            color: #333;
            margin: 8px 0;
            font-weight: 500;
        }
        .email-snippet {
            color: #666;
            font-size: 14px;
            line-height: 1.4;
        }
        .email-category {
            display: inline-block;
            background: #e3f2fd;
            color: #1976d2;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 11px;
            margin: 4px 2px;
        }
        .ai-analysis {
            background: #f0f9ff;
            border: 1px solid #bfdbfe;
            border-radius: 6px;
            padding: 8px;
            margin: 8px 0;
            font-size: 13px;
        }
        .ai-summary {
            background: #f0fdf4;
            border: 1px solid #bbf7d0;
            border-radius: 6px;
            padding: 8px;
            margin: 8px 0;
            font-size: 13px;
        }
        .priority-badge {
            font-size: 18px;
            margin-right: 5px;
        }
        .sentiment-badge {
            font-size: 16px;
            margin-left: 5px;
        }
        </style>
        """, unsafe_allow_html=True)

        for i, email in enumerate(emails):
            email_id = email.get("id", i)
            subject = email.get("subject") or "No Subject"
            sender = self._extract_sender_name(email.get("sender", "Unknown"))
            date = self._format_date(email.get("date", ""))
            snippet = email.get("snippet", "")
            is_read = email.get("is_read", 0)
            category = email.get("category", "Other")

            # Get AI analysis if available
            analysis = None
            if st.session_state.show_ai_analysis:
                try:
                    db.cursor.execute("SELECT * FROM email_analysis WHERE email_id = ?", (email_id,))
                    analysis_row = db.cursor.fetchone()
                    if analysis_row:
                        analysis = dict(analysis_row)
                except Exception:
                    pass

            # Get AI summary if available
            summaries = []
            if st.session_state.show_ai_summary:
                summaries = email_summarizer.get_email_summaries(email_id)

            # Determine email styling
            unread_class = "email-unread" if not is_read else ""
            priority_class = ""
            priority_emoji = ""
            sentiment_emoji = ""
            
            if analysis:
                priority_score = analysis.get('priority_score', 3)
                priority_emoji = self._get_priority_emoji(priority_score)
                sentiment_emoji = self._get_sentiment_emoji(analysis.get('sentiment', 'neutral'))
                
                if priority_score >= 4:
                    priority_class = "email-high-priority"

            # Create email item container
            with st.container():
                st.markdown(f"""
                <div class="email-item {unread_class} {priority_class}">
                    <div class="email-header">
                        <div class="sender-name">
                            {'📩' if not is_read else '📖'} 
                            <span class="priority-badge">{priority_emoji}</span>
                            {sender}
                            <span class="sentiment-badge">{sentiment_emoji}</span>
                        </div>
                        <div class="email-date">{date}</div>
                    </div>
                    <div class="email-subject">{self._truncate_text(subject, 80)}</div>
                    <div class="email-snippet">{self._truncate_text(snippet, 120)}</div>
                    <span class="email-category">{category}</span>
                </div>
                """, unsafe_allow_html=True)

                # Show AI analysis if enabled
                if st.session_state.show_ai_analysis and analysis:
                    priority_score = analysis.get('priority_score', 0)
                    summary = analysis.get('summary', '')
                    action_required = analysis.get('action_required', False)
                    suggested_actions = json.loads(analysis.get('suggested_actions', '[]'))
                    
                    st.markdown(f"""
                    <div class="ai-analysis">
                        <strong>🤖 AI Analysis:</strong><br/>
                        <strong>Priority:</strong> {priority_score}/5 | 
                        <strong>Action Required:</strong> {'✅ Yes' if action_required else '❌ No'}<br/>
                        <strong>Summary:</strong> {self._truncate_text(summary, 100)}<br/>
                        {f'<strong>Actions:</strong> {", ".join(suggested_actions[:2])}' if suggested_actions else ''}
                    </div>
                    """, unsafe_allow_html=True)

                # Show AI summary if enabled
                if st.session_state.show_ai_summary and summaries:
                    latest_summary = summaries[0]  # Get most recent summary
                    brief_summary = latest_summary.get('brief_summary', '')
                    summary_type = latest_summary.get('summary_type', 'detailed')
                    compression_ratio = latest_summary.get('compression_ratio', 0)
                    
                    st.markdown(f"""
                    <div class="ai-summary">
                        <strong>📝 AI Summary ({summary_type}):</strong><br/>
                        {self._truncate_text(brief_summary, 150)}<br/>
                        <small>Compression: {compression_ratio}% | {len(summaries)} summary(ies) available</small>
                    </div>
                    """, unsafe_allow_html=True)

                # Enhanced action buttons
                col1, col2, col3, col4, col5, col6, col7 = st.columns([2, 1.5, 1.5, 1.5, 1.5, 1.5, 1])
                
                with col1:
                    if st.button("📖 View Details", key=f"detail_{tab_name}_{email_id}_{i}", help="View full email with AI analysis"):
                        st.session_state.selected_email = email_id
                        st.session_state.show_email_detail = True
                        self._show_email_detail_modal(email)
                
                with col2:
                    if not is_read and st.button("✅ Read", key=f"mark_{tab_name}_{email_id}_{i}", help="Mark as read"):
                        db.mark_email_as_read(email_id)
                        st.success("Marked as read!")
                        time.sleep(0.5)
                        st.rerun()
                
                with col3:
                    if st.button("Analyze", key=f"analyze_{tab_name}_{email_id}_{i}", help="Run AI analysis"):
                        self._analyze_single_email(email_id, dict(email))
                
                with col4:
                    if st.button("Summary", key=f"summary_{tab_name}_{email_id}_{i}", help="Generate AI summary"):
                        self._summarize_single_email(email_id, dict(email))
                
                with col5:
                    if st.button("Reply", key=f"reply_{tab_name}_{email_id}_{i}", help="Generate AI reply"):
                        self._show_reply_modal(email_id, dict(email))
                
                with col6:
                    if st.button("Draft", key=f"draft_{tab_name}_{email_id}_{i}", help="Quick draft reply"):
                        with st.spinner("Creating draft..."):
                            reply_content = email_reply_system.generate_ai_reply(dict(email), "acknowledge")
                            if reply_content:
                                draft_id = email_reply_system.create_reply_draft(dict(email), reply_content, 'ai_generated')
                                if draft_id:
                                    st.success("✅ Draft created!")
                                else:
                                    st.error("❌ Draft failed")
                
                with col7:
                    if st.button("🗑️", key=f"del_{tab_name}_{email_id}_{i}", help="Delete email"):
                        db.delete_email(email_id)
                        st.rerun()

    def _analyze_single_email(self, email_id: int, email_data: dict):
        """Analyze a single email with enhanced feedback"""
        with st.spinner("🤖 Analyzing email with AI..."):
            analysis = ai_analyzer.analyze_email(email_data)
            if analysis:
                st.success("✅ Email analyzed successfully!")
                st.info(f"Priority: {analysis.priority_score}/5 | Sentiment: {analysis.sentiment}")
                time.sleep(1)
                st.rerun()
            else:
                st.error("❌ Failed to analyze email")

    def _summarize_single_email(self, email_id: int, email_data: dict):
        """Summarize a single email with enhanced feedback"""
        with st.spinner("📝 Summarizing email with AI..."):
            summary = email_summarizer.summarize_email(email_data, "detailed")
            if summary:
                st.success("✅ Email summarized successfully!")
                st.info(f"Summary: {summary.compression_ratio}% compression | {len(summary.key_points)} key points")
                time.sleep(1)
                st.rerun()
            else:
                st.error("❌ Failed to summarize email")

    # ---------------- Pagination ----------------

    def render_pagination(self, total, page, size, tab_name):
        pages = max(1, (total + size - 1) // size)
        col1, col2, col3 = st.columns([1, 1, 3])

        if col1.button("⬅ Prev", key=f"prev_{tab_name}", disabled=(page <= 1)):
            st.session_state.current_page = max(1, page - 1)
            st.rerun()

        

        col3.write(f"📄 Page {page}/{pages} — {total} total")


        if col2.button("Next ➡", key=f"next_{tab_name}", disabled=(page >= pages)):
            st.session_state.current_page = min(pages, page + 1)
            st.rerun()


        if total == 0:
            st.caption("💡 Click **🔄 Refresh** to fetch emails from Gmail.")

    # ---------------- Main Render ----------------
    def render(self):
        st.set_page_config(
            page_title="🤖 AI Mail Dashboard", 
            layout="wide",
            initial_sidebar_state="expanded"
        )
        
        # Header with modern styling
        st.markdown("""
        <div style='text-align: center; padding: 1rem 0; margin-bottom: 2rem;'>
            <h1 style='color: #1f77b4; margin: 0;'>🤖 AI-Powered Mail Dashboard</h1>
            <p style='color: #666; margin: 0.5rem 0;'>Intelligent email management with AI analysis, summarization & auto-reply</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Handle modal states properly
        if st.session_state.get('show_email_detail') and st.session_state.get('selected_email'):
            try:
                db.cursor.execute("SELECT * FROM emails WHERE id = ?", (st.session_state.selected_email,))
                email_row = db.cursor.fetchone()
                if email_row:
                    self._show_email_detail_modal(dict(email_row))
                    return  # Don't render main dashboard when showing detail
                else:
                    # Email not found, reset state
                    st.session_state.show_email_detail = False
                    st.session_state.selected_email = None
            except Exception as e:
                st.error(f"Error loading email details: {e}")
                st.session_state.show_email_detail = False
                st.session_state.selected_email = None
        
        # Show reply modal if active
        if st.session_state.get('show_reply_modal') and st.session_state.get('selected_email'):
            try:
                db.cursor.execute("SELECT * FROM emails WHERE id = ?", (st.session_state.selected_email,))
                email_row = db.cursor.fetchone()
                if email_row:
                    self._show_reply_modal(st.session_state.selected_email, dict(email_row))
                else:
                    # Email not found, reset state
                    st.session_state.show_reply_modal = False
                    st.session_state.selected_email = None
            except Exception as e:
                st.error(f"Error loading reply modal: {e}")
                st.session_state.show_reply_modal = False
                st.session_state.selected_email = None
        
        # Show summary modal if active
        if st.session_state.get('show_summary_modal') and st.session_state.get('selected_email'):
            try:
                db.cursor.execute("SELECT * FROM emails WHERE id = ?", (st.session_state.selected_email,))
                email_row = db.cursor.fetchone()
                if email_row:
                    self._show_summary_modal(st.session_state.selected_email, dict(email_row))
                else:
                    # Email not found, reset state
                    st.session_state.show_summary_modal = False
                    st.session_state.selected_email = None
            except Exception as e:
                st.error(f"Error loading summary modal: {e}")
                st.session_state.show_summary_modal = False
                st.session_state.selected_email = None
        
        # Stats overview with enhanced AI metrics
        total_emails = db.get_total_email_count()
        if total_emails == 0:
            st.info("👈 **Welcome!** Click 'Sync Gmail' in the sidebar to fetch your emails.")
        else:
            # Get comprehensive stats
            unread = db.get_unread_count()
            ai_stats = ai_analyzer.get_analysis_stats()
            summary_stats = email_summarizer.get_summary_stats()
            reply_stats = email_reply_system.get_reply_stats()
            
            # Display stats in columns
            col_s1, col_s2, col_s3, col_s4, col_s5, col_s6 = st.columns(6)
            
            with col_s1:
                st.metric("📧 Total Emails", total_emails)
            with col_s2:
                st.metric("📩 Unread", unread)
            with col_s3:
                st.metric("🤖 AI Analyzed", ai_stats.get('total_analyzed', 0))
            with col_s4:
                st.metric("📝 Summarized", summary_stats.get('total_emails_summarized', 0))
            with col_s5:
                st.metric("🎯 Need Action", ai_stats.get('emails_requiring_action', 0))
            with col_s6:
                st.metric("↩️ Replies Sent", reply_stats.get('total_replies_sent', 0))

        # High Priority Alert with AI integration
        high_priority_emails = ai_analyzer.get_high_priority_emails(5)
        if high_priority_emails:
            st.warning(f"🔴 **{len(high_priority_emails)} high-priority emails need your attention!**")
            
            with st.expander("View High Priority Emails", expanded=False):
                for email in high_priority_emails[:3]:  # Show top 3
                    col_hp1, col_hp2, col_hp3 = st.columns([3, 1, 1])
                    with col_hp1:
                        st.markdown(f"**{email['subject']}** from {email['sender']}")
                        st.caption(f"Priority: {email['priority_score']}/5 - {email['priority_reason']}")
                    with col_hp2:
                        if st.button("📝 Summary", key=f"hp_sum_{email['id']}"):
                            self._summarize_single_email(email['id'], dict(email))
                    with col_hp3:
                        if st.button("📖 View", key=f"hp_{email['id']}"):
                            st.session_state.selected_email = email['id']
                            st.session_state.show_email_detail = True
                            st.rerun()

        self.render_sidebar()

        # Category tabs with enhanced counts including AI metrics
        tabs = ["Inbox", "Sent", "Drafts"]
        tab_counts = []
        for tab in tabs:
            count = db.get_total_email_count(tab)
            # Add AI analysis and summary counts
            try:
                db.cursor.execute("""
                    SELECT COUNT(*) as ai_count FROM emails e 
                    JOIN email_analysis a ON e.id = a.email_id 
                    WHERE e.category = ?
                """, (tab,))
                ai_count = db.cursor.fetchone()['ai_count']
                
                db.cursor.execute("""
                    SELECT COUNT(DISTINCT email_id) as summary_count FROM email_summaries s
                    JOIN emails e ON e.id = s.email_id 
                    WHERE e.category = ?
                """, (tab,))
                summary_count = db.cursor.fetchone()['summary_count']
                
                tab_counts.append(f"{tab} ({count}) 🤖{ai_count} 📝{summary_count}")
            except:
                tab_counts.append(f"{tab} ({count})")
        
        tab_objects = st.tabs(tab_counts)
        
        for i, tab_name in enumerate(tabs):
            with tab_objects[i]:
                page = st.session_state.current_page
                size = st.session_state.page_size
                
                # Build filters
                sender_filter = st.session_state.sender_filter.strip() or None
                subject_filter = st.session_state.subject_filter.strip() or None

                try:
                    # Get paginated emails with AI analysis
                    page_rows, total = db.get_emails_paginated(
                        page=page,
                        page_size=size,
                        category=tab_name,
                        sender_filter=sender_filter,
                        subject_filter=subject_filter,
                        include_unread_only=st.session_state.show_unread_only
                    )

                    # Apply priority filter if needed
                    if st.session_state.priority_filter:
                        filtered_rows = []
                        for row in page_rows:
                            try:
                                db.cursor.execute("SELECT priority_score FROM email_analysis WHERE email_id = ?", (row['id'],))
                                analysis_row = db.cursor.fetchone()
                                if analysis_row:
                                    priority = analysis_row['priority_score']
                                    if st.session_state.priority_filter == "high" and priority >= 4:
                                        filtered_rows.append(row)
                                    elif st.session_state.priority_filter == "medium" and priority == 3:
                                        filtered_rows.append(row)
                                    elif st.session_state.priority_filter == "low" and priority <= 2:
                                        filtered_rows.append(row)
                            except:
                                pass
                        page_rows = filtered_rows
                        total = len(filtered_rows)

                    # Show active filters
                    filters = []
                    if sender_filter:
                        filters.append(f"From: '{sender_filter}'")
                    if subject_filter:
                        filters.append(f"Subject: '{subject_filter}'")
                    if st.session_state.show_unread_only:
                        filters.append("Unread only")
                    if st.session_state.priority_filter:
                        filters.append(f"{st.session_state.priority_filter.title()} priority")
                    if st.session_state.show_ai_analysis:
                        filters.append("AI analysis visible")
                    if st.session_state.show_ai_summary:
                        filters.append("AI summaries visible")
                    
                    if filters:
                        st.markdown(f"**Active filters:** {' • '.join(filters)}")

                    # Pagination at top
                    self.render_pagination(total, page, size, f"{tab_name}_top")
                    
                    # Email list
                    self.render_email_list(page_rows, tab_name)
                    
                    # Pagination at bottom
                    if total > size:
                        st.markdown("---")
                        self.render_pagination(total, page, size, f"{tab_name}_bottom")
                    
                except Exception as e:
                    st.error(f"Error loading {tab_name} emails: {str(e)}")
                    st.info("Try syncing with Gmail or check your database connection.")

    
    
    def _snap_to_end(self):
        total = db.get_total_email_count()
        pages = max(1, (total + st.session_state.page_size - 1) // st.session_state.page_size)
        st.session_state.current_page = pages




def render_dashboard():
    EmailDashboard().render()


if __name__ == "__main__":
    render_dashboard()