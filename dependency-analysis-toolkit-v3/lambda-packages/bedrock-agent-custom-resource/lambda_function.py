import json
import boto3
import urllib3
import logging
import base64

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    """
    CloudFormation Custom Resource handler for Bedrock Agent management
    """
    try:
        # Handle both JSON and base64 input
        if isinstance(event, str):
            try:
                decoded = base64.b64decode(event).decode('utf-8')
                event = json.loads(decoded)
            except:
                event = json.loads(event)
        
        logger.info(f"Received event type: {event['RequestType']}")
        
        request_type = event['RequestType']
        resource_properties = event['ResourceProperties']
        
        if request_type == 'Create':
            response_data = handle_create(resource_properties)
        elif request_type == 'Update':
            response_data = handle_update(resource_properties, event.get('OldResourceProperties', {}))
        elif request_type == 'Delete':
            response_data = handle_delete(resource_properties)
        else:
            raise ValueError(f"Unknown request type: {request_type}")
        
        send_response(event, context, 'SUCCESS', response_data)
        
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        send_response(event, context, 'FAILED', {'Error': str(e)})

def handle_create(properties):
    """Handle CREATE operations - Create Bedrock agent with S3 prompt and action groups"""
    bedrock = boto3.client('bedrock-agent')
    s3_client = boto3.client('s3')
    
    # Get agent prompt from S3 (any length)
    bucket = properties['S3Bucket']
    key = properties['S3Key']
    
    try:
        logger.info(f"Fetching agent prompt from s3://{bucket}/{key}")
        response = s3_client.get_object(Bucket=bucket, Key=key)
        instruction = response['Body'].read().decode('utf-8')
        logger.info(f"Agent prompt loaded: {len(instruction)} characters")
    except Exception as e:
        logger.error(f"Error fetching agent prompt from S3: {str(e)}")
        raise e
    
    # Create Bedrock agent with full prompt
    agent_name = properties['AgentName']
    foundation_model = properties['FoundationModel']
    agent_role_arn = properties['AgentRoleArn']
    
    logger.info(f"Creating Bedrock agent: {agent_name}")
    
    # Bedrock agents require base model ID, not inference profile ARN
    if 'inference-profile' in foundation_model and 'claude-3-7-sonnet' in foundation_model:
        # Extract the base model ID for Claude 3.7 Sonnet
        model_id = 'anthropic.claude-3-7-sonnet-20250219-v1:0'
    else:
        model_id = foundation_model
    
    logger.info(f"Using model ID for agent: {model_id}")
    response = bedrock.create_agent(
        agentName=agent_name,
        foundationModel=model_id,
        agentResourceRoleArn=agent_role_arn,
        instruction=instruction
    )
    
    agent_id = response['agent']['agentId']
    logger.info(f"Created agent: {agent_id}")
    
    # Wait for agent to be ready before creating action groups
    import time
    max_retries = 30
    for i in range(max_retries):
        agent_status = bedrock.get_agent(agentId=agent_id)['agent']['agentStatus']
        if agent_status == 'NOT_PREPARED':
            break
        logger.info(f"Waiting for agent to be ready... Status: {agent_status} (attempt {i+1}/{max_retries})")
        time.sleep(10)
    
    # Create action groups with function schemas
    action_groups_config = [
        {
            'name': 'DependencyAnalysis',
            'lambda_arn': properties['DependencyAnalysisLambdaArn'],
            'functions': [{
                'name': 'analyzeDependencies',
                'description': 'Analyze ATX dependency relationships and transitive dependencies',
                'parameters': {
                    'dependencies_s3_uri': {'type': 'string', 'description': 'S3 URI of the ATX dependency JSON file', 'required': True},
                    'query_text': {'type': 'string', 'description': 'Natural language query about dependencies', 'required': True},
                    'include_transitive': {'type': 'boolean', 'description': 'Include transitive dependencies', 'required': False}
                }
            }]
        },
        {
            'name': 'MinimalDependencyFinder',
            'lambda_arn': properties['MinimalDependencyFinderLambdaArn'],
            'functions': [{
                'name': 'findMinimalDependencies',
                'description': 'Find entry points with least dependencies for pilot modernization (batch and online)',
                'parameters': {
                    'dependencies_s3_uri': {'type': 'string', 'description': 'S3 URI of dependencies JSON file', 'required': False},
                    'missing_components_s3_uri': {'type': 'string', 'description': 'S3 URI of missing components CSV file for risk assessment', 'required': False},
                    'target_type': {'type': 'string', 'description': 'Type of functionality (application_program, database_reference, vsam_reference)', 'required': False},
                    'max_results': {'type': 'integer', 'description': 'Maximum number of results', 'required': False},
                    'csd_s3_uri': {'type': 'string', 'description': 'S3 URI of CICS System Definition file for transaction mapping (optional)', 'required': False}
                }
            }]
        },
        {
            'name': 'MissingComponentAnalysis',
            'lambda_arn': properties['MissingComponentAnalysisLambdaArn'],
            'functions': [{
                'name': 'analyzeMissingComponents',
                'description': 'Analyze missing components and calculate risk scores',
                'parameters': {
                    'dependencies_s3_uri': {'type': 'string', 'description': 'S3 URI of dependencies JSON file for context', 'required': False},
                    'missing_components_s3_uri': {'type': 'string', 'description': 'S3 URI of missing components CSV file', 'required': False},
                    'risk_threshold': {'type': 'string', 'description': 'Risk threshold level (LOW, MEDIUM, HIGH, CRITICAL)', 'required': False}
                }
            }]
        }
    ]
    
    # Create each action group
    for ag_config in action_groups_config:
        logger.info(f"Creating action group: {ag_config['name']}")
        
        # Convert function schema to Bedrock format
        functions = []
        for func in ag_config['functions']:
            bedrock_func = {
                'name': func['name'],
                'description': func['description'],
                'parameters': {}
            }
            
            for param_name, param_config in func['parameters'].items():
                bedrock_func['parameters'][param_name] = {
                    'type': param_config['type'],
                    'description': param_config['description'],
                    'required': param_config['required']
                }
            
            functions.append(bedrock_func)
        
        bedrock.create_agent_action_group(
            agentId=agent_id,
            agentVersion='DRAFT',
            actionGroupName=ag_config['name'],
            actionGroupExecutor={'lambda': ag_config['lambda_arn']},
            functionSchema={'functions': functions}
        )
        logger.info(f"Created action group: {ag_config['name']}")
    
    # Prepare agent
    logger.info("Preparing agent...")
    bedrock.prepare_agent(agentId=agent_id)
    
    # Wait for agent to be fully prepared before creating alias
    logger.info("Waiting for agent to be prepared...")
    for i in range(60):  # Wait up to 10 minutes
        agent_status = bedrock.get_agent(agentId=agent_id)['agent']['agentStatus']
        if agent_status == 'PREPARED':
            break
        logger.info(f"Agent status: {agent_status}, waiting... (attempt {i+1}/60)")
        time.sleep(10)
    
    # Create alias
    logger.info("Creating agent alias...")
    alias_response = bedrock.create_agent_alias(
        agentId=agent_id,
        agentAliasName='TSTALIASID'
    )
    
    return {
        'AgentId': agent_id,
        'AgentArn': response['agent']['agentArn'],
        'AgentAliasId': alias_response['agentAlias']['agentAliasId']
    }

