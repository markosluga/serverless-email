"""
Lambda function to get SES quota via API Gateway
"""
import json
import boto3
from cors_config import cors_response, get_cors_headers

ses = boto3.client('ses', region_name='us-west-2')

def lambda_handler(event, context):
    """
    Get SES sending quota
    GET /api/quota
    """
    try:
        # Get quota from SES
        response = ses.get_send_quota()
        
        quota_data = {
            'max_24h': response['Max24HourSend'],
            'sent_24h': response['SentLast24Hours'],
            'remaining': response['Max24HourSend'] - response['SentLast24Hours'],
            'max_per_second': response['MaxSendRate']
        }
        
        return cors_response(200, json.dumps(quota_data))
        
    except Exception as e:
        print(f"Error: {str(e)}")
        return cors_response(500, json.dumps({'error': str(e)}))

