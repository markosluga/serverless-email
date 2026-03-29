"""
Lambda function to send emails via API Gateway
"""
import json
import boto3
import os
import base64
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formataddr
from email.header import Header
from datetime import datetime
from cors_config import cors_response, get_cors_headers
from rate_limiter import check_rate_limit, rate_limit_response

ses = boto3.client('ses', region_name='us-west-2')
s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
S3_BUCKET = 'BUCKET_NAME'

def sanitize_email(email):
    """Remove control characters and extra whitespace from email address"""
    if not email:
        return ''
    # Remove all control characters (including newlines, tabs, etc.)
    email = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', email)
    # Strip whitespace
    email = email.strip()
    return email

def extract_email_address(email_string):
    """Extract just the email address from 'Name <email@domain.com>' format"""
    if not email_string:
        return ''
    
    # Sanitize first
    email_string = sanitize_email(email_string)
    
    # Check if it's in "Name <email>" format
    match = re.search(r'<([^>]+)>', email_string)
    if match:
        return match.group(1).strip()
    
    # Otherwise return as-is (already sanitized)
    return email_string

def format_email_header(email_string):
    """Format email address for headers, handling international characters properly"""
    if not email_string:
        return ''
    
    # Sanitize first
    email_string = sanitize_email(email_string)
    
    # Check if it's in "Name <email>" format
    match = re.match(r'^(.+?)\s*<([^>]+)>$', email_string)
    if match:
        name = match.group(1).strip()
        email = match.group(2).strip()
        # Use formataddr to properly encode international characters
        return formataddr((name, email))
    
    # Just an email address
    return email_string

def lambda_handler(event, context):
    """
    Send email for authenticated user
    POST /api/emails
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        user_email = user_context.get('email', 'newmail@example.com')
        # Extract username from email (before @)
        username = user_email.split('@')[0] if '@' in user_email else 'newmail'
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'email-send')
        if not allowed:
            return rate_limit_response()
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        
        # Sanitize email addresses - remove empty strings, whitespace, and control characters
        to_addresses = [sanitize_email(addr) for addr in body.get('to', []) if sanitize_email(addr)]
        cc_addresses = [sanitize_email(addr) for addr in body.get('cc', []) if sanitize_email(addr)]
        subject = body.get('subject', '')
        email_body = body.get('body', '')
        html_body = body.get('html_body', '')
        attachments = body.get('attachments', [])
        
        print(f"To addresses: {to_addresses}")
        print(f"CC addresses: {cc_addresses}")
        print(f"From: {user_email}")
        
        if not to_addresses or not subject:
            return cors_response(400, json.dumps({'error': 'Missing required fields: to, subject'}))
        
        # Create email message
        msg = MIMEMultipart()
        msg['From'] = user_email
        # Format addresses properly for headers (handles international characters)
        msg['To'] = ', '.join([format_email_header(addr) for addr in to_addresses])
        if cc_addresses:
            msg['Cc'] = ', '.join([format_email_header(addr) for addr in cc_addresses])
        msg['Subject'] = subject
        msg['Date'] = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')
        
        # Add body (HTML or plain text)
        if html_body:
            msg.attach(MIMEText(html_body, 'html'))
        else:
            msg.attach(MIMEText(email_body, 'plain'))
        
        # Add attachments
        for attachment in attachments:
            try:
                filename = attachment.get('filename')
                content = attachment.get('content')  # base64 encoded
                content_type = attachment.get('content_type', 'application/octet-stream')
                
                # Decode base64 content
                file_data = base64.b64decode(content)
                
                # Create MIME attachment
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(file_data)
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                
                msg.attach(part)
                print(f"Added attachment: {filename} ({len(file_data)} bytes)")
            except Exception as e:
                print(f"Error adding attachment {filename}: {e}")
                # Continue with other attachments
        
        # Send via SES
        # Extract plain email addresses for Destinations (SES doesn't accept "Name <email>" format here)
        to_plain = [extract_email_address(addr) for addr in to_addresses]
        cc_plain = [extract_email_address(addr) for addr in cc_addresses]
        
        print(f"To plain addresses: {to_plain}")
        print(f"CC plain addresses: {cc_plain}")
        print(f"All destinations: {to_plain + cc_plain}")
        
        response = ses.send_raw_email(
            Source=user_email,
            Destinations=to_plain + cc_plain,
            RawMessage={'Data': msg.as_bytes()}
        )
        
        message_id = response['MessageId']
        
        # Store in sent folder
        bucket = os.environ.get('NEWMAIL_S3_BUCKET', 'BUCKET_NAME')
        key = f"users/{username}/sent/{message_id}"
        
        # Encode metadata to ASCII (S3 metadata only supports ASCII)
        def encode_ascii(text):
            """Encode text to ASCII, replacing non-ASCII characters"""
            try:
                return text.encode('ascii', errors='ignore').decode('ascii')
            except:
                return text
        
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=msg.as_bytes(),
            ContentType='message/rfc822',
            Metadata={
                'sender': encode_ascii(user_email),
                'subject': encode_ascii(subject),
                'date': encode_ascii(msg['Date'])
            }
        )
        
        # Store metadata in DynamoDB (sent emails don't have "read" property)
        try:
            table = dynamodb.Table('email-metadata')
            # For sent emails, store recipient in 'to' field (not sender)
            recipient_display = msg['To']  # This includes the formatted "Name <email>" if present
            
            table.put_item(
                Item={
                    'userId': username,
                    'emailId': message_id,
                    'folder': 'sent',
                    'timestamp': int(datetime.now().timestamp()),
                    'subject': subject[:1000],
                    'from': user_email,
                    'to': recipient_display[:500],  # Store the formatted recipient
                    'date': msg['Date']
                }
            )
            print(f"Sent email metadata saved to DynamoDB: {message_id}")
        except Exception as e:
            print(f"Warning: Could not save sent email metadata to DynamoDB: {e}")
        
        # Invalidate inbox summary cache after sending (especially for replies)
        invalidate_inbox_summary_cache(username)
        
        return cors_response(200, json.dumps({
            'success': True,
            'message_id': message_id
        }))
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return cors_response(500, json.dumps({'error': str(e)}))


def invalidate_inbox_summary_cache(username):
    """Invalidate the inbox summary cache when emails are sent (especially replies)"""
    try:
        cache_key = f"ai/summary/{username}/inbox-summary.json"
        s3.delete_object(Bucket=S3_BUCKET, Key=cache_key)
        print(f"✅ Invalidated inbox summary cache for {username}")
    except s3.exceptions.NoSuchKey:
        print(f"No cache to invalidate for {username}")
    except Exception as e:
        print(f"Warning: Failed to invalidate cache: {str(e)}")

