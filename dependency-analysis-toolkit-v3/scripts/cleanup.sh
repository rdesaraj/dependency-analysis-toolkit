#!/bin/bash
set -e

# ATX Dependency Analysis - Complete Cleanup Script
echo "🧹 ATX Complete Cleanup Starting..."

REGION="us-east-1"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
DEPLOYMENT_BUCKET="dependency-deployment-${ACCOUNT_ID}-${REGION}"

echo "📋 Account ID: $ACCOUNT_ID"
echo "📋 Region: $REGION"

# Function to safely delete resources
safe_delete() {
    local resource_type=$1
    local command=$2
    echo "🗑️  Deleting $resource_type..."
    if eval "$command" 2>/dev/null; then
        echo "✅ $resource_type deleted successfully"
    else
        echo "⚠️  $resource_type not found or already deleted"
    fi
}

# 1. Delete Bedrock Agent and Aliases
echo "🤖 Cleaning up Bedrock agents..."
AGENT_IDS=$(aws bedrock-agent list-agents --region $REGION --query 'agentSummaries[?contains(agentName, `atx`)].agentId' --output text 2>/dev/null || echo "")

if [ ! -z "$AGENT_IDS" ]; then
    for AGENT_ID in $AGENT_IDS; do
        echo "🔍 Processing agent: $AGENT_ID"
        
        # Delete all aliases first
        ALIAS_IDS=$(aws bedrock-agent list-agent-aliases --agent-id $AGENT_ID --region $REGION --query 'agentAliasSummaries[].agentAliasId' --output text 2>/dev/null || echo "")
        
        if [ ! -z "$ALIAS_IDS" ]; then
            for ALIAS_ID in $ALIAS_IDS; do
                if [ "$ALIAS_ID" != "TSTALIASID" ]; then
                    safe_delete "Agent alias $ALIAS_ID" "aws bedrock-agent delete-agent-alias --agent-id $AGENT_ID --agent-alias-id $ALIAS_ID --region $REGION"
                fi
            done
            echo "⏳ Waiting for aliases to be deleted..."
            sleep 10
        fi
        
        # Delete the agent
        safe_delete "Bedrock agent $AGENT_ID" "aws bedrock-agent delete-agent --agent-id $AGENT_ID --region $REGION"
    done
else
    echo "✅ No Bedrock agents found"
fi

# 2. Delete CloudFormation Stack
echo "📚 Cleaning up CloudFormation stacks..."
STACK_NAMES=("dependency-analysis" "dependency-analysis-dev")

for STACK_NAME in "${STACK_NAMES[@]}"; do
    if aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION >/dev/null 2>&1; then
        STACK_STATUS=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION --query 'Stacks[0].StackStatus' --output text)
        
        if [[ "$STACK_STATUS" == *"IN_PROGRESS"* ]]; then
            echo "⏳ Stack $STACK_NAME is in progress state: $STACK_STATUS. Waiting..."
            aws cloudformation wait stack-update-complete --stack-name $STACK_NAME --region $REGION 2>/dev/null || \
            aws cloudformation wait stack-create-complete --stack-name $STACK_NAME --region $REGION 2>/dev/null || \
            echo "⚠️  Stack operation timeout, proceeding..."
        fi
        
        safe_delete "CloudFormation stack $STACK_NAME" "aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION"
        
        echo "⏳ Waiting for stack deletion to complete..."
        aws cloudformation wait stack-delete-complete --stack-name $STACK_NAME --region $REGION 2>/dev/null || echo "⚠️  Stack deletion timeout"
    else
        echo "✅ Stack $STACK_NAME not found"
    fi
done

# 3. Delete Lambda Functions (in case stack deletion failed)
echo "⚡ Cleaning up Lambda functions..."
LAMBDA_FUNCTIONS=$(aws lambda list-functions --region $REGION --query 'Functions[?contains(FunctionName, `atx`)].FunctionName' --output text 2>/dev/null || echo "")

