"""
Lambda function to delete emails via API Gateway
Uses tombstone deletion (soft delete) with DynamoDB
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
    Delete email for authenticated user
    DELETE /api/emails/{id}?folder=inbox
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        user_email = user_context.get('email', 'newmail@example.com')
        # Extract username from email (before @)
        username = user_email.split('@')[0] if '@' in user_email else 'newmail'
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'email-delete')
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
        
        # Get bucket from environment
        bucket = os.environ.get('NEWMAIL_S3_BUCKET', 'BUCKET_NAME')
        table = dynamodb.Table('email-metadata')
        
        # Determine user ID for DynamoDB based on whether this is a group email
        if group_id:
            user_id_for_metadata = f"group:{group_id}"
        else:
            user_id_for_metadata = username
        
        try:
            # For all emails (including drafts), do soft delete: Mark as deleted in DynamoDB
            table.update_item(
                Key={
                    'userId': user_id_for_metadata,
                    'emailId': message_id
                },
                UpdateExpression='SET deleted = :true, deletedAt = :timestamp',
                ExpressionAttributeValues={
                    ':true': True,
                    ':timestamp': int(datetime.now().timestamp())
                }
            )
            
            print(f"Marked email as deleted: {user_id_for_metadata}/{message_id}")
            
            return cors_response(200, json.dumps({
                'success': True,
                'message': 'Email deleted'
            }))
        except Exception as e:
            print(f"Error marking email as deleted: {e}")
            import traceback
            traceback.print_exc()
            raise
        
    except s3.exceptions.NoSuchKey:
        return cors_response(404, json.dumps({'error': 'Email not found'}))
    except Exception as e:
        print(f"Error: {str(e)}")
        return cors_response(500, json.dumps({'error': str(e)}))

