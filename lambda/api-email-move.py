"""
Lambda function to move email to a different folder via API Gateway
Updates folder attribute in DynamoDB
"""
import json
import boto3
import time
from cors_config import cors_response
from rate_limiter import check_rate_limit, rate_limit_response

dynamodb = boto3.resource('dynamodb', region_name='us-west-2')

# Valid system folders
SYSTEM_FOLDERS = ['inbox', 'sent', 'drafts', 'trash', 'quarantine']

def lambda_handler(event, context):
    """
    Move email to a different folder
    PUT /api/emails/{id}/move
    Body: {"folder": "work"}
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        username = user_context.get('email', 'newmail')
        if '@' in username:
            username = username.split('@')[0]
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'email-move')
        if not allowed:
            return rate_limit_response()
        
        # Get email ID from path
        email_id = event.get('pathParameters', {}).get('id')
        if not email_id:
            return cors_response(400, json.dumps({'error': 'Email ID is required'}))
        
        # Parse request body
        body = json.loads(event.get('body', '{}'))
        target_folder = body.get('folder', '').lower().strip()
        
        if not target_folder:
            return cors_response(400, json.dumps({'error': 'Target folder is required'}))
        
        table = dynamodb.Table('email-metadata')
        
        # If not a system folder, verify custom folder exists
        if target_folder not in SYSTEM_FOLDERS:
            try:
                response = table.get_item(
                    Key={
                        'userId': username,
                        'emailId': 'settings:folders'
                    }
                )
                
                if 'Item' in response:
                    folders = response['Item'].get('folders', [])
                    folder_ids = [f['id'] for f in folders]
                    
                    if target_folder not in folder_ids:
                        return cors_response(404, json.dumps({'error': f"Folder '{target_folder}' not found"}))
                else:
                    return cors_response(404, json.dumps({'error': f"Folder '{target_folder}' not found"}))
            except Exception as e:
                print(f"Error checking folder: {e}")
                return cors_response(500, json.dumps({'error': 'Failed to verify folder'}))
        
        # Check if email exists and get current folder
        try:
            email_response = table.get_item(
                Key={
                    'userId': username,
                    'emailId': email_id
                }
            )
            
            if 'Item' not in email_response:
                # Try group emails
                groups_table = dynamodb.Table('email-groups')
                user_email = f"{username}@example.com"
                groups_response = groups_table.scan(
                    FilterExpression='contains(members, :email)',
                    ExpressionAttributeValues={':email': user_email}
                )
                
                # Check each group
                found = False
                for group in groups_response.get('Items', []):
                    group_id = group['groupEmail'].split('@')[0]
                    group_email_response = table.get_item(
                        Key={
                            'userId': f"group:{group_id}",
                            'emailId': email_id
                        }
                    )
                    
                    if 'Item' in group_email_response:
                        # Move group email
                        table.update_item(
                            Key={
                                'userId': f"group:{group_id}",
                                'emailId': email_id
                            },
                            UpdateExpression='SET folder = :folder, movedAt = :movedAt',
                            ExpressionAttributeValues={
                                ':folder': target_folder,
                                ':movedAt': int(time.time())
                            }
                        )
                        found = True
                        break
                
                if not found:
                    return cors_response(404, json.dumps({'error': 'Email not found'}))
            else:
                # Move personal email
                table.update_item(
                    Key={
                        'userId': username,
                        'emailId': email_id
                    },
                    UpdateExpression='SET folder = :folder, movedAt = :movedAt',
                    ExpressionAttributeValues={
                        ':folder': target_folder,
                        ':movedAt': int(time.time())
                    }
                )
        except Exception as e:
            print(f"Error moving email: {e}")
            import traceback
            traceback.print_exc()
            return cors_response(500, json.dumps({'error': f'Failed to move email: {str(e)}'}))
        
        return cors_response(
            200,
            json.dumps({
                'message': f"Email moved to '{target_folder}' successfully",
                'folder': target_folder
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