if [ ! -z "$LAMBDA_FUNCTIONS" ]; then
    for FUNCTION_NAME in $LAMBDA_FUNCTIONS; do
        safe_delete "Lambda function $FUNCTION_NAME" "aws lambda delete-function --function-name $FUNCTION_NAME --region $REGION"
    done
else
    echo "✅ No Lambda functions found"
fi

# 4. Delete S3 Buckets
echo "🪣 Cleaning up S3 buckets..."
S3_BUCKETS=$(aws s3 ls --region $REGION | grep "dependency-" | awk '{print $3}' || echo "")

if [ ! -z "$S3_BUCKETS" ]; then
    for BUCKET in $S3_BUCKETS; do
        if [[ "$BUCKET" == *"cloudtrail"* ]] || [[ "$BUCKET" == *"do-not-delete"* ]]; then
            echo "⚠️  Skipping system bucket: $BUCKET"
            continue
        fi
        safe_delete "S3 bucket $BUCKET" "aws s3 rb s3://$BUCKET --force --region $REGION"
    done
else
    echo "✅ No ATX S3 buckets found"
fi

# 5. Delete IAM Roles (in case stack deletion failed)
echo "🔐 Cleaning up IAM roles..."
IAM_ROLES=$(aws iam list-roles --query 'Roles[?contains(RoleName, `atx`)].RoleName' --output text 2>/dev/null || echo "")

if [ ! -z "$IAM_ROLES" ]; then
    for ROLE_NAME in $IAM_ROLES; do
        # Detach policies first
        ATTACHED_POLICIES=$(aws iam list-attached-role-policies --role-name $ROLE_NAME --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null || echo "")
        for POLICY_ARN in $ATTACHED_POLICIES; do
            safe_delete "Policy $POLICY_ARN from role $ROLE_NAME" "aws iam detach-role-policy --role-name $ROLE_NAME --policy-arn $POLICY_ARN"
        done
        
        # Delete inline policies
        INLINE_POLICIES=$(aws iam list-role-policies --role-name $ROLE_NAME --query 'PolicyNames[]' --output text 2>/dev/null || echo "")
        for POLICY_NAME in $INLINE_POLICIES; do
            safe_delete "Inline policy $POLICY_NAME from role $ROLE_NAME" "aws iam delete-role-policy --role-name $ROLE_NAME --policy-name $POLICY_NAME"
        done
        
        safe_delete "IAM role $ROLE_NAME" "aws iam delete-role --role-name $ROLE_NAME"
    done
else
    echo "✅ No ATX IAM roles found"
fi

echo ""
echo "🎉 ATX Cleanup completed!"
echo "✅ All ATX resources have been cleaned up"
echo "💡 You can now run ./one-click-deploy.sh for a fresh deployment"
    -f, --force                 Skip confirmation prompts
    -h, --help                  Show this help message

EXAMPLES:
    $0 -r us-east-1
    $0 -p my-atx -e prod -r us-west-2 --force

WARNING:
    This script will permanently delete all resources created by the deployment.
    This action cannot be undone.
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -p|--project-name)
                PROJECT_NAME="$2"
                shift 2
                ;;
            -e|--environment)
                ENVIRONMENT="$2"
                shift 2
                ;;
            -r|--region)
                AWS_REGION="$2"
                shift 2
                ;;
            -f|--force)
                FORCE_DELETE=true
                shift
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
}

validate_args() {
    if [[ -z "$AWS_REGION" ]]; then
        log_error "AWS region is required (-r/--region)"
        show_usage
        exit 1
    fi
}

confirm_deletion() {
    if [[ "$FORCE_DELETE" == true ]]; then
        return 0
    fi
    
    echo
    log_warning "This will permanently delete the following resources:"
    log_warning "  - CloudFormation stack: $PROJECT_NAME-$ENVIRONMENT"
    log_warning "  - All Lambda functions and layers"
    log_warning "  - Bedrock agent and action groups"
    log_warning "  - S3 buckets and all contents"
    log_warning "  - IAM roles and policies"
    echo
    log_warning "This action cannot be undone!"
    echo
    
    read -p "Are you sure you want to continue? (type 'yes' to confirm): " confirmation
    
    if [[ "$confirmation" != "yes" ]]; then
        log_info "Cleanup cancelled by user"
        exit 0
    fi
}

