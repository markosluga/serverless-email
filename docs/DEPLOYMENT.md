# Deployment Guide

This guide walks you through deploying the Serverless Email System to your AWS account.

## Prerequisites

1. **AWS Account** with appropriate permissions
2. **AWS CLI** installed and configured
3. **Node.js 18+** for web GUI
4. **Python 3.11+** for Lambda functions
5. **Domain name** for email and web app
6. **SES Production Access** (optional, but recommended for production use)

## Step 1: Prepare Your Domain

### 1.1 Register or Transfer Domain to Route53

If your domain is not already in Route53:

```bash
# Create hosted zone
aws route53 create-hosted-zone \
  --name example.com \
  --caller-reference $(date +%s)
```

Update your domain registrar's nameservers to point to Route53.

### 1.2 Request ACM Certificate

The CloudFormation template will create a certificate, but you need to validate it:

```bash
# The certificate will be created automatically
# Check AWS Certificate Manager console for validation instructions
```

## Step 2: Deploy CloudFormation Stack

### 2.1 Create Parameters File

Create `cloudformation/parameters.json`:

```json
[
  {
    "ParameterKey": "DomainName",
    "ParameterValue": "example.com"
  },
  {
    "ParameterKey": "WebAppDomain",
    "ParameterValue": "mail.example.com"
  },
  {
    "ParameterKey": "AdminEmail",
    "ParameterValue": "admin@example.com"
  },
  {
    "ParameterKey": "EnableAI",
    "ParameterValue": "true"
  },
  {
    "ParameterKey": "EnablePushNotifications",
    "ParameterValue": "true"
  },
  {
    "ParameterKey": "RateLimitPerSecond",
    "ParameterValue": "20"
  }
]
```

### 2.2 Deploy Stack

```bash
aws cloudformation create-stack \
  --stack-name serverless-email \
  --template-body file://cloudformation/main-stack.yaml \
  --parameters file://cloudformation/parameters.json \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-west-2
```

Wait for stack creation to complete (10-15 minutes):

```bash
aws cloudformation wait stack-create-complete \
  --stack-name serverless-email \
  --region us-west-2
```

### 2.3 Get Stack Outputs

```bash
aws cloudformation describe-stacks \
  --stack-name serverless-email \
  --region us-west-2 \
  --query 'Stacks[0].Outputs'
```

Save these outputs - you'll need them later.

## Step 3: Configure SES

### 3.1 Verify Domain

```bash
# Get domain verification token
aws ses verify-domain-identity \
  --domain example.com \
  --region us-west-2
```

Add the TXT record to your Route53 hosted zone.

### 3.2 Configure MX Records

Add MX record to Route53:

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id YOUR_ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "example.com",
        "Type": "MX",
        "TTL": 300,
        "ResourceRecords": [{"Value": "10 inbound-smtp.us-west-2.amazonaws.com"}]
      }
    }]
  }'
```

### 3.3 Configure SPF and DMARC

Add SPF record:

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id YOUR_ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "example.com",
        "Type": "TXT",
        "TTL": 300,
        "ResourceRecords": [{"Value": "\"v=spf1 include:amazonses.com ~all\""}]
      }
    }]
  }'
```

Add DMARC record:

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id YOUR_ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "CREATE",
      "ResourceRecordSet": {
        "Name": "_dmarc.example.com",
        "Type": "TXT",
        "TTL": 300,
        "ResourceRecords": [{"Value": "\"v=DMARC1; p=quarantine; rua=mailto:admin@example.com\""}]
      }
    }]
  }'
```

### 3.4 Request Production Access (Optional)

By default, SES is in sandbox mode (limited to 200 emails/day). Request production access:

```bash
# Open AWS Console > SES > Account Dashboard > Request Production Access
# Or use the CLI:
aws sesv2 put-account-details \
  --production-access-enabled \
  --mail-type TRANSACTIONAL \
  --website-url https://mail.example.com \
  --use-case-description "Serverless email system for personal/business use" \
  --region us-west-2
```

## Step 4: Deploy Lambda Functions

### 4.1 Package Lambda Functions

```bash
cd lambda

# Create deployment packages for each function
for func in api-*.py lambda-*.py; do
  func_name=$(basename $func .py)
  zip ${func_name}.zip $func cors_config.py rate_limiter.py
done
```

### 4.2 Deploy Lambda Functions

```bash
# Get Lambda function names from CloudFormation
FUNCTIONS=$(aws cloudformation describe-stack-resources \
  --stack-name serverless-email \
  --query 'StackResources[?ResourceType==`AWS::Lambda::Function`].PhysicalResourceId' \
  --output text)

# Deploy each function
for func in $FUNCTIONS; do
  # Extract base name (e.g., api-email-list from serverless-email-api-email-list)
  base_name=$(echo $func | sed 's/serverless-email-//' | sed 's/^Email/email-/' | tr '[:upper:]' '[:lower:]')
  
  if [ -f "${base_name}.zip" ]; then
    echo "Deploying $func..."
    aws lambda update-function-code \
      --function-name $func \
      --zip-file fileb://${base_name}.zip \
      --region us-west-2
  fi
done
```

### 4.3 Configure Environment Variables

```bash
# Get stack outputs
API_ENDPOINT=$(aws cloudformation describe-stacks \
  --stack-name serverless-email \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
  --output text)

