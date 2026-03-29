#!/bin/bash
# Remove an email group from the serverless email system

set -e

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 <group-name> <group-email> [stack-name]"
    echo "Example: $0 support support@example.com serverless-email"
    exit 1
fi

GROUP_NAME=$1
GROUP_EMAIL=$2
STACK_NAME=${3:-serverless-email}
REGION=${AWS_REGION:-us-west-2}

echo "Removing group: $GROUP_NAME ($GROUP_EMAIL)"
echo "Stack: $STACK_NAME"
echo "Region: $REGION"
echo ""
read -p "Are you sure you want to remove this group? This will delete all group emails! (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

# Get stack outputs
S3_BUCKET=$(aws ssm get-parameter --name "/${STACK_NAME}/s3-bucket" --query 'Parameter.Value' --output text --region $REGION)
GROUPS_TABLE="${STACK_NAME}-email-groups"
METADATA_TABLE="${STACK_NAME}-email-metadata"

echo "S3 Bucket: $S3_BUCKET"
echo "Groups Table: $GROUPS_TABLE"

# 1. Delete group from DynamoDB
echo "Deleting group from DynamoDB..."
aws dynamodb delete-item \
    --table-name $GROUPS_TABLE \
    --key "{\"groupEmail\":{\"S\":\"$GROUP_EMAIL\"}}" \
    --region $REGION 2>/dev/null || echo "Group not found in DynamoDB"

echo "✓ Group deleted from DynamoDB"

# 2. Delete SES receipt rule
echo "Deleting SES receipt rule..."
RULE_SET=$(aws ses describe-active-receipt-rule-set --region $REGION --query 'Metadata.Name' --output text 2>/dev/null || echo "")

if [ -n "$RULE_SET" ]; then
    aws ses delete-receipt-rule \
        --rule-set-name $RULE_SET \
        --rule-name "group-${GROUP_NAME}-receipt-rule" \
        --region $REGION 2>/dev/null || echo "Rule not found"
fi

echo "✓ SES receipt rule deleted"

# 3. Delete email metadata from DynamoDB
echo "Deleting email metadata from DynamoDB..."
# Query all emails for this group
EMAILS=$(aws dynamodb query \
    --table-name $METADATA_TABLE \
    --key-condition-expression "userId = :userId" \
    --expression-attribute-values '{":userId":{"S":"group:'$GROUP_NAME'"}}' \
    --projection-expression "emailId" \
    --region $REGION \
    --query 'Items[].emailId.S' \
    --output text)

# Delete each email metadata entry
for EMAIL_ID in $EMAILS; do
    aws dynamodb delete-item \
        --table-name $METADATA_TABLE \
        --key "{\"userId\":{\"S\":\"group:$GROUP_NAME\"},\"emailId\":{\"S\":\"$EMAIL_ID\"}}" \
        --region $REGION
done

echo "✓ Email metadata deleted"

# 4. Delete S3 emails (optional - commented out for safety)
echo "Deleting S3 emails..."
read -p "Do you want to delete all group email files from S3? (yes/no): " DELETE_S3

if [ "$DELETE_S3" == "yes" ]; then
    aws s3 rm s3://$S3_BUCKET/groups/${GROUP_NAME}/ --recursive --region $REGION
    echo "✓ S3 emails deleted"
else
    echo "⚠ S3 emails NOT deleted (kept for backup)"
fi

echo ""
echo "========================================="
echo "Group removed successfully!"
echo "========================================="
echo "Group Name: $GROUP_NAME"
echo "Group Email: $GROUP_EMAIL"
echo ""
if [ "$DELETE_S3" != "yes" ]; then
    echo "NOTE: Email files are still in S3 at: s3://$S3_BUCKET/groups/${GROUP_NAME}/"
    echo "You can delete them manually if needed."
fi
echo "========================================="
