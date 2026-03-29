"""
Lambda function to permanently delete emails
Removes from both S3 and DynamoDB
"""
import json
import boto3
import os
from cors_config import cors_response
from rate_limiter import check_rate_limit, rate_limit_response

s3 = boto3.client('s3')
dynamodb = boto3.resource('dynamodb', region_name='us-west-2')

def lambda_handler(event, context):
    """
    Permanently delete email (remove from S3 and DynamoDB)
    DELETE /api/emails/{id}/permanent
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        user_email = user_context.get('email', 'newmail@example.com')
        username = user_email.split('@')[0] if '@' in user_email else 'newmail'
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'email-permanent-delete')
        if not allowed:
            return rate_limit_response()
        
        # Get path parameters
        message_id = event.get('pathParameters', {}).get('id')
        if not message_id:
            return cors_response(400, json.dumps({'error': 'Missing message ID'}))
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        group_id = params.get('group', None)
        
        bucket = os.environ.get('NEWMAIL_S3_BUCKET', 'BUCKET_NAME')
        table = dynamodb.Table('email-metadata')
        
        # Determine user ID for DynamoDB
        if group_id:
            user_id_for_metadata = f"group:{group_id}"
        else:
            user_id_for_metadata = username
        
        # Get email metadata to find the folder
        try:
            response = table.get_item(
                Key={
                    'userId': user_id_for_metadata,
                    'emailId': message_id
                }
            )
            
            if 'Item' not in response:
                return cors_response(404, json.dumps({'error': 'Email not found'}))
            
            folder = response['Item'].get('folder', 'inbox')
            
        except Exception as e:
            print(f"Error getting email metadata: {e}")
            return cors_response(404, json.dumps({'error': 'Email not found'}))
        
        # Delete from S3
        if group_id:
            key = f"groups/{group_id}/{folder}/{message_id}"
        else:
            key = f"users/{username}/{folder}/{message_id}"
        
        try:
            s3.delete_object(Bucket=bucket, Key=key)
            print(f"Deleted from S3: {key}")
        except Exception as e:
            print(f"Warning: Could not delete from S3: {e}")
            # Continue anyway - metadata deletion is more important
        
        # Delete from DynamoDB
        try:
            table.delete_item(
                Key={
                    'userId': user_id_for_metadata,
                    'emailId': message_id
                }
            )
            print(f"Deleted from DynamoDB: {user_id_for_metadata}/{message_id}")
        except Exception as e:
            print(f"Error deleting from DynamoDB: {e}")
            raise
        
        return cors_response(200, json.dumps({
            'success': True,
            'message': 'Email permanently deleted'
        }))
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return cors_response(500, json.dumps({'error': str(e)}))

