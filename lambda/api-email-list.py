"""
Lambda function to list emails via API Gateway
Uses DynamoDB for fast metadata queries
"""
import json
import boto3
import os
from boto3.dynamodb.conditions import Key
from decimal import Decimal
from cors_config import cors_response, get_cors_headers
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
    List emails for authenticated user with pagination and search
    GET /api/emails?folder=inbox&limit=50&unread_only=false&last_key=...&search=query
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        username = user_context.get('email', 'newmail')
        if '@' in username:
            username = username.split('@')[0]
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'email-list')
        if not allowed:
            return rate_limit_response()
        
        # Get query parameters
        params = event.get('queryStringParameters') or {}
        folder = params.get('folder', 'inbox')
        limit = int(params.get('limit', '50'))
        unread_only = params.get('unread_only', 'false').lower() == 'true'
        show_deleted = params.get('show_deleted', 'false').lower() == 'true'
        search_query = params.get('search', '').strip().lower()
        
        # Decode pagination token if provided
        last_evaluated_key = None
        if params.get('last_key'):
            try:
                import base64
                last_evaluated_key = json.loads(base64.b64decode(params['last_key']).decode('utf-8'))
            except:
                pass
        
        # Query DynamoDB for personal and group emails
        table = dynamodb.Table('email-metadata')
        groups_table = dynamodb.Table('email-groups')
        
        emails = []
        
        # Helper function to match search query
        def matches_search(item):
            if not search_query:
                return True
            # Search in subject, from, to, and body preview
            searchable_text = ' '.join([
                item.get('subject', ''),
                item.get('from', ''),
                item.get('to', ''),
                item.get('bodyPreview', '')
            ]).lower()
            return search_query in searchable_text
        
        # 1. Get personal emails - fetch ALL to ensure proper sorting
        query_params = {
            'IndexName': 'FolderIndex',
            'KeyConditionExpression': Key('userId').eq(username) & Key('folder').eq(folder),
            'ScanIndexForward': False  # Sort by timestamp descending
        }
        
        response = table.query(**query_params)
        all_personal_items = response.get('Items', [])
        
        # Handle pagination to get ALL personal emails
        while 'LastEvaluatedKey' in response:
            query_params['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = table.query(**query_params)
            all_personal_items.extend(response.get('Items', []))
        
        # Process personal emails
        for item in all_personal_items:
            is_deleted = item.get('deleted', False)
            
            if is_deleted and not show_deleted:
                continue
            if unread_only and item.get('read', False):
                continue
            if not matches_search(item):
                continue
            
            emails.append({
                'id': item['emailId'],
                'from': item.get('from', 'Unknown'),
                'to': item.get('to', ''),
                'subject': item.get('subject', '(no subject)'),
                'date': item.get('date', ''),
                'read': item.get('read', False),
                'deleted': is_deleted,
                'folder': item.get('folder', folder),
                'timestamp': int(item.get('timestamp', 0)),
                'isGroup': False,
                'bodyPreview': item.get('bodyPreview', '')[:200]  # Return first 200 chars for UI
            })
        
        # 2. Get user's group memberships
        user_email = f"{username}@example.com"
        groups_response = groups_table.scan(
            FilterExpression='contains(members, :email)',
            ExpressionAttributeValues={':email': user_email}
        )
        
        user_groups = [g['groupEmail'].split('@')[0] for g in groups_response.get('Items', [])]
        
        # 3. Get group emails for each group - fetch ALL to ensure proper sorting
        for group_id in user_groups:
            group_query_params = {
                'IndexName': 'FolderIndex',
                'KeyConditionExpression': Key('userId').eq(f"group:{group_id}") & Key('folder').eq(folder),
                'ScanIndexForward': False
            }
            
            group_response = table.query(**group_query_params)
            all_group_items = group_response.get('Items', [])
            
            # Handle pagination for group emails
            while 'LastEvaluatedKey' in group_response:
                group_query_params['ExclusiveStartKey'] = group_response['LastEvaluatedKey']
                group_response = table.query(**group_query_params)
                all_group_items.extend(group_response.get('Items', []))
            
            for item in all_group_items:
                is_deleted = item.get('deleted', False)
                
                if is_deleted and not show_deleted:
                    continue
                if unread_only and item.get('read', False):
                    continue
                if not matches_search(item):
                    continue
                
                emails.append({
                    'id': item['emailId'],
                    'from': item.get('from', 'Unknown'),
                    'to': item.get('to', ''),
                    'subject': item.get('subject', '(no subject)'),
                    'date': item.get('date', ''),
                    'read': item.get('read', False),
                    'deleted': is_deleted,
                    'folder': item.get('folder', folder),
                    'timestamp': int(item.get('timestamp', 0)),
                    'isGroup': True,
                    'groupId': group_id,
                    'groupEmail': item.get('groupEmail', ''),
                    'groupName': item.get('groupName', group_id),
                    'bodyPreview': item.get('bodyPreview', '')[:200]
                })
        
        # Sort by timestamp (newest first) BEFORE limiting
        emails.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Implement client-side pagination after sorting
        start_index = 0
        if last_evaluated_key:
            # last_evaluated_key is already decoded as a dict
            start_index = last_evaluated_key.get('index', 0)
        
        end_index = start_index + limit
        paginated_emails = emails[start_index:end_index]
        
        # Count unread
        unread_count = sum(1 for email in paginated_emails if not email['read'])
        
        # Encode pagination token for next page
        next_page_token = None
        if end_index < len(emails):
            import base64
            next_key = {'index': end_index}
            next_page_token = base64.b64encode(json.dumps(next_key).encode('utf-8')).decode('utf-8')
        
        return cors_response(
            200,
            json.dumps({
                'emails': paginated_emails,
                'total': len(paginated_emails),
                'unread_count': unread_count,
                'next_page_token': next_page_token,
                'has_more': next_page_token is not None
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

