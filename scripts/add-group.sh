#!/bin/bash
# Add a new email group to the serverless email system

set -e

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <group-name> <group-email> <member1@example.com> [member2@example.com] ... [stack-name]"
    echo "Example: $0 support support@example.com john@example.com jane@example.com serverless-email"
    exit 1
fi

GROUP_NAME=$1
GROUP_EMAIL=$2
shift 2

# Collect all members (all args except the last one if it matches stack name pattern)
MEMBERS=()
STACK_NAME="serverless-email"

for arg in "$@"; do
    if [[ $arg == *"-"* ]] && [ ${#MEMBERS[@]} -gt 0 ]; then
        # This looks like a stack name
        STACK_NAME=$arg
    else
        MEMBERS+=("$arg")
    fi
done

REGION=${AWS_REGION:-us-west-2}

echo "Adding group: $GROUP_NAME ($GROUP_EMAIL)"
echo "Members: ${MEMBERS[@]}"
echo "Stack: $STACK_NAME"
echo "Region: $REGION"

# Get stack outputs
S3_BUCKET=$(aws ssm get-parameter --name "/${STACK_NAME}/s3-bucket" --query 'Parameter.Value' --output text --region $REGION)
GROUPS_TABLE="${STACK_NAME}-email-groups"

echo "S3 Bucket: $S3_BUCKET"
echo "Groups Table: $GROUPS_TABLE"

# 1. Create group in DynamoDB
echo "Creating group in DynamoDB..."

# Build members array for DynamoDB
MEMBERS_JSON="["
for i in "${!MEMBERS[@]}"; do
    if [ $i -gt 0 ]; then
        MEMBERS_JSON+=","
    fi
    MEMBERS_JSON+="{\"S\":\"${MEMBERS[$i]}\"}"
done
MEMBERS_JSON+="]"

cat > /tmp/group-${GROUP_NAME}.json <<EOF
{
    "groupEmail": {"S": "$GROUP_EMAIL"},
    "groupName": {"S": "$GROUP_NAME"},
    "members": {"L": $MEMBERS_JSON},
    "enabled": {"BOOL": true},
    "createdAt": {"N": "$(date +%s)"}
}
EOF

aws dynamodb put-item \
    --table-name $GROUPS_TABLE \
    --item file:///tmp/group-${GROUP_NAME}.json \
    --region $REGION

rm /tmp/group-${GROUP_NAME}.json

echo "✓ Group created in DynamoDB"

# 2. Verify group email in SES
echo "Verifying group email in SES..."
aws ses verify-email-identity \
    --email-address $GROUP_EMAIL \
    --region $REGION

echo "✓ Email verification initiated (check inbox for verification email)"

# 3. Create SES receipt rule for group
echo "Creating SES receipt rule for group..."
RULE_SET=$(aws ses describe-active-receipt-rule-set --region $REGION --query 'Metadata.Name' --output text 2>/dev/null || echo "")

if [ -z "$RULE_SET" ]; then
    echo "No active rule set found. Creating one..."
    aws ses create-receipt-rule-set --rule-set-name "${STACK_NAME}-rules" --region $REGION
    aws ses set-active-receipt-rule-set --rule-set-name "${STACK_NAME}-rules" --region $REGION
    RULE_SET="${STACK_NAME}-rules"
fi

# Create receipt rule for group
cat > /tmp/receipt-rule-group-${GROUP_NAME}.json <<EOF
{
    "Name": "group-${GROUP_NAME}-receipt-rule",
    "Enabled": true,
    "Recipients": ["$GROUP_EMAIL"],
    "Actions": [
        {
            "S3Action": {
                "BucketName": "$S3_BUCKET",
                "ObjectKeyPrefix": "groups/${GROUP_NAME}/inbox/"
            }
        }
    ],
    "ScanEnabled": true
}
EOF

aws ses create-receipt-rule \
    --rule-set-name $RULE_SET \
    --rule file:///tmp/receipt-rule-group-${GROUP_NAME}.json \
    --region $REGION 2>/dev/null || echo "Rule may already exist"

rm /tmp/receipt-rule-group-${GROUP_NAME}.json

echo "✓ SES receipt rule created"

# 4. Create S3 folder structure for group
echo "Creating S3 folder structure for group..."
for folder in inbox sent drafts trash; do
    aws s3api put-object \
        --bucket $S3_BUCKET \
        --key "groups/${GROUP_NAME}/${folder}/" \
        --region $REGION
done

echo "✓ S3 folders created"

echo ""
echo "========================================="
echo "Group created successfully!"
echo "========================================="
echo "Group Name: $GROUP_NAME"
echo "Group Email: $GROUP_EMAIL"
echo "Members:"
for member in "${MEMBERS[@]}"; do
    echo "  - $member"
done
echo ""
echo "IMPORTANT: Verify the group email address by clicking the link sent to $GROUP_EMAIL"
echo "All members will receive emails sent to this group address."
echo "========================================="
