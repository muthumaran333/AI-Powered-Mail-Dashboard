# # src/email_processing/fetch_emails.py

# import base64
# import time
# from datetime import datetime
# from src.auth.gmail_auth import authenticate_gmail
# from src.utils.logger import logger
# from src.storage.sqlite_manager import SQLiteManager, map_labels_to_category

# db = SQLiteManager()

# class EmailFetcher:
#     def __init__(self):
#         self.service = None
#         self._authenticate()

#     def _authenticate(self):
#         """Initialize Gmail service"""
#         try:
#             self.service = authenticate_gmail()
#             logger.info("✅ Gmail service authenticated successfully")
#         except Exception as e:
#             logger.error(f"❌ Failed to authenticate Gmail service: {e}")
#             raise

#     def _get_label_map(self):
#         """Fetch Gmail labels and map by id"""
#         try:
#             results = self.service.users().labels().list(userId="me").execute()
#             labels = results.get("labels", [])
#             return {lbl["id"]: lbl["name"] for lbl in labels}
#         except Exception as e:
#             logger.warning(f"Could not fetch Gmail labels: {e}")
#             return {}

#     def _categorize_email(self, labels, sender, to_recipients):
#         """Enhanced email categorization"""
#         category = map_labels_to_category(labels)
        
#         # Additional logic for "No Reply" detection
#         if category == "Sent":
#             # Check if this sent email has received replies
#             # This would be done in a post-processing step
#             pass
            
#         return category

#     def _clean_email_content(self, text):
#         """Clean and normalize email content"""
#         if not text:
#             return ""
        
#         # Remove excessive whitespace and normalize
#         text = ' '.join(text.split())
        
#         # Remove common email artifacts
#         text = text.replace('\r\n', '\n').replace('\r', '\n')
        
#         return text.strip()

#     def fetch_email_batch(self, page_token=None, batch_size=50):
#         """Fetch one batch of emails with improved error handling"""
#         try:
#             params = {
#                 "userId": "me",
#                 "maxResults": batch_size,
#                 "includeSpamTrash": False,  # Exclude spam/trash
#             }
#             if page_token:
#                 params["pageToken"] = page_token

#             # First, get the list of message IDs
#             results = self.service.users().messages().list(**params).execute()
#             messages = results.get("messages", [])
#             next_page_token = results.get("nextPageToken")

#             if not messages:
#                 logger.info("📭 No messages found in this batch")
#                 return [], next_page_token

#             logger.info(f"📨 Processing {len(messages)} messages...")

#             emails = []
#             processed_count = 0
            
#             for msg in messages:
#                 try:
#                     email_data = self._process_email(msg["id"])
#                     if email_data:
#                         emails.append(email_data)
#                         processed_count += 1
                        
#                         # Progress logging every 10 emails
#                         if processed_count % 10 == 0:
#                             logger.info(f"📊 Processed {processed_count}/{len(messages)} emails")
                            
#                 except Exception as e:
#                     logger.error(f"❌ Failed to process email {msg['id']}: {e}")
#                     continue

#             logger.info(f"✅ Successfully processed {len(emails)} emails in batch")
#             return emails, next_page_token
            
#         except Exception as e:
#             logger.error(f"❌ Error fetching email batch: {e}")
#             return [], None

#     def _process_email(self, email_id):
#         """Process single email with enhanced data extraction"""
#         try:
#             # Fetch full message with all parts
#             full_msg = self.service.users().messages().get(
#                 userId="me", 
#                 id=email_id, 
#                 format="full"
#             ).execute()

#             # Extract headers
#             headers = {h["name"]: h["value"] for h in full_msg["payload"].get("headers", [])}
            
#             # Core email data
#             subject = headers.get("Subject", "No Subject")
#             sender = headers.get("From", "Unknown Sender")
#             to_recipients = headers.get("To", "")
#             date = headers.get("Date", "Unknown Date")
            
#             # Additional headers for better categorization
#             cc_recipients = headers.get("Cc", "")
#             bcc_recipients = headers.get("Bcc", "")
#             reply_to = headers.get("Reply-To", "")
            