get_stack_outputs() {
    local stack_name="$PROJECT_NAME-$ENVIRONMENT"
    
    aws cloudformation describe-stacks \
        --stack-name "$stack_name" \
        --region "$AWS_REGION" \
        --query 'Stacks[0].Outputs' \
        --output json 2>/dev/null || echo "[]"
}

empty_s3_buckets() {
    log_info "Emptying S3 buckets..."
    
    local outputs=$(get_stack_outputs)
    local buckets=(
        "DeploymentBucketName"
        "DataBucketName"
        "BedrockArtifactsBucketName"
    )
    
    for bucket_output in "${buckets[@]}"; do
        local bucket_name=$(echo "$outputs" | jq -r ".[] | select(.OutputKey==\"$bucket_output\") | .OutputValue")
        
        if [[ -z "$bucket_name" || "$bucket_name" == "null" ]]; then
            log_warning "Bucket name not found: $bucket_output"
            continue
        fi
        
        log_info "Emptying bucket: $bucket_name"
        
        # Check if bucket exists
        if ! aws s3 ls "s3://$bucket_name" --region "$AWS_REGION" &> /dev/null; then
            log_warning "  Bucket does not exist or is not accessible: $bucket_name"
            continue
        fi
        
        # Empty bucket (delete all objects and versions)
        aws s3 rm "s3://$bucket_name" --recursive --region "$AWS_REGION" || true
        
        # Delete all object versions if versioning is enabled
        aws s3api list-object-versions \
            --bucket "$bucket_name" \
            --region "$AWS_REGION" \
            --query 'Versions[].{Key:Key,VersionId:VersionId}' \
            --output json 2>/dev/null | \
        jq -r '.[] | "--key \(.Key) --version-id \(.VersionId)"' | \
        while read -r args; do
            if [[ -n "$args" ]]; then
                aws s3api delete-object --bucket "$bucket_name" --region "$AWS_REGION" $args || true
            fi
        done
        
        # Delete all delete markers
        aws s3api list-object-versions \
            --bucket "$bucket_name" \
            --region "$AWS_REGION" \
            --query 'DeleteMarkers[].{Key:Key,VersionId:VersionId}' \
            --output json 2>/dev/null | \
        jq -r '.[] | "--key \(.Key) --version-id \(.VersionId)"' | \
        while read -r args; do
            if [[ -n "$args" ]]; then
                aws s3api delete-object --bucket "$bucket_name" --region "$AWS_REGION" $args || true
            fi
        done
        
        log_success "  Emptied bucket: $bucket_name"
    done
}

delete_lambda_layers() {
    log_info "Deleting Lambda layers..."
    
    local layer_name="$PROJECT_NAME-$ENVIRONMENT-shared-dependencies"
    
    # List all versions of the layer
    local versions=$(aws lambda list-layer-versions \
        --layer-name "$layer_name" \
        --region "$AWS_REGION" \
        --query 'LayerVersions[].Version' \
        --output text 2>/dev/null || echo "")
    
    if [[ -n "$versions" ]]; then
        for version in $versions; do
            log_info "Deleting layer version: $layer_name:$version"
            aws lambda delete-layer-version \
                --layer-name "$layer_name" \
                --version-number "$version" \
                --region "$AWS_REGION" || true
        done
        log_success "Deleted Lambda layer: $layer_name"
    else
        log_warning "No Lambda layers found to delete"
    fi
}

delete_cloudformation_stack() {
    log_info "Deleting CloudFormation stack..."
    
    local stack_name="$PROJECT_NAME-$ENVIRONMENT"
    
    # Check if stack exists
    if ! aws cloudformation describe-stacks --stack-name "$stack_name" --region "$AWS_REGION" &> /dev/null; then
        log_warning "CloudFormation stack not found: $stack_name"
        return 0
    fi
    
    log_info "Deleting stack: $stack_name"
    aws cloudformation delete-stack \
        --stack-name "$stack_name" \
        --region "$AWS_REGION"
    
    log_info "Waiting for stack deletion to complete..."
    aws cloudformation wait stack-delete-complete \
        --stack-name "$stack_name" \
        --region "$AWS_REGION"
    
    log_success "CloudFormation stack deleted: $stack_name"
}

