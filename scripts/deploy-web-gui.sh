#!/bin/bash
# Deploy web GUI to S3 and CloudFront

set -e

STACK_NAME=${1:-serverless-email}
REGION=${AWS_REGION:-us-west-2}

echo "Deploying Web GUI"
echo "Stack Name: $STACK_NAME"
echo "Region: $REGION"
echo ""

# Get stack outputs
echo "Getting stack outputs..."
API_ENDPOINT=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
    --output text)

USER_POOL_ID=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
    --output text)

CLIENT_ID=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
    --output text)

WEB_BUCKET=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`WebAppBucket`].OutputValue' \
    --output text)

DISTRIBUTION_ID=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDistributionId`].OutputValue' \
    --output text)

echo "API Endpoint: $API_ENDPOINT"
echo "User Pool ID: $USER_POOL_ID"
echo "Client ID: $CLIENT_ID"
echo "Web Bucket: $WEB_BUCKET"
echo "Distribution ID: $DISTRIBUTION_ID"

# Create .env file
cd web-gui

echo ""
echo "Creating .env file..."
cat > .env <<EOF
VITE_API_URL=$API_ENDPOINT
VITE_COGNITO_USER_POOL_ID=$USER_POOL_ID
VITE_COGNITO_CLIENT_ID=$CLIENT_ID
VITE_COGNITO_REGION=$REGION
EOF

echo "✓ .env file created"

# Install dependencies if needed
if [ ! -d "node_modules" ]; then
    echo ""
    echo "Installing dependencies..."
    npm install
    echo "✓ Dependencies installed"
fi

# Build
echo ""
echo "Building web GUI..."
npm run build
echo "✓ Build complete"

# Deploy to S3
echo ""
echo "Deploying to S3..."
aws s3 sync dist/ s3://$WEB_BUCKET/ --delete --region $REGION
echo "✓ Deployed to S3"

# Invalidate CloudFront cache
echo ""
echo "Invalidating CloudFront cache..."
INVALIDATION_ID=$(aws cloudfront create-invalidation \
    --distribution-id $DISTRIBUTION_ID \
    --paths "/*" \
    --query 'Invalidation.Id' \
    --output text)

echo "Invalidation ID: $INVALIDATION_ID"
echo "Waiting for invalidation to complete..."
aws cloudfront wait invalidation-completed \
    --distribution-id $DISTRIBUTION_ID \
    --id $INVALIDATION_ID

echo "✓ CloudFront cache invalidated"

# Get web app URL
WEB_APP_URL=$(aws cloudformation describe-stacks \
    --stack-name $STACK_NAME \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`WebAppURL`].OutputValue' \
    --output text)

echo ""
echo "========================================="
echo "Web GUI deployed successfully!"
echo "========================================="
echo ""
echo "Access your email system at:"
echo "  $WEB_APP_URL"
echo ""
echo "Next step: Add users"
echo "  ./scripts/add-user.sh username email@domain.com"
echo ""
