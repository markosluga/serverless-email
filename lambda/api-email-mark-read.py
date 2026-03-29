"""
Lambda function to mark emails as read/unread
Updates the read flag in DynamoDB and invalidates inbox summary cache
If email doesn't exist in DynamoDB, creates metadata entry from S3
"""
import json
import boto3
from email import message_from_bytes
from email.utils import parsedate_to_datetime
from datetime import datetime
from cors_config import cors_response
from rate_limiter import check_rate_limit, rate_limit_response

dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
s3 = boto3.client('s3', region_name='us-west-2')
S3_BUCKET = 'BUCKET_NAME'

def lambda_handler(event, context):
    """
    Mark email as read or unread
    PUT /api/emails/{id}/read
    Body: {"read": true/false}
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        user_email = user_context.get('email', 'newmail@example.com')
        username = user_email.split('@')[0] if '@' in user_email else 'newmail'
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'email-mark-read')
        if not allowed:
            return rate_limit_response()
        
        # Get path parameters
        message_id = event.get('pathParameters', {}).get('id')
        if not message_id:
            return cors_response(400, json.dumps({'error': 'Missing message ID'}))
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        group_id = params.get('group', None)
        
        # Parse body
        body = json.loads(event.get('body', '{}'))
        read_status = body.get('read', True)
        
        # Determine user ID for DynamoDB
        if group_id:
            user_id_for_metadata = f"group:{group_id}"
        else:
            user_id_for_metadata = username
        
        # Update DynamoDB
        table = dynamodb.Table('email-metadata')
        
        try:
            # Try to update existing item
            table.update_item(
                Key={
                    'userId': user_id_for_metadata,
                    'emailId': message_id
                },
                UpdateExpression='SET #read = :read',
                ExpressionAttributeNames={
                    '#read': 'read'
                },
                ExpressionAttributeValues={
                    ':read': read_status
                },
                ConditionExpression='attribute_exists(userId)'
            )
            print(f"Updated existing email: {user_id_for_metadata}/{message_id}")
            
        except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            # Email doesn't exist in DynamoDB yet - create metadata entry
            print(f"Email not in DynamoDB, creating metadata entry: {user_id_for_metadata}/{message_id}")
            
            # Fetch email from S3 to get metadata
            try:
                # Determine S3 key based on whether it's a group or personal email
                if group_id:
                    s3_key = f"groups/{group_id}/inbox/{message_id}"
                else:
                    s3_key = f"users/{username}/inbox/{message_id}"
                
                # Get email from S3
                response = s3.get_object(Bucket=S3_BUCKET, Key=s3_key)
                email_content = response['Body'].read()
                
                # Parse email to extract metadata
                from email import message_from_bytes
                from email.utils import parsedate_to_datetime
                from datetime import datetime
                
                msg = message_from_bytes(email_content)
                sender = msg.get('From', 'unknown')
                subject = msg.get('Subject', '(no subject)')
                date_str = msg.get('Date', '')
                to = msg.get('To', '')
                
                # Parse timestamp
                try:
                    if date_str:
                        date_obj = parsedate_to_datetime(date_str)
                        timestamp = int(date_obj.timestamp())
                    else:
                        timestamp = int(datetime.now().timestamp())
                except:
                    timestamp = int(datetime.now().timestamp())
                
                # Create metadata entry
                item = {
                    'userId': user_id_for_metadata,
                    'emailId': message_id,
                    'folder': 'inbox',
                    'timestamp': timestamp,
                    'read': read_status,
                    'subject': subject[:1000],
                    'from': sender[:500],
                    'to': to[:500],
                    'date': date_str[:100],
                    's3Key': s3_key
                }
                
                # Add group-specific fields if this is a group email
                if group_id:
                    item['isGroup'] = True
                    item['groupId'] = group_id
                
                table.put_item(Item=item)
                print(f"Created metadata entry for email: {user_id_for_metadata}/{message_id}")
                
            except s3.exceptions.NoSuchKey:
                # Email doesn't exist in S3 either
                return cors_response(404, json.dumps({'error': 'Email not found'}))
            except Exception as e:
                print(f"Error creating metadata entry: {str(e)}")
                import traceback
                traceback.print_exc()
                return cors_response(500, json.dumps({'error': f'Failed to create metadata: {str(e)}'}))
        
        print(f"Marked email as {'read' if read_status else 'unread'}: {user_id_for_metadata}/{message_id}")
        
        # Invalidate inbox summary cache when marking as read
        if read_status:
            invalidate_inbox_summary_cache(username)
        
        return cors_response(200, json.dumps({
            'success': True,
            'message': f"Email marked as {'read' if read_status else 'unread'}"
        }))
        
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        # This should never happen now since we handle it above
        return cors_response(404, json.dumps({'error': 'Email not found'}))
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return cors_response(500, json.dumps({'error': str(e)}))


def invalidate_inbox_summary_cache(username):
    """Invalidate the inbox summary cache when emails are marked as read"""
    try:
        cache_key = f"ai/summary/{username}/inbox-summary.json"
        s3.delete_object(Bucket=S3_BUCKET, Key=cache_key)
        print(f"✅ Invalidated inbox summary cache for {username}")
    except s3.exceptions.NoSuchKey:
        print(f"No cache to invalidate for {username}")
    except Exception as e:
        print(f"Warning: Failed to invalidate cache: {str(e)}")