#             # Gmail metadata
#             thread_id = full_msg.get("threadId")
#             history_id = full_msg.get("historyId")
#             snippet = self._clean_email_content(full_msg.get("snippet", ""))
#             labels = full_msg.get("labelIds", [])
            
#             # Determine category
#             category = self._categorize_email(labels, sender, to_recipients)
            
#             # Determine read status from labels
#             is_read = 0 if "UNREAD" in labels else 1

#             # Extract body and attachments
#             body, attachments = self._extract_content_and_attachments(full_msg["payload"], email_id)
#             body = self._clean_email_content(body)

#             # Store in database
#             db_email_id = db.upsert_email(
#                 gmail_id=email_id,
#                 thread_id=thread_id,
#                 history_id=history_id,
#                 sender=sender,
#                 to_recipients=to_recipients,
#                 subject=subject,
#                 date=date,
#                 snippet=snippet,
#                 body=body,
#                 category=category,
#                 labels=",".join(labels),
#                 is_read=is_read
#             )

#             # Store attachments
#             for att in attachments:
#                 db.insert_attachment(
#                     db_email_id,
#                     att["filename"],
#                     att.get("content"),
#                     att.get("content_preview"),
#                     att["size"]
#                 )

#             logger.info(f"📩 Stored: {subject[:50]}... [{category}]")
            
#             return {
#                 "id": db_email_id,
#                 "gmail_id": email_id,
#                 "thread_id": thread_id,
#                 "sender": sender,
#                 "to_recipients": to_recipients,
#                 "subject": subject,
#                 "date": date,
#                 "snippet": snippet,
#                 "body": body,
#                 "category": category,
#                 "labels": labels,
#                 "is_read": is_read,
#                 "attachments": len(attachments),
#             }
            
#         except Exception as e:
#             logger.error(f"❌ Error processing email {email_id}: {e}")
#             return None

#     def _extract_content_and_attachments(self, payload, msg_id):
#         """Enhanced content and attachment extraction"""
#         body_parts = []
#         attachments = []
        
#         def process_part(part):
#             mime_type = part.get("mimeType", "")
#             body_data = part.get("body", {})
            
#             # Handle text content
#             if mime_type in ["text/plain", "text/html"]:
#                 data = body_data.get("data")
#                 if data:
#                     try:
#                         decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
#                         body_parts.append(decoded)
#                     except Exception as e:
#                         logger.warning(f"Failed to decode body part: {e}")
            
#             # Handle attachments
#             attachment_id = body_data.get("attachmentId")
#             filename = part.get("filename", "")
            
#             if attachment_id and filename:
#                 try:
#                     # Fetch attachment
#                     att_data = self.service.users().messages().attachments().get(
#                         userId="me", 
#                         messageId=msg_id, 
#                         id=attachment_id
#                     ).execute()
                    
#                     raw_data = base64.urlsafe_b64decode(att_data["data"])
                    
#                     # Create preview for text-based files
#                     preview = ""
#                     if filename.lower().endswith(('.txt', '.csv', '.json', '.xml', '.log')):
#                         try:
#                             preview = raw_data[:1000].decode("utf-8", errors="ignore")
#                         except:
#                             preview = "Binary file - no preview available"
                    
#                     attachments.append({
#                         "filename": filename,
#                         "size": len(raw_data),
#                         "content": raw_data,
#                         "content_preview": preview,
#                         "mime_type": mime_type
#                     })
                    
#                     logger.info(f"📎 Attachment: {filename} ({len(raw_data)} bytes)")
                    
#                 except Exception as e:
#                     logger.warning(f"Failed to fetch attachment {filename}: {e}")
#                     # Store attachment metadata even if content fetch fails
#                     attachments.append({
#                         "filename": filename,
#                         "size": 0,
#                         "content": None,
#                         "content_preview": "Failed to fetch attachment content",
#                         "mime_type": mime_type
#                     })
            
