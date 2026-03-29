"""
Lambda function to delete custom folders via API Gateway
Moves all emails in folder to inbox before deletion
"""
import json
import boto3
import time
from boto3.dynamodb.conditions import Key
from decimal import Decimal
from cors_config import cors_response
from rate_limiter import check_rate_limit, rate_limit_response

dynamodb = boto3.resource('dynamodb', region_name='us-west-2')

# Reserved folders that cannot be deleted
RESERVED_FOLDERS = ['inbox', 'sent', 'drafts', 'trash', 'quarantine']

def lambda_handler(event, context):
    """
    Delete a custom folder for authenticated user
    DELETE /api/folders/{id}
    Moves all emails in folder to inbox
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        username = user_context.get('email', 'newmail')
        if '@' in username:
            username = username.split('@')[0]
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'folder-delete')
        if not allowed:
            return rate_limit_response()
        
        # Get folder ID from path
        folder_id = event.get('pathParameters', {}).get('id')
        if not folder_id:
            return cors_response(400, json.dumps({'error': 'Folder ID is required'}))
        
        folder_id = folder_id.lower().strip()
        
        # Prevent deletion of reserved folders
        if folder_id in RESERVED_FOLDERS:
            return cors_response(400, json.dumps({'error': f"Cannot delete reserved folder '{folder_id}'"}))
        
        table = dynamodb.Table('email-metadata')
        
        # Get existing folders
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
        
        # Check if folder exists
        folder_exists = any(f['id'] == folder_id for f in folders)
        if not folder_exists:
            return cors_response(404, json.dumps({'error': f"Folder '{folder_id}' not found"}))
        
        # Move all emails in this folder to inbox
        try:
            # Query all emails in this folder
            emails_response = table.query(
                IndexName='FolderIndex',
                KeyConditionExpression=Key('userId').eq(username) & Key('folder').eq(folder_id)
            )
            
            emails_moved = 0
            for item in emails_response.get('Items', []):
                # Skip folder settings items
                if item['emailId'].startswith('settings:'):
                    continue
                
                # Move email to inbox
                table.update_item(
                    Key={
                        'userId': username,
                        'emailId': item['emailId']
                    },
                    UpdateExpression='SET folder = :inbox',
                    ExpressionAttributeValues={
                        ':inbox': 'inbox'
                    }
                )
                emails_moved += 1
            
            print(f"Moved {emails_moved} emails from '{folder_id}' to inbox")
        except Exception as e:
            print(f"Error moving emails: {e}")
            return cors_response(500, json.dumps({'error': f'Failed to move emails: {str(e)}'}))
        
        # Remove folder from settings
        folders = [f for f in folders if f['id'] != folder_id]
        
        # Update folder settings
        table.put_item(
            Item={
                'userId': username,
                'emailId': 'settings:folders',
                'folders': folders,
                'updatedAt': int(time.time())
            }
        )
        
        return cors_response(
            200,
            json.dumps({
                'message': f"Folder '{folder_id}' deleted successfully",
                'emailsMoved': emails_moved
            })
        )
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return cors_response(
            500,
            json.dumps({'error': str(e)})
        )

