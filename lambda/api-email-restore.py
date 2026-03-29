"""
Lambda function to restore emails from trash
Unmarks the deleted flag in DynamoDB
"""
import json
import boto3
from cors_config import cors_response
from rate_limiter import check_rate_limit, rate_limit_response

dynamodb = boto3.resource('dynamodb', region_name='us-west-2')

def lambda_handler(event, context):
    """
    Restore email from trash (unmark as deleted)
    PUT /api/emails/{id}/restore
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        user_email = user_context.get('email', 'newmail@example.com')
        username = user_email.split('@')[0] if '@' in user_email else 'newmail'
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'email-restore')
        if not allowed:
            return rate_limit_response()
        
        # Get path parameters
        message_id = event.get('pathParameters', {}).get('id')
        if not message_id:
            return cors_response(400, json.dumps({'error': 'Missing message ID'}))
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        group_id = params.get('group', None)
        
        # Determine user ID for DynamoDB
        if group_id:
            user_id_for_metadata = f"group:{group_id}"
        else:
            user_id_for_metadata = username
        
        # Update DynamoDB to unmark as deleted
        table = dynamodb.Table('email-metadata')
        table.update_item(
            Key={
                'userId': user_id_for_metadata,
                'emailId': message_id
            },
            UpdateExpression='REMOVE deleted, deletedAt',
            ConditionExpression='attribute_exists(userId)'
        )
        
        print(f"Restored email: {user_id_for_metadata}/{message_id}")
        
        return cors_response(200, json.dumps({
            'success': True,
            'message': 'Email restored'
        }))
        
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        return cors_response(404, json.dumps({'error': 'Email not found'}))
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return cors_response(500, json.dumps({'error': str(e)}))