WEB_APP_URL=$(aws cloudformation describe-stacks \
  --stack-name serverless-email \
  --query 'Stacks[0].Outputs[?OutputKey==`WebAppURL`].OutputValue' \
  --output text)

# Update Lambda environment variables
for func in $FUNCTIONS; do
  aws lambda update-function-configuration \
    --function-name $func \
    --environment "Variables={ALLOWED_ORIGIN=$WEB_APP_URL}" \
    --region us-west-2
done
```

## Step 5: Deploy Web GUI

### 5.1 Install Dependencies

```bash
cd web-gui
npm install
```

### 5.2 Configure Environment

Create `.env` file:

```bash
VITE_API_URL=https://YOUR_API_ID.execute-api.us-west-2.amazonaws.com
VITE_COGNITO_USER_POOL_ID=us-west-2_XXXXXXXXX
VITE_COGNITO_CLIENT_ID=XXXXXXXXXXXXXXXXXXXXXXXXXX
VITE_COGNITO_REGION=us-west-2
```

Get values from CloudFormation outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name serverless-email \
  --query 'Stacks[0].Outputs' \
  --region us-west-2
```

### 5.3 Build and Deploy

```bash
# Build
npm run build

# Deploy to S3
WEB_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name serverless-email \
  --query 'Stacks[0].Outputs[?OutputKey==`WebAppBucket`].OutputValue' \
  --output text)

aws s3 sync dist/ s3://$WEB_BUCKET/ --delete --region us-west-2

# Invalidate CloudFront cache
DISTRIBUTION_ID=$(aws cloudformation describe-stacks \
  --stack-name serverless-email \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDistributionId`].OutputValue' \
  --output text)

aws cloudfront create-invalidation \
  --distribution-id $DISTRIBUTION_ID \
  --paths "/*" \
  --region us-west-2
```

## Step 6: Create Users and Groups

### 6.1 Add First User

```bash
./scripts/add-user.sh admin admin@example.com MySecurePassword123!
```

### 6.2 Add a Group (Optional)

```bash
./scripts/add-group.sh support support@example.com admin@example.com user@example.com
```

## Step 7: Test the System

### 7.1 Access Web Interface

Open your browser and navigate to: `https://mail.example.com`

Login with the credentials you created.

### 7.2 Send Test Email

```bash
# Send test email via AWS CLI
aws ses send-email \
  --from admin@example.com \
  --destination ToAddresses=admin@example.com \
  --message Subject={Data="Test Email"},Body={Text={Data="This is a test"}} \
  --region us-west-2
```

### 7.3 Verify Email Receipt

Check the web interface - you should see the test email in your inbox.

## Step 8: Enable AI Features (Optional)

### 8.1 Request Bedrock Access

1. Go to AWS Console > Bedrock
2. Request access to Claude models
3. Wait for approval (usually instant)

### 8.2 Test AI Features

In the web interface:
1. Click "AI Assistant"
2. Ask a question about your emails
3. Verify AI responses work

## Troubleshooting

### CloudFormation Stack Failed

```bash
# Check stack events
aws cloudformation describe-stack-events \
  --stack-name serverless-email \
  --region us-west-2 \
  --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`]'
```

### Lambda Function Errors

```bash
# Check Lambda logs
aws logs tail /aws/lambda/serverless-email-EmailMetadataExtractor \
  --follow \
  --region us-west-2
```

### Email Not Receiving

1. Check SES receipt rules:
   ```bash
   aws ses describe-active-receipt-rule-set --region us-west-2
   ```

2. Check S3 bucket for emails:
   ```bash
   aws s3 ls s3://YOUR_BUCKET/users/admin/inbox/
   ```

3. Check Lambda logs for metadata extractor

### Web App Not Loading

1. Check CloudFront distribution status
2. Verify S3 bucket has files
3. Check browser console for errors
4. Verify CORS configuration

## Maintenance

### Update Lambda Functions

```bash
cd lambda
# Make changes to Lambda functions
# Repackage and deploy
./deploy-lambda.sh
```

### Update Web GUI

```bash
cd web-gui
# Make changes
npm run build
./deploy-web-gui.sh
```

### Backup Data

```bash
# Backup DynamoDB tables
aws dynamodb create-backup \
  --table-name serverless-email-email-metadata \
  --backup-name metadata-backup-$(date +%Y%m%d) \
  --region us-west-2

# Backup S3 emails
aws s3 sync s3://YOUR_BUCKET/ ./backup/ --region us-west-2
```

## Cost Optimization

1. **Enable S3 Lifecycle Policies** - Archive old emails to Glacier
2. **Use DynamoDB On-Demand** - Pay only for what you use
3. **Enable CloudFront Caching** - Reduce origin requests
4. **Monitor Lambda Execution** - Optimize memory and timeout settings
5. **Use Bedrock Caching** - Reduce AI costs by 95%

## Security Best Practices

1. **Enable MFA** for Cognito users
2. **Rotate VAPID keys** for push notifications
3. **Review IAM policies** regularly
4. **Enable CloudTrail** for audit logging
5. **Use AWS WAF** for CloudFront (optional)
6. **Enable S3 versioning** for email backup

## Next Steps

- [User Guide](docs/USER_GUIDE.md) - Learn how to use the system
- [API Reference](docs/API_REFERENCE.md) - API documentation
- [Development Guide](docs/DEVELOPMENT.md) - Contribute to the project

## Support

For issues or questions:
- Check CloudWatch logs
- Review AWS service quotas
- Open a GitHub issue
