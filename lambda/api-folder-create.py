"""
Lambda function to create custom folders via API Gateway
Stores folder metadata in DynamoDB
"""
import json
import boto3
import re
import time
from decimal import Decimal
from cors_config import cors_response
from rate_limiter import check_rate_limit, rate_limit_response

dynamodb = boto3.resource('dynamodb', region_name='us-west-2')

# Reserved folder names that cannot be used
RESERVED_FOLDERS = ['inbox', 'sent', 'drafts', 'trash', 'quarantine']
MAX_FOLDERS = 50

def validate_folder_id(folder_id):
    """Validate folder ID format"""
    if not folder_id:
        return False, "Folder ID is required"
    
    if len(folder_id) > 50:
        return False, "Folder ID must be 50 characters or less"
    
    if folder_id.lower() in RESERVED_FOLDERS:
        return False, f"'{folder_id}' is a reserved folder name"
    
    if not re.match(r'^[a-z0-9-]+$', folder_id):
        return False, "Folder ID must contain only lowercase letters, numbers, and hyphens"
    
    return True, None

def lambda_handler(event, context):
    """
    Create a custom folder for authenticated user
    POST /api/folders
    Body: {"id": "work", "name": "Work", "color": "#FF5733", "icon": "💼"}
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        username = user_context.get('email', 'newmail')
        if '@' in username:
            username = username.split('@')[0]
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'folder-create')
        if not allowed:
            return rate_limit_response()
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        folder_id = body.get('id', '').lower().strip()
        folder_name = body.get('name', '').strip()
        folder_color = body.get('color', '#6B7280')
        folder_icon = body.get('icon', '📁')
        
        # Validate folder ID
        valid, error = validate_folder_id(folder_id)
        if not valid:
            return cors_response(400, json.dumps({'error': error}))
        
        # Validate folder name
        if not folder_name:
            return cors_response(400, json.dumps({'error': 'Folder name is required'}))
        
        if len(folder_name) > 100:
            return cors_response(400, json.dumps({'error': 'Folder name must be 100 characters or less'}))
        
        # Get existing folders
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
        
        # Check if folder already exists
        if any(f['id'] == folder_id for f in folders):
            return cors_response(400, json.dumps({'error': f"Folder '{folder_id}' already exists"}))
        
        # Check folder limit
        if len(folders) >= MAX_FOLDERS:
            return cors_response(400, json.dumps({'error': f'Maximum {MAX_FOLDERS} custom folders allowed'}))
        
        # Create new folder
        new_folder = {
            'id': folder_id,
            'name': folder_name,
            'color': folder_color,
            'icon': folder_icon,
            'order': len(folders) + 1,
            'createdAt': int(time.time())
        }
        
        folders.append(new_folder)
        
        # Save to DynamoDB
        table.put_item(
            Item={
                'userId': username,
                'emailId': 'settings:folders',
                'folders': folders,
                'updatedAt': int(time.time())
            }
        )
        
        return cors_response(
            201,
            json.dumps({
                'message': 'Folder created successfully',
                'folder': new_folder
            })
        )
        
    except json.JSONDecodeError:
        return cors_response(400, json.dumps({'error': 'Invalid JSON in request body'}))
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return cors_response(
            500,
            json.dumps({'error': str(e)})
        )

