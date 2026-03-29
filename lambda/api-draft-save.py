"""
Lambda function to save draft emails via API Gateway
"""
import json
import boto3
import os
from datetime import datetime
from cors_config import cors_response, get_cors_headers
from rate_limiter import check_rate_limit, rate_limit_response

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb', region_name='us-west-2')

def lambda_handler(event, context):
    """
    Save draft email for authenticated user
    POST /api/drafts
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        user_email = user_context.get('email', 'newmail@example.com')
        username = user_email.split('@')[0] if '@' in user_email else 'newmail'
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'draft-save')
        if not allowed:
            return rate_limit_response()
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        
        # Generate draft ID
        draft_id = f"draft-{int(datetime.utcnow().timestamp() * 1000)}"
        
        # Get bucket from environment
        bucket = os.environ.get('NEWMAIL_S3_BUCKET', 'BUCKET_NAME')
        # Store drafts outside users/ prefix to avoid S3 notification triggers
        key = f"drafts/{username}/{draft_id}.json"
        
        # Save draft to S3
        draft_data = {
            'id': draft_id,
            'to': body.get('to', ''),
            'cc': body.get('cc', ''),
            'subject': body.get('subject', ''),
            'body': body.get('body', ''),
            'savedAt': datetime.utcnow().isoformat()
        }
        
        # Save draft to S3
        try:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(draft_data),
                ContentType='application/json'
            )
            print(f"Draft saved to S3: {key}")
        except Exception as e:
            print(f"Error saving draft to S3: {e}")
            raise
        
        # Also save metadata to DynamoDB
        try:
            table = dynamodb.Table('email-metadata')
            current_time = datetime.utcnow()
            table.put_item(
                Item={
                    'userId': username,
                    'emailId': draft_id,
                    'folder': 'drafts',
                    'timestamp': int(current_time.timestamp()),
                    'read': True,  # Drafts are always "read"
                    'deleted': False,
                    'subject': body.get('subject', '(no subject)'),
                    'from': 'Draft',
                    'to': body.get('to', ''),
                    'date': current_time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                }
            )
            print(f"Draft metadata saved to DynamoDB: {draft_id}")
        except Exception as e:
            print(f"Warning: Could not save draft metadata to DynamoDB: {e}")
            import traceback
            traceback.print_exc()
        
        return cors_response(200, json.dumps({
            'success': True,
            'draft_id': draft_id
        }))
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return cors_response(500, json.dumps({'error': str(e)}))

