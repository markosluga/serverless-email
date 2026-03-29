#!/bin/bash
# Deploy the serverless email CloudFormation stack

set -e

STACK_NAME=${1:-serverless-email}
REGION=${AWS_REGION:-us-west-2}
PARAMS_FILE=${2:-cloudformation/parameters.json}

echo "Deploying Serverless Email System"
echo "Stack Name: $STACK_NAME"
echo "Region: $REGION"
echo "Parameters: $PARAMS_FILE"
echo ""

# Check if parameters file exists
if [ ! -f "$PARAMS_FILE" ]; then
    echo "Error: Parameters file not found: $PARAMS_FILE"
    echo "Please create it from the example:"
    echo "  cp cloudformation/parameters.example.json cloudformation/parameters.json"
    echo "  # Edit parameters.json with your values"
    exit 1
fi

# Check if stack exists
STACK_EXISTS=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].StackName' \
    --output text 2>/dev/null || echo "")

if [ -n "$STACK_EXISTS" ]; then
    echo "Stack exists. Updating..."
    aws cloudformation update-stack \
        --stack-name $STACK_NAME \
        --template-body file://cloudformation/main-stack.yaml \
        --parameters file://$PARAMS_FILE \
        --capabilities CAPABILITY_NAMED_IAM \
        --region $REGION
    
    echo "Waiting for stack update to complete..."
    aws cloudformation wait stack-update-complete \
        --stack-name $STACK_NAME \
        --region $REGION
    
    echo "✓ Stack updated successfully!"
else
    echo "Creating new stack..."
    aws cloudformation create-stack \
        --stack-name $STACK_NAME \
        --template-body file://cloudformation/main-stack.yaml \
        --parameters file://$PARAMS_FILE \
        --capabilities CAPABILITY_NAMED_IAM \
        --region $REGION
    
    echo "Waiting for stack creation to complete (this may take 10-15 minutes)..."
    aws cloudformation wait stack-create-complete \
        --stack-name $STACK_NAME \
        --region $REGION
    
    echo "✓ Stack created successfully!"
fi

echo ""
echo "========================================="
echo "Stack Outputs:"
echo "========================================="
aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
    --output table

echo ""
echo "Next steps:"
echo "1. Configure SES (verify domain, set up MX records)"
echo "2. Deploy Lambda functions: ./scripts/deploy-lambda.sh"
echo "3. Deploy web GUI: ./scripts/deploy-web-gui.sh"
echo "4. Add users: ./scripts/add-user.sh username email@domain.com"
echo ""
