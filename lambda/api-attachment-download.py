"""
Lambda function to generate presigned URLs for email attachments
"""
import json
import boto3
import os
from cors_config import cors_response
from rate_limiter import check_rate_limit, rate_limit_response

s3 = boto3.client('s3')

def lambda_handler(event, context):
    """
    Generate presigned URL for attachment download
    GET /api/attachments/{emailId}/{attachmentIndex}
    """
    try:
        # Get user from JWT claims
        user_context = event.get('requestContext', {}).get('authorizer', {}).get('jwt', {}).get('claims', {})
        user_email = user_context.get('email', 'user@example.com')
        username = user_email.split('@')[0] if '@' in user_email else 'user'
        
        # Rate limiting check
        allowed, retry_after = check_rate_limit(username, 'attachment-download')
        if not allowed:
            return rate_limit_response()
        
        # Get path parameters
        path_params = event.get('pathParameters', {})
        email_id = path_params.get('emailId')
        attachment_index = path_params.get('attachmentIndex')
        
        # Get query parameters
        query_params = event.get('queryStringParameters') or {}
        folder = query_params.get('folder', 'inbox')
        group_id = query_params.get('group')
        
        if not email_id or attachment_index is None:
            return cors_response(400, json.dumps({'error': 'Missing emailId or attachmentIndex'}))
        
        bucket = os.environ.get('NEWMAIL_S3_BUCKET', 'BUCKET_NAME')
        
        # Determine S3 key based on folder and group
        if group_id:
            key = f"groups/{group_id}/{folder}/{email_id}"
        else:
            key = f"users/{username}/{folder}/{email_id}"
        
        # Get email from S3 to extract attachment info
        try:
            response = s3.get_object(Bucket=bucket, Key=key)
            email_content = response['Body'].read()
            
            # Parse email to get attachment
            import email
            from email import policy
            msg = email.message_from_bytes(email_content, policy=policy.default)
            
            # Find attachments
            attachments = []
            attachment_count = 0
            for part in msg.walk():
                # Skip multipart containers
                if part.get_content_maintype() == 'multipart':
                    continue
                
                # Get content disposition
                content_disposition = part.get_content_disposition()
                filename = part.get_filename()
                content_type = part.get_content_type()
                
                print(f"Part {attachment_count}: type={content_type}, disposition={content_disposition}, filename={filename}")
                
                # Consider it an attachment if:
                # 1. Content-Disposition is 'attachment'
                # 2. It has a filename (even if disposition is 'inline')
                # 3. Skip text/plain and text/html without filenames (these are body parts)
                
                if content_disposition == 'attachment' or (filename and content_type not in ['text/plain', 'text/html', 'text/calendar']):
                    attachments.append(part)
                    print(f"  -> Added as attachment #{len(attachments)-1}")
                    attachment_count += 1
            
            print(f"Total attachments found: {len(attachments)}")
            print(f"Requested attachment index: {attachment_index}")
            
            if int(attachment_index) >= len(attachments):
                return cors_response(404, json.dumps({'error': 'Attachment not found'}))
            
            attachment = attachments[int(attachment_index)]
            filename = attachment.get_filename()
            content = attachment.get_payload(decode=True)
            content_type = attachment.get_content_type()
            
            # Store attachment temporarily in S3 for download
            temp_key = f"temp/attachments/{username}/{email_id}/{attachment_index}/{filename}"
            s3.put_object(
                Bucket=bucket,
                Key=temp_key,
                Body=content,
                ContentType=content_type,
                ContentDisposition=f'attachment; filename="{filename}"'
            )
            
            # Generate presigned URL (valid for 1 hour)
            presigned_url = s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': bucket,
                    'Key': temp_key
                },
                ExpiresIn=3600
            )
            
            return cors_response(200, json.dumps({
                'url': presigned_url,
                'filename': filename,
                'content_type': content_type,
                'size': len(content)
            }))
            
        except s3.exceptions.NoSuchKey:
            return cors_response(404, json.dumps({'error': 'Email not found'}))
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return cors_response(500, json.dumps({'error': str(e)}))

