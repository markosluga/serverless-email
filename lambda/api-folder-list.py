"""
Lambda function to list custom folders via API Gateway
Stores folder metadata in DynamoDB
"""
import json
import boto3
from boto3.dynamodb.conditions import Key
from decimal import Decimal
from cors_config import cors_response
from rate_limiter import check_rate_limit, rate_limit_response

dynamodb = boto3.resource('dynamodb', region_name='us-west-2')

class DecimalEncoder(json.JSONEncoder):
    """Helper to convert Decimal to int/float for JSON"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super(DecimalEncoder, self).default(obj)

def lambda_handler(event, context):
    """
    List custom folders for authenticated user
    GET /api/folders
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        username = user_context.get('email', 'newmail')
        if '@' in username:
            username = username.split('@')[0]
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'folder-list')
        if not allowed:
            return rate_limit_response()
        
        # Get folder settings from DynamoDB
        table = dynamodb.Table('email-metadata')
        
        try:
            response = table.get_item(
                Key={
                    'userId': username,
                    'emailId': 'settings:folders'
                }
            )
            
            if 'Item' in response:
                folders = response['Item'].get('folders', [])
            else:
                folders = []
        except Exception as e:
            print(f"Error fetching folders: {e}")
            folders = []
        
        # Sort by order
        folders.sort(key=lambda x: x.get('order', 999))
        
        return cors_response(
            200,
            json.dumps({
                'folders': folders,
                'total': len(folders)
            }, cls=DecimalEncoder)
        )
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return cors_response(
            500,
            json.dumps({'error': str(e)})
        )

