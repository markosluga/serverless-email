# Serverless Email System

This is v 1.0.0 of a fully functional, low cost, serverless email system built on AWS with AI capabilities.

## Features

- **Email Management**: Full inbox, sent, drafts, trash, and custom folders
- **Multi-User Support**: Individual users and group email addresses
- **AI Assistant**: Powered by Amazon Bedrock (Claude Haiku in my case, but you can pick your model)
- **Push Notifications**: Real-time email alerts (subscribe to notificatins in web and PWA)
- **Modern Web UI**: React-based responsive interface
- **Subscription Management**: Automated unsubscribe detection and management of spam-like, but legit subscribed emails
- **Calendar Integration**: Handle calendar invites and responses (like, read them, accept, decline tentative, doesn't include an actual calendar)
- **Attachment Support**: Send and receive attachments
- **Search & Pagination**: Fast email search with pagination
- **Mobile PWA**: Install as native app on mobile devices via progressive web application (PWA)

## Architecture

- **Frontend**: React + Vite (S3 + CloudFront)
- **Backend**: AWS Lambda (Python 3.11/3.12, Node.js 22.x)
- **API**: API Gateway HTTP API with JWT authentication
- **Storage**: S3 (emails) + DynamoDB (metadata)
- **Email**: Amazon SES (sending/receiving)
- **Authentication**: AWS Cognito
- **AI**: Amazon Bedrock (Claude models)

## Quick Start

### Prerequisites

- AWS Account with appropriate permissions
- Request SES production (out of sandbox) account access - this will be a ticket to AWS Support 
- AWS CLI configured, preferably - but you can do it in console :S
- Node.js 18+ (for web GUI)
- Python 3.11+ (for Lambda functions)

## Cost Estimate

Typical monthly cost for, potentially, a dozzens users is **<$1**
- **Lambda**: $0.05 (100K requests)
- **DynamoDB**: $0.10 (on-demand)
- **S3**: $0.10 (storage + requests, it grows by $0.02 per gb of email stored)
- **CloudFront**: $0.05 (CDN)
- **SES**: Free tier (62,000 emails/month)
- **API Gateway**: $0.10 (100K requests)
- **Bedrock**: $0.50 - (500k tokens) here it's a question of how much interaction with the models you have and which models you pick. Haiku is more thna good enough, go for deepseek or llama and you're spending half what Haiku does...
- **Total**: <$1/month (I pay about $0.05 for my own account with AI - without it's more like $0.02...)


### Deployment

1. **Deploy Infrastructure**
   ```bash
   aws cloudformation create-stack \
     --stack-name serverless-email \
     --template-body file://cloudformation/main-stack.yaml \
     --parameters file://cloudformation/parameters.json \
     --capabilities CAPABILITY_IAM \
     --region us-west-2
   ```

2. **Configure SES**
   ```bash
   # Verify your domain
   ./scripts/setup-ses.sh your-domain.com
   ```

3. **Create Users**
   ```bash
   # Add a user
   ./scripts/add-user.sh username email@domain.com
   
   # Add a group
   ./scripts/add-group.sh groupname group@domain.com member1@domain.com member2@domain.com
   ```

4. **Deploy Web GUI**
   ```bash
   cd web-gui
   npm install
   npm run build
   ./deploy-web-gui.sh
   ```


## Components

### Lambda Functions (30 total)

**Email Operations**
- `api-email-list` - List emails with pagination
- `api-email-read` - Read single email
- `api-email-send` - Send email via SES
- `api-email-delete` - Soft delete email
- `api-email-restore` - Restore from trash
- `api-email-permanent-delete` - Permanently delete
- `api-email-mark-read` - Mark as read/unread
- `api-email-mark-not-spam` - Mark as not spam
- `api-email-move` - Move between folders

**Folder Management**
- `api-folder-list` - List custom folders
- `api-folder-create` - Create custom folder
- `api-folder-delete` - Delete custom folder

**Drafts**
- `api-draft-save` - Save draft

**Groups**
- `api-groups-list` - List email groups

**Attachments**
- `api-attachment-download` - Download attachment

**AI Features**
- `ai-inbox-summary` - Generate inbox summary
- `ai-email-summarize` - Summarize single email
- `api-ai-chat` - AI chat interface

**Calendar**
- `api-calendar-respond` - Respond to calendar invites

**Subscriptions**
- `api-subscriptions-list` - List subscriptions
- `api-subscriptions-scan` - Scan for subscriptions
- `api-subscriptions-scan-progress` - Check scan progress
- `api-subscriptions-delete` - Delete subscription
- `api-subscriptions-unsubscribe` - Unsubscribe from mailing list
- `subscriptions-scan-worker` - Background scan worker

**Push Notifications**
- `api-push-subscribe` - Subscribe to push notifications
- `push-notification-sender` - Send push notifications

**Core Processing**
- `email-metadata-extractor` - Extract metadata from incoming emails

**Utilities**
- `api-quota` - Get SES sending quota

### DynamoDB Tables

- `email-metadata` - Email metadata with indexes
- `email-groups` - Group configurations
- `email-subscriptions` - Subscription tracking
- `email-scan-history` - Subscription scan history
- `scan-sessions` - Active scan sessions
- `push-subscriptions` - Push notification subscriptions
- `rate-limits` - API rate limiting
- `ai-usage` - AI feature usage tracking

### S3 Buckets

- `emails` - Email storage (raw .eml files)
- `web-app` - Static website hosting

## Security

- **CORS Protection**: API restricted to authorized domain
- **Rate Limiting**: Token bucket algorithm (20 req/sec)
- **Authentication**: Cognito JWT tokens required
- **Encryption**: S3 server-side encryption
- **User Isolation**: Enforced at Lambda level
- **Private S3**: CloudFront OAI access only

## User Management

### Add User
```bash
./scripts/add-user.sh username email@domain.com
```

This will:
1. Create Cognito user
2. Verify email in SES
3. Create SES receipt rule
4. Set up S3 folder structure

### Add Group
```bash
./scripts/add-group.sh groupname group@domain.com member1@domain.com member2@domain.com
```

This will:
1. Create group in DynamoDB
2. Verify group email in SES
3. Create SES receipt rule
4. Set up S3 folder structure

### Remove User
```bash
./scripts/remove-user.sh username
```

### Remove Group
```bash
./scripts/remove-group.sh groupname
```

## Configuration

All configuration is managed through CloudFormation parameters and AWS Systems Manager Parameter Store.

### Required Parameters

- `DomainName` - Your email domain (e.g., example.com)
- `WebAppDomain` - Web app subdomain (e.g., mail.example.com)
- `AdminEmail` - Initial admin email address

### Optional Parameters

- `EnableAI` - Enable AI features (default: true)
- `EnablePushNotifications` - Enable push notifications (default: true)
- `RateLimitPerSecond` - API rate limit (default: 20)

## Documentation

- [Architecture Overview](docs/ARCHITECTURE.md)
- [Deployment Guide](docs/DEPLOYMENT.md)
- [User Guide](docs/USER_GUIDE.md)
- [API Reference](docs/API_REFERENCE.md)
- [Development Guide](docs/DEVELOPMENT.md)

## License

MIT License - See LICENSE file for details

## Support

For issues or questions, please open a GitHub issue.
