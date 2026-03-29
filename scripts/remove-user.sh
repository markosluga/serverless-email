#!/bin/bash
# Remove a user from the serverless email system

set -e

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <username> <email> [stack-name]"
    echo "Example: $0 john john@example.com serverless-email"
    exit 1
fi

USERNAME=$1
EMAIL=$2
STACK_NAME=${3:-serverless-email}
REGION=${AWS_REGION:-us-west-2}

echo "Removing user: $USERNAME ($EMAIL)"
echo "Stack: $STACK_NAME"
echo "Region: $REGION"
echo ""
read -p "Are you sure you want to remove this user? This will delete all their emails! (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Get stack outputs
USER_POOL_ID=$(aws ssm get-parameter --name "/${STACK_NAME}/cognito-user-pool-id" --query 'Parameter.Value' --output text --region $REGION)
S3_BUCKET=$(aws ssm get-parameter --name "/${STACK_NAME}/s3-bucket" --query 'Parameter.Value' --output text --region $REGION)
METADATA_TABLE="${STACK_NAME}-email-metadata"

echo "User Pool ID: $USER_POOL_ID"
echo "S3 Bucket: $S3_BUCKET"

# 1. Delete Cognito user
echo "Deleting Cognito user..."
aws cognito-idp admin-delete-user \
    --user-pool-id $USER_POOL_ID \
    --username $EMAIL \
    --region $REGION 2>/dev/null || echo "User not found in Cognito"

echo "✓ Cognito user deleted"

# 2. Delete SES receipt rule
echo "Deleting SES receipt rule..."
RULE_SET=$(aws ses describe-active-receipt-rule-set --region $REGION --query 'Metadata.Name' --output text 2>/dev/null || echo "")

if [ -n "$RULE_SET" ]; then
    aws ses delete-receipt-rule \
        --rule-set-name $RULE_SET \
        --rule-name "${USERNAME}-receipt-rule" \
        --region $REGION 2>/dev/null || echo "Rule not found"
fi

echo "✓ SES receipt rule deleted"

# 3. Delete email metadata from DynamoDB
echo "Deleting email metadata from DynamoDB..."
# Query all emails for this user
EMAILS=$(aws dynamodb query \
    --table-name $METADATA_TABLE \
    --key-condition-expression "userId = :userId" \
    --expression-attribute-values '{":userId":{"S":"'$USERNAME'"}}' \
    --projection-expression "emailId" \
    --region $REGION \
    --query 'Items[].emailId.S' \
    --output text)

# Delete each email metadata entry
for EMAIL_ID in $EMAILS; do
    aws dynamodb delete-item \
        --table-name $METADATA_TABLE \
        --key "{\"userId\":{\"S\":\"$USERNAME\"},\"emailId\":{\"S\":\"$EMAIL_ID\"}}" \
        --region $REGION
done

echo "✓ Email metadata deleted"

# 4. Delete S3 emails (optional - commented out for safety)
echo "Deleting S3 emails..."
read -p "Do you want to delete all email files from S3? (yes/no): " DELETE_S3

if [ "$DELETE_S3" == "yes" ]; then
    aws s3 rm s3://$S3_BUCKET/users/${USERNAME}/ --recursive --region $REGION
    echo "✓ S3 emails deleted"
else
    echo "⚠ S3 emails NOT deleted (kept for backup)"
fi

echo ""
echo "========================================="
echo "User removed successfully!"
echo "========================================="
echo "Username: $USERNAME"
echo "Email: $EMAIL"
echo ""
if [ "$DELETE_S3" != "yes" ]; then
    echo "NOTE: Email files are still in S3 at: s3://$S3_BUCKET/users/${USERNAME}/"
    echo "You can delete them manually if needed."
fi
echo "========================================="