#             # Process nested parts
#             if "parts" in part:
#                 for subpart in part["parts"]:
#                     process_part(subpart)

#         # Start processing
#         if "parts" in payload:
#             for part in payload["parts"]:
#                 process_part(part)
#         else:
#             # Single part message
#             process_part(payload)

#         # Combine body parts
#         combined_body = "\n\n".join(body_parts) if body_parts else ""
        
#         return combined_body, attachments

#     def fetch_all_emails(self, batch_size=100, max_emails=None):
#         """Fetch all emails with progress tracking and limits"""
#         logger.info("🚀 Starting comprehensive Gmail sync...")
        
#         page_token = db.get_sync_metadata("last_page_token")
#         total_processed = 0
#         batch_count = 0
#         start_time = time.time()
        
#         try:
#             while True:
#                 batch_count += 1
#                 logger.info(f"📦 Processing batch {batch_count}...")
                
#                 emails, next_token = self.fetch_email_batch(page_token, batch_size)
#                 current_batch_size = len(emails)
#                 total_processed += current_batch_size

#                 # Update sync metadata
#                 db.update_sync_metadata("last_page_token", next_token or "")
#                 db.update_sync_metadata("last_sync_time", str(int(time.time())))
                
#                 # Progress reporting
#                 elapsed = time.time() - start_time
#                 rate = total_processed / elapsed if elapsed > 0 else 0
#                 logger.info(
#                     f"📊 Batch {batch_count}: {current_batch_size} emails | "
#                     f"Total: {total_processed} | Rate: {rate:.1f} emails/sec"
#                 )

#                 # Check stopping conditions
#                 if not next_token or current_batch_size == 0:
#                     logger.info("📭 Reached end of mailbox")
#                     break
                    
#                 if max_emails and total_processed >= max_emails:
#                     logger.info(f"📈 Reached limit of {max_emails} emails")
#                     break
                
#                 page_token = next_token
                
#                 # Small delay to be nice to the API
#                 time.sleep(0.1)

#             # Final statistics
#             elapsed_minutes = (time.time() - start_time) / 60
#             logger.info(
#                 f"✅ Sync complete: {total_processed} emails processed "
#                 f"in {elapsed_minutes:.1f} minutes ({batch_count} batches)"
#             )
            
#             return total_processed
            
#         except Exception as e:
#             logger.error(f"❌ Sync failed after {total_processed} emails: {e}")
#             return total_processed

#     def sync_recent_emails(self, days_back=7):
#         """Sync only recent emails for quick updates"""
#         logger.info(f"🔄 Syncing emails from last {days_back} days...")
        
#         # This would require date-based filtering in Gmail API
#         # For now, just fetch a smaller batch
#         emails, _ = self.fetch_email_batch(batch_size=50)
        
#         logger.info(f"✅ Recent sync complete: {len(emails)} emails")
#         return len(emails)


# # Singleton instance
# email_fetcher = EmailFetcher()

# def fetch_email_list(batch_size=50, page_token=None):
#     """Convenience function for dashboard UI"""
#     return email_fetcher.fetch_email_batch(page_token, batch_size)

# def sync_gmail_full():
#     """Full Gmail sync - use carefully with large mailboxes"""
#     return email_fetcher.fetch_all_emails()

# def sync_gmail_recent():
#     """Quick sync of recent emails"""
#     return email_fetcher.sync_recent_emails()




# src/email_processing/fetch_emails.py

import base64
import time
from datetime import datetime
from src.auth.gmail_auth import authenticate_gmail
from src.utils.logger import logger
from src.storage.sqlite_manager import SQLiteManager, map_labels_to_category

db = SQLiteManager()

