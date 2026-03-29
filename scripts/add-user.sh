#!/bin/bash
# Add a new user to the serverless email system

set -e

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <username> <email> [password] [stack-name]"
    echo "Example: $0 john john@example.com MyPassword123! serverless-email"
    exit 1
fi

USERNAME=$1
EMAIL=$2
PASSWORD=${3:-$(openssl rand -base64 12)}
STACK_NAME=${4:-serverless-email}
REGION=${AWS_REGION:-us-west-2}

echo "Adding user: $USERNAME ($EMAIL)"
echo "Stack: $STACK_NAME"
echo "Region: $REGION"

# Get stack outputs
USER_POOL_ID=$(aws ssm get-parameter --name "/${STACK_NAME}/cognito-user-pool-id" --query 'Parameter.Value' --output text --region $REGION)
S3_BUCKET=$(aws ssm get-parameter --name "/${STACK_NAME}/s3-bucket" --query 'Parameter.Value' --output text --region $REGION)
DOMAIN=$(echo $EMAIL | cut -d'@' -f2)

echo "User Pool ID: $USER_POOL_ID"
echo "S3 Bucket: $S3_BUCKET"

# 1. Create Cognito user
echo "Creating Cognito user..."
aws cognito-idp admin-create-user \
    --user-pool-id $USER_POOL_ID \
    --username $EMAIL \
    --user-attributes Name=email,Value=$EMAIL Name=email_verified,Value=true \
    --temporary-password "$PASSWORD" \
    --message-action SUPPRESS \
    --region $REGION

# Set permanent password
aws cognito-idp admin-set-user-password \
    --user-pool-id $USER_POOL_ID \
    --username $EMAIL \
    --password "$PASSWORD" \
    --permanent \
    --region $REGION

echo "✓ Cognito user created"

# 2. Verify email in SES
echo "Verifying email in SES..."
aws ses verify-email-identity \
    --email-address $EMAIL \
    --region $REGION

echo "✓ Email verification initiated (check inbox for verification email)"

# 3. Create SES receipt rule
echo "Creating SES receipt rule..."
RULE_SET=$(aws ses describe-active-receipt-rule-set --region $REGION --query 'Metadata.Name' --output text 2>/dev/null || echo "")

if [ -z "$RULE_SET" ]; then
    echo "No active rule set found. Creating one..."
    aws ses create-receipt-rule-set --rule-set-name "${STACK_NAME}-rules" --region $REGION
    aws ses set-active-receipt-rule-set --rule-set-name "${STACK_NAME}-rules" --region $REGION
    RULE_SET="${STACK_NAME}-rules"
fi

# Create receipt rule
cat > /tmp/receipt-rule-${USERNAME}.json <<EOF
{
    "Name": "${USERNAME}-receipt-rule",
    "Enabled": true,
    "Recipients": ["$EMAIL"],
    "Actions": [
        {
            "S3Action": {
                "BucketName": "$S3_BUCKET",
                "ObjectKeyPrefix": "users/${USERNAME}/inbox/"
            }
        }
    ],
    "ScanEnabled": true
}
EOF

aws ses create-receipt-rule \
    --rule-set-name $RULE_SET \
    --rule file:///tmp/receipt-rule-${USERNAME}.json \
    --region $REGION 2>/dev/null || echo "Rule may already exist"

rm /tmp/receipt-rule-${USERNAME}.json

echo "✓ SES receipt rule created"

# 4. Create S3 folder structure
echo "Creating S3 folder structure..."
for folder in inbox sent drafts trash; do
    aws s3api put-object \
        --bucket $S3_BUCKET \
        --key "users/${USERNAME}/${folder}/" \
        --region $REGION
done

echo "✓ S3 folders created"

echo ""
echo "========================================="
echo "User created successfully!"
echo "========================================="
echo "Username: $EMAIL"
echo "Password: $PASSWORD"
echo "Login URL: https://$(aws ssm get-parameter --name "/${STACK_NAME}/web-app-domain" --query 'Parameter.Value' --output text --region $REGION 2>/dev/null || echo 'mail.example.com')"
echo ""
echo "IMPORTANT: Save the password securely!"
echo "The user must verify their email address by clicking the link sent to $EMAIL"
echo "========================================="
