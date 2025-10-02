#!/bin/bash
set -e

# Configuration
REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
DEPLOYMENT_BUCKET="dependency-deployment-${ACCOUNT_ID}-${REGION}"

echo "🚀 ATX Dependency Analysis Toolkit Deployment"
echo "📋 Account ID: $ACCOUNT_ID"
echo "📋 Region: $REGION"

# Step 1: Create S3 bucket for deployment artifacts
echo "🪣 Creating deployment S3 bucket..."
if ! aws s3 ls "s3://$DEPLOYMENT_BUCKET" >/dev/null 2>&1; then
    aws s3 mb "s3://$DEPLOYMENT_BUCKET" --region $REGION
    echo "✅ Created S3 bucket: $DEPLOYMENT_BUCKET"
else
    echo "✅ S3 bucket already exists: $DEPLOYMENT_BUCKET"
fi

# Step 2: Package Lambda functions (no custom layer needed - using AWS managed)
echo "📦 Packaging Lambda functions..."
./scripts/package-lambda-functions.sh

# Step 3: Upload Lambda packages to S3 (no layer needed - using AWS managed)
echo "📤 Uploading Lambda packages to S3..."
aws s3 sync dist/ s3://$DEPLOYMENT_BUCKET/lambda-packages/ --exclude "*" --include "*.zip" --region $REGION

# Step 4: Upload Bedrock agent prompt
echo "📤 Uploading Bedrock agent prompt..."
aws s3 cp bedrock-agent/agent-prompt.txt s3://$DEPLOYMENT_BUCKET/bedrock-agent/agent-prompt.txt --region $REGION

# Step 5: Deploy stack using AWS-managed layers
echo "🔧 Deploying ATX stack with AWS-managed layers..."
aws cloudformation validate-template \
    --template-body file://cloudformation/main-stack.yaml \
    --region $REGION > /dev/null

# Check if stack exists
if aws cloudformation describe-stacks --stack-name dependency-analysis --region $REGION >/dev/null 2>&1; then
    echo "📝 Updating existing stack..."
    aws cloudformation update-stack \
        --stack-name dependency-analysis \
        --template-body file://cloudformation/main-stack.yaml \
        --parameters \
            ParameterKey=DeploymentBucket,ParameterValue=$DEPLOYMENT_BUCKET \
        --capabilities CAPABILITY_NAMED_IAM \
        --region $REGION
    
    aws cloudformation wait stack-update-complete \
        --stack-name dependency-analysis \
        --region $REGION
    
    echo "✅ Stack updated successfully!"
else
    echo "📝 Creating new stack..."
    aws cloudformation create-stack \
        --stack-name dependency-analysis \
        --template-body file://cloudformation/main-stack.yaml \
        --parameters \
            ParameterKey=DeploymentBucket,ParameterValue=$DEPLOYMENT_BUCKET \
        --capabilities CAPABILITY_NAMED_IAM \
        --region $REGION
    
    aws cloudformation wait stack-create-complete \
        --stack-name dependency-analysis \
        --region $REGION
    
    echo "✅ Stack created successfully!"
fi

# Step 7: Get outputs
echo "📋 Deployment Summary:"
aws cloudformation describe-stacks \
    --stack-name dependency-analysis \
    --region $REGION \
    --query 'Stacks[0].Outputs[?OutputKey==`BedrockAgentId`].OutputValue' \
    --output text | xargs -I {} echo "🤖 Bedrock Agent ID: {}"

echo ""
echo "🎉 ATX Deployment completed successfully!"
echo "💡 Using AWS managed pandas layer (AWSSDKPandas-Python39:1)"
echo "💡 Use the Bedrock Agent ID above to interact with the system"