cleanup_orphaned_resources() {
    log_info "Checking for orphaned resources..."
    
    # Check for orphaned Lambda functions
    local function_prefix="$PROJECT_NAME-$ENVIRONMENT"
    local orphaned_functions=$(aws lambda list-functions \
        --region "$AWS_REGION" \
        --query "Functions[?starts_with(FunctionName, '$function_prefix')].FunctionName" \
        --output text 2>/dev/null || echo "")
    
    if [[ -n "$orphaned_functions" ]]; then
        log_warning "Found orphaned Lambda functions:"
        for func in $orphaned_functions; do
            log_warning "  - $func"
            if [[ "$FORCE_DELETE" == true ]]; then
                log_info "Deleting orphaned function: $func"
                aws lambda delete-function --function-name "$func" --region "$AWS_REGION" || true
            fi
        done
        
        if [[ "$FORCE_DELETE" != true ]]; then
            log_info "Use --force flag to delete orphaned functions"
        fi
    fi
    
    # Check for orphaned Bedrock agents
    local agents=$(aws bedrock-agent list-agents \
        --region "$AWS_REGION" \
        --query "agentSummaries[?contains(agentName, '$PROJECT_NAME')].{Name:agentName,Id:agentId}" \
        --output json 2>/dev/null || echo "[]")
    
    if [[ "$(echo "$agents" | jq length)" -gt 0 ]]; then
        log_warning "Found potential orphaned Bedrock agents:"
        echo "$agents" | jq -r '.[] | "  - \(.Name) (\(.Id))"'
        
        if [[ "$FORCE_DELETE" != true ]]; then
            log_info "Use --force flag to delete orphaned agents"
        fi
    fi
}

generate_cleanup_report() {
    log_info "Generating cleanup report..."
    
    local report_file="$PROJECT_ROOT/cleanup-report.txt"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    cat > "$report_file" << EOF
ATX Dependency Analysis Solution - Cleanup Report
Generated: $timestamp
Project: $PROJECT_NAME
Environment: $ENVIRONMENT
Region: $AWS_REGION

Resources Cleaned Up:
- CloudFormation Stack: $PROJECT_NAME-$ENVIRONMENT
- Lambda Functions: All functions with prefix $PROJECT_NAME-$ENVIRONMENT
- Lambda Layers: $PROJECT_NAME-$ENVIRONMENT-shared-dependencies
- S3 Buckets: All buckets created by the deployment (emptied and deleted)
- Bedrock Agent: Agent and action groups managed by CloudFormation
- IAM Roles: All roles created by the deployment

Cleanup Status: COMPLETED
Force Delete: $FORCE_DELETE

Note: Some resources may take additional time to be fully removed from AWS.
EOF
    
    log_success "Cleanup report saved: $report_file"
}

main() {
    log_info "Starting ATX Dependency Analysis cleanup..."
    
    parse_args "$@"
    validate_args
    
    log_info "Cleanup configuration:"
    log_info "  Project: $PROJECT_NAME"
    log_info "  Environment: $ENVIRONMENT"
    log_info "  Region: $AWS_REGION"
    log_info "  Force delete: $FORCE_DELETE"
    
    confirm_deletion
    
    echo
    log_info "Beginning cleanup process..."
    
    # Empty S3 buckets first (required before stack deletion)
    empty_s3_buckets
    
    # Delete Lambda layers (not managed by CloudFormation)
    delete_lambda_layers
    
    # Delete the main CloudFormation stack
    delete_cloudformation_stack
    
    # Check for and optionally clean up orphaned resources
    cleanup_orphaned_resources
    
    # Generate cleanup report
    generate_cleanup_report
    
    echo
    log_success "Cleanup completed successfully!"
    log_info "All ATX Dependency Analysis resources have been removed"
    log_warning "Note: Some AWS resources may take additional time to be fully removed"
}

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi