"""
CORS Configuration Module
Centralized CORS headers for all API Lambda functions
"""

# Production domain - only allow requests from this origin
# This should be set via environment variable in production
import os
ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', 'https://mail.example.com')

def get_cors_headers(origin=None):
    """
    Returns standardized CORS headers for API responses
    Allows localhost for development
    """
    # Allow localhost for development
    allowed_origin = ALLOWED_ORIGIN
    if origin and ('localhost' in origin or '127.0.0.1' in origin):
        allowed_origin = origin
    
    return {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': allowed_origin,
        'Access-Control-Allow-Credentials': 'true',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS'
    }

def cors_response(status_code, body):
    """
    Helper function to create a response with CORS headers
    """
    return {
        'statusCode': status_code,
        'headers': get_cors_headers(),
        'body': body
    }
