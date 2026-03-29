#!/bin/bash
# Deploy all Lambda functions

set -e

STACK_NAME=${1:-serverless-email}
REGION=${AWS_REGION:-us-west-2}

echo "Deploying Lambda functions"
echo "Stack Name: $STACK_NAME"
echo "Region: $REGION"
echo ""

cd lambda

# Create deployment packages
echo "Creating deployment packages..."

# Core Lambda functions
LAMBDA_FUNCTIONS=(
    "lambda-email-metadata-sns"
    "api-email-list"
    "api-email-read"
    "api-email-send"
    "api-email-delete"
    "api-email-restore"
    "api-email-permanent-delete"
    "api-email-mark-read"
    "api-email-mark-not-spam"
    "api-email-move"
    "api-draft-save"
    "api-folder-list"
    "api-folder-create"
    "api-folder-delete"
    "api-groups-list"
    "api-attachment-download"
    "api-quota"
    "api-calendar-respond"
    "api-push-subscribe"
    "api-subscriptions-list"
    "api-subscriptions-scan"
    "api-subscriptions-scan-progress"
    "api-subscriptions-delete"
    "api-subscriptions-unsubscribe"
    "subscriptions-scan-worker"
    "ai-inbox-summary"
    "ai-email-summarize"
    "api-ai-chat"
)

# Package each function
for func in "${LAMBDA_FUNCTIONS[@]}"; do
    if [ -f "${func}.py" ]; then
        echo "Packaging ${func}..."
        zip -q ${func}.zip ${func}.py cors_config.py rate_limiter.py 2>/dev/null || \
        zip -q ${func}.zip ${func}.py cors_config.py 2>/dev/null || \
        zip -q ${func}.zip ${func}.py
    fi
done

echo "✓ Packages created"

# Get CloudFormation stack outputs
echo "Getting stack outputs..."
API_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
    --output text)

WEB_APP_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`WebAppURL`].OutputValue' \
    --output text)

S3_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`EmailStorageBucket`].OutputValue' \
    --output text)

SNS_TOPIC=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`SNSTopicArn`].OutputValue' \
    --output text)

echo "API Endpoint: $API_ENDPOINT"
echo "Web App URL: $WEB_APP_URL"
echo "S3 Bucket: $S3_BUCKET"
echo "SNS Topic: $SNS_TOPIC"

# Deploy each function
echo ""
echo "Deploying Lambda functions..."

for func in "${LAMBDA_FUNCTIONS[@]}"; do
    if [ -f "${func}.zip" ]; then
        # Convert function name to CloudFormation resource name
        # e.g., api-email-list -> APIEmailList
        cf_name=$(echo $func | sed 's/-/ /g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2))}1' | sed 's/ //g')
        
        # Try to find the Lambda function
        lambda_name="${STACK_NAME}-${cf_name}"
        
        # Check if function exists
        if aws lambda get-function --function-name $lambda_name --region $REGION &>/dev/null; then
            echo "Deploying ${lambda_name}..."
            
            # Update function code
            aws lambda update-function-code \
                --function-name $lambda_name \
                --zip-file fileb://${func}.zip \
                --region $REGION \
                --no-cli-pager > /dev/null
            
            # Update environment variables
            aws lambda update-function-configuration \
                --function-name $lambda_name \
                --environment "Variables={ALLOWED_ORIGIN=$WEB_APP_URL,S3_BUCKET=$S3_BUCKET,SNS_TOPIC_ARN=$SNS_TOPIC}" \
                --region $REGION \
                --no-cli-pager > /dev/null
            
            echo "✓ ${lambda_name} deployed"
        else
            echo "⚠ Function not found: ${lambda_name} (skipping)"
        fi
    fi
done

# Clean up zip files
echo ""
echo "Cleaning up..."
rm -f *.zip

echo ""
echo "========================================="
echo "Lambda functions deployed successfully!"
echo "========================================="
echo ""
echo "Next step: Deploy web GUI"
echo "  ./scripts/deploy-web-gui.sh"
echo ""