def handle_update(properties, old_properties):
    """Handle UPDATE operations"""
    # For now, return existing values
    return {
        'AgentId': old_properties.get('AgentId', ''),
        'Message': 'Update not implemented - recreate stack for changes'
    }

def handle_delete(properties):
    """Handle DELETE operations"""
    try:
        bedrock = boto3.client('bedrock-agent')
        
        # Get agent ID from physical resource ID or properties
        agent_id = properties.get('AgentId')
        if not agent_id:
            logger.warning("No AgentId found for deletion")
            return {'Message': 'No agent to delete'}
        
        logger.info(f"Deleting agent: {agent_id}")
        
        # Delete aliases first
        try:
            aliases = bedrock.list_agent_aliases(agentId=agent_id)
            for alias in aliases['agentAliasSummaries']:
                if alias['agentAliasId'] != 'TSTALIASID':  # Skip default alias
                    logger.info(f"Deleting alias: {alias['agentAliasId']}")
                    bedrock.delete_agent_alias(
                        agentId=agent_id,
                        agentAliasId=alias['agentAliasId']
                    )
        except Exception as e:
            logger.warning(f"Error deleting aliases: {str(e)}")
        
        # Delete agent
        bedrock.delete_agent(agentId=agent_id)
        logger.info(f"Deleted agent: {agent_id}")
        
    except Exception as e:
        logger.warning(f"Error deleting agent: {str(e)}")
    
    return {'Message': 'Delete completed'}

def send_response(event, context, status, response_data):
    """Send response to CloudFormation"""
    response_url = event['ResponseURL']
    
    response_body = {
        'Status': status,
        'Reason': f'See CloudWatch Log Stream: {context.log_stream_name}',
        'PhysicalResourceId': response_data.get('AgentId', context.log_stream_name),
        'StackId': event['StackId'],
        'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'],
        'Data': response_data
    }
    
    json_response_body = json.dumps(response_body)
    
    headers = {
        'content-type': '',
        'content-length': str(len(json_response_body))
    }
    
    http = urllib3.PoolManager()
    response = http.request('PUT', response_url, body=json_response_body, headers=headers)
    logger.info(f"Response status: {response.status}")
