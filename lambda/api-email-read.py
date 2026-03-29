"""
Lambda function to read a single email via API Gateway
Uses DynamoDB for metadata tracking (no S3 copy operations)
Invalidates inbox summary cache when marking emails as read
"""
import json
import boto3
import os
import re
from email import message_from_bytes
from decimal import Decimal
from cors_config import cors_response, get_cors_headers
from rate_limiter import check_rate_limit, rate_limit_response

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
S3_BUCKET = 'BUCKET_NAME'

def lambda_handler(event, context):
    """
    Read email content for authenticated user
    GET /api/emails/{id}?folder=inbox
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        username = user_context.get('email', 'newmail')
        if '@' in username:
            username = username.split('@')[0]
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'email-read')
        if not allowed:
            return rate_limit_response()
        
        # Get path parameters
        message_id = event.get('pathParameters', {}).get('id')
        if not message_id:
            return cors_response(400, json.dumps({'error': 'Missing message ID'}))
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        folder = params.get('folder', 'inbox')
        group_id = params.get('group', None)
        mark_read = params.get('mark_read', 'true').lower() == 'true'  # Default to true for backward compatibility
        
        # Get bucket from environment
        bucket = os.environ.get('NEWMAIL_S3_BUCKET', 'BUCKET_NAME')
        
        # Determine S3 key based on whether this is a group email
        if group_id:
            # Group email
            if folder == 'drafts' and not message_id.endswith('.json'):
                # Drafts stored in drafts/ prefix to avoid S3 notifications
                key = f"drafts/group-{group_id}/{message_id}.json"
            else:
                key = f"groups/{group_id}/{folder}/{message_id}"
            user_id_for_metadata = f"group:{group_id}"
        else:
            # Personal email
            if folder == 'drafts' and not message_id.endswith('.json'):
                # Drafts stored in drafts/ prefix to avoid S3 notifications
                key = f"drafts/{username}/{message_id}.json"
            else:
                key = f"users/{username}/{folder}/{message_id}"
            user_id_for_metadata = username
        
        # Get email from S3
        response = s3.get_object(Bucket=bucket, Key=key)
        email_content = response['Body'].read()
        
        # Handle drafts (JSON format)
        if folder == 'drafts':
            draft_data = json.loads(email_content)
            return cors_response(200, json.dumps({
                'id': message_id,
                'from': 'Draft',
                'to': [draft_data.get('to', '')],
                'cc': [draft_data.get('cc', '')] if draft_data.get('cc') else [],
                'subject': draft_data.get('subject', ''),
                'date': draft_data.get('savedAt', ''),
                'body': draft_data.get('body', ''),
                'html_body': '',
                'attachments': []
            }))
        
        # Parse email
        msg = message_from_bytes(email_content)
        
        # Decode MIME encoded-word headers (like subject with emojis)
        from email.header import decode_header
        
        def decode_mime_header(header_value):
            """Decode MIME encoded-word format to proper Unicode"""
            if not header_value:
                return ''
            decoded_parts = decode_header(header_value)
            result = []
            for content, encoding in decoded_parts:
                if isinstance(content, bytes):
                    result.append(content.decode(encoding or 'utf-8', errors='ignore'))
                else:
                    result.append(content)
            return ''.join(result)
        
        # Extract email data
        email_data = {
            'id': message_id,
            'from': decode_mime_header(msg.get('From', '')),
            'to': msg.get('To', '').split(',') if msg.get('To') else [],
            'cc': msg.get('Cc', '').split(',') if msg.get('Cc') else [],
            'subject': decode_mime_header(msg.get('Subject', '')),
            'date': msg.get('Date', ''),
            'body': '',
            'html_body': '',
            'attachments': [],
            'calendar': None
        }
        
        # Extract body and attachments
        # Store inline images for CID replacement
        inline_images = {}
        calendar_data = None
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get('Content-Disposition', ''))
                
                # Skip multipart containers
                if content_type.startswith('multipart/'):
                    continue
                
                # Handle calendar invites (text/calendar)
                if content_type == 'text/calendar':
                    try:
                        calendar_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        calendar_data = parse_calendar_invite(calendar_text)
                    except Exception as e:
                        print(f"Error parsing calendar invite: {e}")
                    continue
                
                # Check for inline images (images with Content-ID)
                content_id = part.get('Content-Id') or part.get('Content-ID')
                if content_id and content_type.startswith('image/'):
                    # Remove < > brackets from Content-ID
                    cid = content_id.strip('<>')
                    
                    # Store inline image in S3 for access
                    try:
                        image_data = part.get_payload(decode=True)
                        filename = part.get_filename() or f"{cid}.{content_type.split('/')[-1]}"
                        
                        # Store in temp location
                        temp_key = f"temp/inline-images/{user_id_for_metadata}/{message_id}/{cid}"
                        s3.put_object(
                            Bucket=bucket,
                            Key=temp_key,
                            Body=image_data,
                            ContentType=content_type
                        )
                        
                        # Generate presigned URL (valid for 24 hours)
                        presigned_url = s3.generate_presigned_url(
                            'get_object',
                            Params={
                                'Bucket': bucket,
                                'Key': temp_key
                            },
                            ExpiresIn=86400
                        )
                        
                        inline_images[cid] = presigned_url
                        
                        # Also add to attachments list if it has a filename
                        if part.get_filename():
                            email_data['attachments'].append({
                                'filename': filename,
                                'size': len(image_data),
                                'content_type': content_type,
                                'inline': True,
                                'cid': cid
                            })
                    except Exception as e:
                        print(f"Error processing inline image {cid}: {e}")
                
                elif 'attachment' in content_disposition or part.get_filename():
                    # Handle both explicit attachments and parts with filenames
                    filename = part.get_filename()
                    if filename:
                        try:
                            payload = part.get_payload(decode=True)
                            email_data['attachments'].append({
                                'filename': filename,
                                'size': len(payload or b''),
                                'content_type': content_type
                            })
                        except Exception as e:
                            print(f"Error processing attachment {filename}: {e}")
                elif content_type == 'text/plain':
                    # Always capture plain text (may be overwritten by better version)
                    try:
                        email_data['body'] = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    except:
                        pass
                elif content_type == 'text/html':
                    # Always capture HTML (may be overwritten by better version)
                    try:
                        email_data['html_body'] = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    except:
                        pass
        else:
            # Single part message
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                if content_type == 'text/html':
                    email_data['html_body'] = payload
                else:
                    email_data['body'] = payload
            except:
                email_data['body'] = str(msg.get_payload())
        
        # Replace cid: references in HTML with presigned URLs
        if email_data['html_body'] and inline_images:
            import re
            html = email_data['html_body']
            for cid, url in inline_images.items():
                # Replace cid: references (handle both with and without cid: prefix)
                html = re.sub(f'src=["\']cid:{re.escape(cid)}["\']', f'src="{url}"', html, flags=re.IGNORECASE)
                html = re.sub(f'src=["\']cid:{re.escape(cid.split("@")[0])}["\']', f'src="{url}"', html, flags=re.IGNORECASE)
            email_data['html_body'] = html
        
        # Add calendar data if found
        if calendar_data:
            print(f"Calendar data parsed: {json.dumps(calendar_data, indent=2)}")
            email_data['calendar'] = calendar_data
        
        # Mark as read in DynamoDB (no S3 copy operation!) - only if mark_read is True
        if mark_read:
            try:
                table = dynamodb.Table('email-metadata')
                table.update_item(
                    Key={
                        'userId': user_id_for_metadata,
                        'emailId': message_id
                    },
                    UpdateExpression='SET #read = :true',
                    ExpressionAttributeNames={
                        '#read': 'read'
                    },
                    ExpressionAttributeValues={
                        ':true': True
                    }
                )
                
                # Invalidate inbox summary cache so chat sees the updated read status
                if not group_id:  # Only for personal emails
                    invalidate_inbox_summary_cache(username)
                    
            except Exception as e:
                print(f"Error marking as read in DynamoDB: {e}")
        else:
            print(f"Skipping mark as read (mark_read=false parameter provided)")
        
        return cors_response(200, json.dumps(email_data))
        
    except s3.exceptions.NoSuchKey:
        return cors_response(404, json.dumps({'error': 'Email not found'}))
    except Exception as e:
        print(f"Error: {str(e)}")
        return cors_response(500, json.dumps({'error': str(e)}))


def parse_calendar_invite(calendar_text):
    """Parse iCalendar data and extract event details"""
    try:
        # Simple parser for iCalendar format
        lines = calendar_text.split('\n')
        event = {
            'summary': None,
            'description': None,
            'location': None,
            'start': None,
            'end': None,
            'start_tz': None,
            'end_tz': None,
            'organizer': None,
            'attendees': [],
            'status': None,
            'method': None,
            'uid': None
        }
        
        in_vevent = False
        current_field = None
        
        for line in lines:
            line = line.strip()
            
            # Handle line continuations (lines starting with space)
            if line.startswith(' ') and current_field:
                event[current_field] += line[1:]
                continue
            
            if line == 'BEGIN:VEVENT':
                in_vevent = True
                continue
            elif line == 'END:VEVENT':
                in_vevent = False
                continue
            
            if not in_vevent and line.startswith('METHOD:'):
                event['method'] = line.split(':', 1)[1].strip()
            
            if in_vevent:
                if line.startswith('UID:'):
                    event['uid'] = line.split(':', 1)[1].strip()
                    current_field = None
                elif line.startswith('SUMMARY:'):
                    event['summary'] = line.split(':', 1)[1].strip()
                    current_field = 'summary'
                elif line.startswith('DESCRIPTION:'):
                    event['description'] = line.split(':', 1)[1].strip()
                    current_field = 'description'
                elif line.startswith('LOCATION:'):
                    event['location'] = line.split(':', 1)[1].strip()
                    current_field = 'location'
                elif line.startswith('DTSTART'):
                    # Handle both DTSTART and DTSTART;TZID=...
                    # Extract timezone if present
                    tz = None
                    if 'TZID=' in line:
                        tz_part = line.split('TZID=')[1].split(':')[0]
                        tz = tz_part.strip()
                    
                    dt_value = line.split(':', 1)[1].strip() if ':' in line else None
                    if dt_value:
                        event['start'], event['start_tz'] = format_ical_datetime(dt_value, tz)
                    current_field = None
                elif line.startswith('DTEND'):
                    # Extract timezone if present
                    tz = None
                    if 'TZID=' in line:
                        tz_part = line.split('TZID=')[1].split(':')[0]
                        tz = tz_part.strip()
                    
                    dt_value = line.split(':', 1)[1].strip() if ':' in line else None
                    if dt_value:
                        event['end'], event['end_tz'] = format_ical_datetime(dt_value, tz)
                    current_field = None
                elif line.startswith('ORGANIZER'):
                    # Extract email from ORGANIZER:mailto:email@example.com or ORGANIZER;CN=Name:mailto:email
                    organizer_line = line.split(':', 1)[1] if ':' in line else ''
                    if 'mailto:' in organizer_line:
                        event['organizer'] = organizer_line.split('mailto:')[1].strip()
                    current_field = None
                elif line.startswith('ATTENDEE'):
                    # Extract email from ATTENDEE:mailto:email@example.com
                    attendee_line = line.split(':', 1)[1] if ':' in line else ''
                    if 'mailto:' in attendee_line:
                        event['attendees'].append(attendee_line.split('mailto:')[1].strip())
                    current_field = None
                elif line.startswith('STATUS:'):
                    event['status'] = line.split(':', 1)[1].strip()
                    current_field = None
                else:
                    current_field = None
        
        # Only return if we found at least a summary or start time
        if event['summary'] or event['start']:
            return event
        
        return None
        
    except Exception as e:
        print(f"Error parsing calendar: {e}")
        return None


def format_ical_datetime(dt_string, timezone=None):
    """Format iCalendar datetime to readable format with timezone"""
    try:
        # Handle formats like: 20250115T190000Z or 20250115T190000
        dt_string = dt_string.replace('Z', '').replace('-', '').replace(':', '')
        
        # Map common timezone identifiers to abbreviations
        tz_map = {
            'America/New_York': 'EST/EDT',
            'America/Chicago': 'CST/CDT',
            'America/Denver': 'MST/MDT',
            'America/Los_Angeles': 'PST/PDT',
            'America/Phoenix': 'MST',
            'America/Anchorage': 'AKST/AKDT',
            'America/Honolulu': 'HST',
            'Europe/London': 'GMT/BST',
            'Europe/Paris': 'CET/CEST',
            'Europe/Berlin': 'CET/CEST',
            'Asia/Tokyo': 'JST',
            'Asia/Shanghai': 'CST',
            'Asia/Hong_Kong': 'HKT',
            'Asia/Singapore': 'SGT',
            'Australia/Sydney': 'AEDT/AEST',
            'Pacific/Auckland': 'NZDT/NZST'
        }
        
        if 'T' in dt_string:
            # DateTime format
            date_part, time_part = dt_string.split('T')
            year = date_part[0:4]
            month = date_part[4:6]
            day = date_part[6:8]
            hour = time_part[0:2]
            minute = time_part[2:4]
            
            from datetime import datetime
            dt = datetime(int(year), int(month), int(day), int(hour), int(minute))
            
            # Format with timezone
            formatted_date = dt.strftime('%Y-%m-%d %H:%M')
            
            # Add timezone if available
            if timezone:
                # Get timezone abbreviation if known
                tz_abbr = tz_map.get(timezone, timezone)
                return formatted_date, tz_abbr
            else:
                # If no timezone specified, it's UTC
                return formatted_date, 'UTC'
        else:
            # Date only format
            year = dt_string[0:4]
            month = dt_string[4:6]
            day = dt_string[6:8]
            return f"{year}-{month}-{day}", None
    except:
        return dt_string, timezone


def invalidate_inbox_summary_cache(username):
    """Invalidate the inbox summary cache when emails are read"""
    try:
        cache_key = f"ai/summary/{username}/inbox-summary.json"
        s3.delete_object(Bucket=S3_BUCKET, Key=cache_key)
        print(f"✅ Invalidated inbox summary cache for {username}")
    except s3.exceptions.NoSuchKey:
        print(f"No cache to invalidate for {username}")
    except Exception as e:
        print(f"Warning: Failed to invalidate cache: {str(e)}")