class EmailFetcher:
    def __init__(self):
        self.service = None
        self._authenticate()

    def _authenticate(self):
        """Initialize Gmail service"""
        try:
            self.service = authenticate_gmail()
            logger.info("✅ Gmail service authenticated successfully")
        except Exception as e:
            logger.error(f"❌ Failed to authenticate Gmail service: {e}")
            raise

    def _get_label_map(self):
        """Fetch Gmail labels and map by id"""
        try:
            results = self.service.users().labels().list(userId="me").execute()
            labels = results.get("labels", [])
            return {lbl["id"]: lbl["name"] for lbl in labels}
        except Exception as e:
            logger.warning(f"Could not fetch Gmail labels: {e}")
            return {}

    def _categorize_email(self, labels, sender, to_recipients):
        """Enhanced email categorization"""
        category = map_labels_to_category(labels)
        
        # Additional logic for "No Reply" detection
        if category == "Sent":
            # Check if this sent email has received replies
            # This would be done in a post-processing step
            pass
            
        return category

    def _clean_email_content(self, text):
        """Clean and normalize email content"""
        if not text:
            return ""
        
        # Remove excessive whitespace and normalize
        text = ' '.join(text.split())
        
        # Remove common email artifacts
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        return text.strip()

    def fetch_email_batch(self, page_token=None, batch_size=50):
        """Fetch one batch of emails with improved error handling and deduplication"""
        try:
            params = {
                "userId": "me",
                "maxResults": batch_size,
                "includeSpamTrash": False,  # Exclude spam/trash
            }
            if page_token and page_token.strip():
                params["pageToken"] = page_token

            # First, get the list of message IDs
            results = self.service.users().messages().list(**params).execute()
            messages = results.get("messages", [])
            next_page_token = results.get("nextPageToken")

            if not messages:
                logger.info("📭 No messages found in this batch")
                return [], next_page_token

            logger.info(f"📨 Processing {len(messages)} messages...")

            emails = []
            processed_count = 0
            skipped_count = 0
            
            # Get existing Gmail IDs to avoid duplicates
            existing_ids = set()
            try:
                db.cursor.execute("SELECT DISTINCT gmail_id FROM emails WHERE gmail_id IS NOT NULL")
                existing_ids = {row['gmail_id'] for row in db.cursor.fetchall()}
            except Exception as e:
                logger.warning(f"Could not fetch existing Gmail IDs: {e}")
            
            for msg in messages:
                try:
                    gmail_id = msg["id"]
                    
                    # Skip if email already exists
                    if gmail_id in existing_ids:
                        skipped_count += 1
                        continue
                    
                    email_data = self._process_email(gmail_id)
                    if email_data:
                        emails.append(email_data)
                        processed_count += 1
                        
                        # Progress logging every 10 emails
                        if processed_count % 10 == 0:
                            logger.info(f"📊 Processed {processed_count}/{len(messages)} emails")
                            
                except Exception as e:
                    logger.error(f"❌ Failed to process email {msg['id']}: {e}")
                    continue

            logger.info(f"✅ Successfully processed {len(emails)} new emails in batch (skipped {skipped_count} existing)")
            return emails, next_page_token
            
        except Exception as e:
            logger.error(f"❌ Error fetching email batch: {e}")
            return [], None

    def _process_email(self, email_id):
        """Process single email with enhanced data extraction"""
        try:
            # Fetch full message with all parts
            full_msg = self.service.users().messages().get(
                userId="me", 
                id=email_id, 
                format="full"
            ).execute()

            # Extract headers
            headers = {h["name"]: h["value"] for h in full_msg["payload"].get("headers", [])}
            
            # Core email data
            subject = headers.get("Subject", "No Subject")
            sender = headers.get("From", "Unknown Sender")
            to_recipients = headers.get("To", "")
            date = headers.get("Date", "Unknown Date")
            
            # Additional headers for better categorization
            cc_recipients = headers.get("Cc", "")
            bcc_recipients = headers.get("Bcc", "")
            reply_to = headers.get("Reply-To", "")
            
            # Gmail metadata
            thread_id = full_msg.get("threadId")
            history_id = full_msg.get("historyId")
            snippet = self._clean_email_content(full_msg.get("snippet", ""))
            labels = full_msg.get("labelIds", [])
            
            # Determine category
            category = self._categorize_email(labels, sender, to_recipients)
            
            # Determine read status from labels
            is_read = 0 if "UNREAD" in labels else 1

            # Extract body and attachments
            body, attachments = self._extract_content_and_attachments(full_msg["payload"], email_id)
            body = self._clean_email_content(body)

            # Store in database with proper error handling
            try:
                db_email_id = db.upsert_email(
                    gmail_id=email_id,
                    thread_id=thread_id,
                    history_id=history_id,
                    sender=sender,
                    to_recipients=to_recipients,
                    subject=subject,
                    date=date,
                    snippet=snippet,
                    body=body,
                    category=category,
                    labels=",".join(labels),
                    is_read=is_read
                )

                # Store attachments
                for att in attachments:
                    try:
                        db.insert_attachment(
                            db_email_id,
                            att["filename"],
                            att.get("content"),
                            att.get("content_preview"),
                            att["size"]
                        )
                    except Exception as e:
                        logger.warning(f"Failed to store attachment {att['filename']}: {e}")

                logger.info(f"📩 Stored: {subject[:50]}... [{category}]")
                
                return {
                    "id": db_email_id,
                    "gmail_id": email_id,
                    "thread_id": thread_id,
                    "sender": sender,
                    "to_recipients": to_recipients,
                    "subject": subject,
                    "date": date,
                    "snippet": snippet,
                    "body": body,
                    "category": category,
                    "labels": labels,
                    "is_read": is_read,
                    "attachments": len(attachments),
                }
            
            except Exception as e:
                logger.error(f"❌ Error storing email {email_id}: {e}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error processing email {email_id}: {e}")
            return None

    def _extract_content_and_attachments(self, payload, msg_id):
        """Enhanced content and attachment extraction with better error handling"""
        body_parts = []
        attachments = []
        
        def process_part(part):
            try:
                mime_type = part.get("mimeType", "")
                body_data = part.get("body", {})
                
                # Handle text content
                if mime_type in ["text/plain", "text/html"]:
                    data = body_data.get("data")
                    if data:
                        try:
                            decoded = base64.urlsafe_b64decode(data + '===').decode("utf-8", errors="ignore")
                            body_parts.append(decoded)
                        except Exception as e:
                            logger.warning(f"Failed to decode body part: {e}")
                
                # Handle attachments
                attachment_id = body_data.get("attachmentId")
                filename = part.get("filename", "")
                
                if attachment_id and filename:
                    try:
                        # Fetch attachment with retry logic
                        max_retries = 3
                        for retry in range(max_retries):
                            try:
                                att_data = self.service.users().messages().attachments().get(
                                    userId="me", 
                                    messageId=msg_id, 
                                    id=attachment_id
                                ).execute()
                                break
                            except Exception as e:
                                if retry == max_retries - 1:
                                    raise e
                                time.sleep(1)  # Wait before retry
                        
                        raw_data = base64.urlsafe_b64decode(att_data["data"] + '===')
                        
                        # Create preview for text-based files
                        preview = ""
                        if filename.lower().endswith(('.txt', '.csv', '.json', '.xml', '.log')):
                            try:
                                preview = raw_data[:1000].decode("utf-8", errors="ignore")
                            except:
                                preview = "Binary file - no preview available"
                        
                        attachments.append({
                            "filename": filename,
                            "size": len(raw_data),
                            "content": raw_data,
                            "content_preview": preview,
                            "mime_type": mime_type
                        })
                        
                        logger.info(f"📎 Attachment: {filename} ({len(raw_data)} bytes)")
                        
                    except Exception as e:
                        logger.warning(f"Failed to fetch attachment {filename}: {e}")
                        # Store attachment metadata even if content fetch fails
                        attachments.append({
                            "filename": filename,
                            "size": 0,
                            "content": None,
                            "content_preview": "Failed to fetch attachment content",
                            "mime_type": mime_type
                        })
                
                # Process nested parts
                if "parts" in part:
                    for subpart in part["parts"]:
                        process_part(subpart)
                        
            except Exception as e:
                logger.warning(f"Error processing email part: {e}")

        # Start processing
        try:
            if "parts" in payload:
                for part in payload["parts"]:
                    process_part(part)
            else:
                # Single part message
                process_part(payload)
        except Exception as e:
            logger.error(f"Error processing email payload: {e}")

        # Combine body parts
        combined_body = "\n\n".join(body_parts) if body_parts else ""
        
        return combined_body, attachments

    def fetch_all_emails(self, batch_size=100, max_emails=None):
        """Fetch all emails with progress tracking and limits"""
        logger.info("🚀 Starting comprehensive Gmail sync...")
        
        page_token = db.get_sync_metadata("last_page_token")
        if page_token and page_token.strip() == "":
            page_token = None
            
        total_processed = 0
        batch_count = 0
        start_time = time.time()
        
        try:
            while True:
                batch_count += 1
                logger.info(f"📦 Processing batch {batch_count}...")
                
                emails, next_token = self.fetch_email_batch(page_token, batch_size)
                current_batch_size = len(emails)
                total_processed += current_batch_size

                # Update sync metadata
                db.update_sync_metadata("last_page_token", next_token or "")
                db.update_sync_metadata("last_sync_time", str(int(time.time())))
                
                # Progress reporting
                elapsed = time.time() - start_time
                rate = total_processed / elapsed if elapsed > 0 else 0
                logger.info(
                    f"📊 Batch {batch_count}: {current_batch_size} emails | "
                    f"Total: {total_processed} | Rate: {rate:.1f} emails/sec"
                )

                # Check stopping conditions
                if not next_token or current_batch_size == 0:
                    logger.info("📭 Reached end of mailbox")
                    break
                    
                if max_emails and total_processed >= max_emails:
                    logger.info(f"📈 Reached limit of {max_emails} emails")
                    break
                
                page_token = next_token
                
                # Small delay to be nice to the API
                time.sleep(0.1)

            # Final statistics
            elapsed_minutes = (time.time() - start_time) / 60
            logger.info(
                f"✅ Sync complete: {total_processed} emails processed "
                f"in {elapsed_minutes:.1f} minutes ({batch_count} batches)"
            )
            
            return total_processed
            
        except Exception as e:
            logger.error(f"❌ Sync failed after {total_processed} emails: {e}")
            return total_processed

    def sync_recent_emails(self, days_back=7):
        """Sync only recent emails for quick updates"""
        logger.info(f"🔄 Syncing emails from last {days_back} days...")
        
        # This would require date-based filtering in Gmail API
        # For now, just fetch a smaller batch
        emails, _ = self.fetch_email_batch(batch_size=50)
        
        logger.info(f"✅ Recent sync complete: {len(emails)} emails")
        return len(emails)

    def get_sync_status(self):
        """Get current synchronization status"""
        try:
            last_sync = db.get_sync_metadata("last_sync_time")
            last_token = db.get_sync_metadata("last_page_token")
            total_fetched = db.get_sync_metadata("total_emails_fetched")
            
            return {
                "last_sync_time": datetime.fromtimestamp(int(last_sync)) if last_sync else None,
                "has_more_emails": bool(last_token and last_token.strip()),
                "total_emails_fetched": int(total_fetched) if total_fetched else 0,
                "emails_in_db": db.get_total_email_count()
            }
        except Exception as e:
            logger.error(f"Error getting sync status: {e}")
            return {
                "last_sync_time": None,
                "has_more_emails": False,
                "total_emails_fetched": 0,
                "emails_in_db": db.get_total_email_count()
            }


# Singleton instance
email_fetcher = EmailFetcher()

def fetch_email_list(batch_size=50, page_token=None):
    """Convenience function for dashboard UI"""
    return email_fetcher.fetch_email_batch(page_token, batch_size)

def sync_gmail_full():
    """Full Gmail sync - use carefully with large mailboxes"""
    return email_fetcher.fetch_all_emails()

def sync_gmail_recent():
    """Quick sync of recent emails"""
    return email_fetcher.sync_recent_emails()

def get_sync_status():
    """Get synchronization status"""
    return email_fetcher.get_sync_status()