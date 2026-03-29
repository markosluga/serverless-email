"""
Rate Limiting Module
Implements per-user rate limiting using DynamoDB with burst allowance
Limit: 20 requests per second with burst of 3 (allows fast navigation)
"""

import boto3
import time
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
rate_limit_table = dynamodb.Table('newmail-rate-limits')

def check_rate_limit(user_id, endpoint):
    """
    Check if user has exceeded rate limit for this endpoint
    Uses token bucket algorithm: allows burst of 3 requests, then 20 req/sec
    Returns: (allowed: bool, retry_after: int)
    """
    current_time = Decimal(str(time.time()))
    rate_limit_key = f"{user_id}#{endpoint}"
    
    # Token bucket parameters
    MAX_TOKENS = 3  # Burst allowance (allows 3 rapid clicks)
    REFILL_RATE = 20  # Tokens per second (20 requests per second)
    
    try:
        # Try to get the current token state
        response = rate_limit_table.get_item(
            Key={'rateLimitKey': rate_limit_key}
        )
        
        if 'Item' in response:
            last_request = response['Item']['lastRequest']
            tokens = float(response['Item'].get('tokens', MAX_TOKENS))
            
            # Calculate time passed and refill tokens
            time_diff = float(current_time - last_request)
            tokens = min(MAX_TOKENS, tokens + (time_diff * REFILL_RATE))
            
            # Check if we have at least 1 token
            if tokens < 1.0:
                retry_after = 1
                return False, retry_after
            
            # Consume 1 token
            tokens -= 1.0
        else:
            # First request - start with full bucket minus 1
            tokens = MAX_TOKENS - 1.0
        
        # Update the token state
        rate_limit_table.put_item(
            Item={
                'rateLimitKey': rate_limit_key,
                'lastRequest': current_time,
                'tokens': Decimal(str(tokens)),
                'ttl': int(current_time) + 3600  # Expire after 1 hour
            }
        )
        
        return True, 0
        
    except Exception as e:
        # If rate limiting fails, allow the request (fail open)
        print(f"Rate limit check failed: {str(e)}")
        return True, 0

def rate_limit_response():
    """
    Returns a 429 Too Many Requests response
    """
    from cors_config import cors_response
    import json
    
    return cors_response(
        429,
        json.dumps({
            'error': 'Rate limit exceeded',
            'message': 'Too many requests. Please wait a moment and try again.'
        })
    )
