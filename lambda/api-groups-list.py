"""
Lambda function to list user's email groups
GET /api/groups
"""
import json
import boto3
from decimal import Decimal
from cors_config import cors_response

dynamodb = boto3.resource('dynamodb', region_name='us-west-2')
groups_table = dynamodb.Table('email-groups')
metadata_table = dynamodb.Table('email-metadata')

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super(DecimalEncoder, self).default(obj)

def lambda_handler(event, context):
    """
    List all groups that the authenticated user is a member of
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        user_email = user_context.get('email', 'newmail@example.com')
        
        print(f"Listing groups for user: {user_email}")
        
        # Scan groups table to find groups where user is a member
        # Handle pagination to get all groups
        groups = []
        last_evaluated_key = None
        
        while True:
            scan_kwargs = {
                'FilterExpression': 'contains(members, :email) AND enabled = :enabled',
                'ExpressionAttributeValues': {
                    ':email': user_email,
                    ':enabled': True
                }
            }
            
            if last_evaluated_key:
                scan_kwargs['ExclusiveStartKey'] = last_evaluated_key
            
            response = groups_table.scan(**scan_kwargs)
            
            for item in response.get('Items', []):
                group_id = item['groupEmail'].split('@')[0]
                
                # Get unread count for this group (excluding deleted and spam emails)
                try:
                    from boto3.dynamodb.conditions import Key, Attr
                    metadata_response = metadata_table.query(
                        KeyConditionExpression=Key('userId').eq(f"group:{group_id}"),
                        FilterExpression='#read = :read_val AND (attribute_not_exists(deleted) OR deleted = :false) AND (attribute_not_exists(spam) OR spam = :false)',
                        ExpressionAttributeNames={'#read': 'read'},
                        ExpressionAttributeValues={
                            ':read_val': False,
                            ':false': False
                        }
                    )
                    unread_count = len(metadata_response.get('Items', []))
                except Exception as e:
                    print(f"Error getting unread count for {group_id}: {str(e)}")
                    unread_count = 0
                
                groups.append({
                    'groupId': group_id,
                    'groupEmail': item['groupEmail'],
                    'groupName': item.get('groupName', group_id),
                    'description': item.get('description', ''),
                    'unreadCount': unread_count,
                    'memberCount': len(item.get('members', []))
                })
            
            # Check if there are more items to scan
            last_evaluated_key = response.get('LastEvaluatedKey')
            if not last_evaluated_key:
                break
        
        # Sort by group name
        groups.sort(key=lambda x: x['groupName'].lower())
        
        print(f"Found {len(groups)} groups for user")
        
        return cors_response(
            200,
            json.dumps({
                'groups': groups,
                'total': len(groups)
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

