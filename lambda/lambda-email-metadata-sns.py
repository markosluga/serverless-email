"""
Lambda function to extract email metadata from SES SNS notifications
Handles both personal emails and group emails
Stores metadata in DynamoDB
"""
import boto3
import json
import os
from email.utils import parsedate_to_datetime
from datetime import datetime

s3 = boto3.client('s3')
sns = boto3.client('sns', region_name='us-west-2')
dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
metadata_table = dynamodb.Table('email-metadata')
groups_table = dynamodb.Table('email-groups')

SNS_TOPIC_ARN = 'arn:aws:sns:us-west-2:ACCOUNT_ID:EmailEvents'

def process_s3_event(record):
    """
    Process S3 event when email is uploaded (for large emails with attachments)
    """
    from email import message_from_bytes
    from email.utils import parsedate_to_datetime
    
    try:
        bucket = record['s3']['bucket']['name']
        key = record['s3']['object']['key']
        
        print(f"Processing S3 event: s3://{bucket}/{key}")
        
        # Extract message ID from the S3 key (it's the filename)
        # Key format: users/{username}/inbox/{messageId} or groups/{groupId}/inbox/{messageId}
        parts = key.split('/')
        if len(parts) < 4:
            print(f"Invalid S3 key format: {key}")
            return
        
        message_id = parts[-1]  # Last part is the message ID
        
        # Skip and delete SES setup notification emails
        if message_id == 'AMAZON_SES_SETUP_NOTIFICATION':
            print(f"Detected SES setup notification, deleting: {key}")
            try:
                s3.delete_object(Bucket=bucket, Key=key)
                print(f"Deleted SES setup notification from S3: {key}")
            except Exception as e:
                print(f"Error deleting SES setup notification: {e}")
            return  # Don't process this email further
        
        # Download email from S3
        response = s3.get_object(Bucket=bucket, Key=key)
        email_content = response['Body'].read()
        
        # Parse email
        email_message = message_from_bytes(email_content)
        
        # Extract metadata
        sender = email_message.get('From', 'unknown')
        subject = email_message.get('Subject', '(no subject)')
        date_str = email_message.get('Date', '')
        to = email_message.get('To', '')
        
        # Parse timestamp
        try:
            if date_str:
                date_obj = parsedate_to_datetime(date_str)
                timestamp = int(date_obj.timestamp())
            else:
                timestamp = int(datetime.now().timestamp())
        except:
            timestamp = int(datetime.now().timestamp())
        
        # Determine if this is a group or personal email based on S3 key
        if parts[0] == 'groups':
            # Group email
            group_id = parts[1]
            folder = parts[2]  # Should be 'inbox'
            
            # Get recipient email from the key path
            recipient_email = f"{group_id}@example.com"
            
            # Check if this is a group
            group = get_group(recipient_email)
            
            if group:
                store_group_metadata(message_id, group_id, group, recipient_email,
                                   sender, subject, date_str, to, timestamp, folder)
            else:
                print(f"Group {recipient_email} not found in groups table")
        
        elif parts[0] == 'users':
            # Personal email
            username = parts[1]
            folder = parts[2]  # Should be 'inbox'
            
            # Get recipients from the To field
            recipients = [username + '@example.com']
            
            store_personal_metadata(message_id, username, sender, subject,
                                  date_str, to, timestamp, folder)
        
        else:
            print(f"Unknown S3 key prefix: {parts[0]}")
    
    except Exception as e:
        print(f"Error processing S3 event: {str(e)}")
        import traceback
        traceback.print_exc()

def lambda_handler(event, context):
    """
    Extract sender and subject from email stored in S3 and store metadata in DynamoDB
    Triggered by S3 ObjectCreated:Put events when SES writes emails
    Supports both personal emails (userId) and group emails (groupId)
    """
    for record in event['Records']:
        # Process S3 event
        if 's3' in record:
            process_s3_event(record)
        else:
            print(f"Skipping non-S3 event type: {list(record.keys())}")
    
    return {
        'statusCode': 200,
        'body': json.dumps('Metadata stored successfully')
    }

def get_group(email):
    """
    Check if email address is a group and return group details
    """
    try:
        response = groups_table.get_item(Key={'groupEmail': email})
        item = response.get('Item')
        
        if item and item.get('enabled', False):
            return item
        return None
    except Exception as e:
        print(f"Error checking if {email} is group: {str(e)}")
        return None

def store_group_metadata(message_id, group_id, group, group_email, sender, subject, date_str, to, timestamp, folder):
    """
    Store metadata for group email using userId field with 'group:' prefix
    """
    try:
        s3_key = f"groups/{group_id}/inbox/{message_id}"
        
        # Use userId with 'group:' prefix to distinguish from personal emails
        item = {
            'userId': f"group:{group_id}",
            'emailId': message_id,
            'folder': folder,
            'timestamp': timestamp,
            'read': False,
            'subject': subject[:1000],
            'from': sender[:500],
            'to': to[:500],
            'date': date_str[:100],
            's3Key': s3_key,
            'groupEmail': group_email,
            'groupName': group.get('groupName', group_id),
            'isGroup': True,
            'groupId': group_id
        }
        
        metadata_table.put_item(Item=item)
        
        print(f"Stored GROUP metadata: group:{group_id}/{folder}/{message_id}")
        print(f"  Group: {group_email}")
        print(f"  From: {sender}")
        print(f"  Subject: {subject}")
        print(f"  Members: {len(group.get('members', []))}")
        
        # Publish notification for each group member
        for member in group.get('members', []):
            member_username = member.split('@')[0] if '@' in member else member
            publish_notification(member_username, sender, subject, message_id, 
                               is_group=True, group_name=group.get('groupName', group_id))
        
    except Exception as e:
        print(f"Error storing group metadata for {message_id}: {str(e)}")
        import traceback
        traceback.print_exc()

def publish_notification(user_id, sender, subject, email_id, is_group=False, group_name=''):
    """
    Publish notification to SNS for push notifications
    """
    try:
        message = {
            'userId': user_id,
            'from': sender,
            'subject': subject,
            'emailId': email_id,
            'isGroup': is_group,
            'groupName': group_name
        }
        
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=json.dumps(message),
            Subject='New Email Notification'
        )
        
        print(f"Published notification to SNS for user {user_id}")
    except Exception as e:
        print(f"Error publishing to SNS: {str(e)}")
        # Don't fail the whole process if SNS publish fails

def store_personal_metadata(message_id, username, sender, subject, date_str, to, timestamp, folder):
    """
    Store metadata for personal email with userId as partition key
    """
    try:
        s3_key = f"users/{username}/inbox/{message_id}"
        
        item = {
            'userId': username,
            'emailId': message_id,
            'folder': folder,
            'timestamp': timestamp,
            'read': False,
            'subject': subject[:1000],
            'from': sender[:500],
            'to': to[:500],
            'date': date_str[:100],
            's3Key': s3_key
        }
        
        metadata_table.put_item(Item=item)
        
        print(f"Stored PERSONAL metadata: {username}/{folder}/{message_id}")
        print(f"  From: {sender}")
        print(f"  Subject: {subject}")
        
        # Publish notification for push notifications
        publish_notification(username, sender, subject, message_id)
        
    except Exception as e:
        print(f"Error storing personal metadata for {message_id}: {str(e)}")
        import traceback
        traceback.print_exc()

