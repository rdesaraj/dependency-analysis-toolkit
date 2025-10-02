# Dependency Analysis Toolkit

This project contains AWS Lambda functions and a Bedrock agent that work together to analyze ATX dependency graphs and missing components for mainframe modernization planning.

## Architecture

1. **Bedrock Agent** (`dependency-analysis-agent`): AI-powered analysis coordinator using Claude 3.7 Sonnet
2. **Dependency Analysis Lambda**: Analyzes component relationships and transitive dependencies  
3. **Minimal Dependency Finder Lambda**: Identifies optimal POC candidates with complexity scoring
4. **Missing Component Analysis Lambda**: Assesses risks and completeness

## Prerequisites

- AWS CLI configured with appropriate permissions
- Python 3.9+ (uses AWS managed pandas layer)
- An S3 bucket for storing ATX files

## Quick Deployment

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Deploy everything
./scripts/deploy.sh
```

This will deploy all Lambda functions and the Bedrock agent with AWS managed layers.

## Manual Cleanup

```bash
./scripts/cleanup.sh
```

## Configuration

The deployment creates:
- **Bedrock Agent**: Claude 3.7 Sonnet with ATX analysis capabilities
- **Lambda Functions**: Python 3.9 runtime with AWS managed pandas layer
- **S3 Buckets**: For deployment artifacts and data storage
- **IAM Roles**: With least-privilege permissions

## Usage

### 1. Upload ATX Files to S3

```bash
aws s3 cp dependencies_YYYYMMDDHHMMSS.json s3://your-data-bucket/
aws s3 cp missing_YYYYMMDDHHMMSS.csv s3://your-data-bucket/
```

### 2. Interact with Bedrock Agent

Use the Bedrock Agent ID from deployment output in the AWS Console or via API.

The agent follows a sequential workflow:
1. **Dependencies JSON** - Required ATX dependency graph
2. **Missing Components CSV** - Optional risk assessment data  
3. **CSD File** - Optional CICS system definition (if CICS detected)

### 3. Analysis Results

The system provides:
- **POC Candidates**: Ranked by complexity and business value
- **Risk Assessment**: Missing component analysis
- **Modernization Strategy**: Batch vs Online recommendations
- **CICS Detection**: Hybrid system analysis

## Generated Analysis Examples

### Batch POC Candidates
```
READACCT.jcl - Complexity: 4.8 | Data Processing Focused
Best for: Database integration and data migration demos
```

### Online POC Candidates  
```
CA00 - Account Administration - Complexity: 19.2 | UI Focused
Best for: User interface modernization and screen transformation
```

## Key Features

- **Hybrid Analysis**: Supports both batch (JCL) and online (CICS) systems
- **Risk Assessment**: Identifies missing components and completeness scores
- **Complexity Scoring**: Weighted analysis of technical dependencies
- **Business Context**: Translates technical patterns to business value
- **AWS Managed**: Uses stable AWS managed pandas layers

## Technical Details

### Lambda Configuration
- **Runtime**: Python 3.9 (stable AWS managed layer support)
- **Layer**: `arn:aws:lambda:us-east-1:336392948345:layer:AWSSDKPandas-Python39:1`
- **Memory**: 128MB (sufficient for analysis workloads)
- **Timeout**: 5 minutes

### Bedrock Agent Configuration  
- **Model**: Claude 3.7 Sonnet (`anthropic.claude-3-7-sonnet-20250219-v1:0`)
- **Action Groups**: 3 Lambda functions with defined schemas
- **Workflow**: Sequential data collection with validation

## Cost Optimization

- Uses AWS managed layers (no custom layer costs)
- Minimal memory allocation for Lambda functions
- Efficient S3 storage patterns
- Pay-per-use Bedrock agent pricing

## Security Best Practices

- Least-privilege IAM policies
- S3 bucket encryption enabled
- No hardcoded credentials
- VPC deployment ready (optional)

## Troubleshooting

### Common Issues

1. **Model Access**: Ensure Claude 3.7 Sonnet is available in your region
2. **Permissions**: Verify AWS CLI has admin permissions for deployment
3. **Layer Access**: AWS managed layer must be accessible in your region

### Logs

```bash
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/dependency-analysis
```

## Known Limitations

1. **Manual Inference Profile**: Cross-region inference profile requires manual selection
2. **Python 3.9 Dependency**: Uses Python 3.9 for AWS managed layer compatibility (monitor for newer versions)

## Support

For issues:
1. Check CloudWatch logs for detailed error information
2. Verify S3 file formats and accessibility  
3. Ensure all prerequisites are met
4. Test with sample ATX files first

## Architecture Diagram

```
ATX Files (S3) → Bedrock Agent → Lambda Functions → Analysis Results
                      ↓
              Sequential Workflow:
              1. Dependencies JSON
              2. Missing Components  
              3. CICS Detection
              4. CSD File (optional)
```
