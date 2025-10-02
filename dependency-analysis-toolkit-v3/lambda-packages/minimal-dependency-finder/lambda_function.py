import json
import boto3
import pandas as pd
import os
import base64
from typing import Dict, List, Any, Set
from urllib.parse import urlparse
from io import StringIO

# Import weight configuration helper
try:
    from weight_config_helper import get_component_weights, get_component_priority_weight
except ImportError:
    # Fallback if helper is not available (for backward compatibility)
    print("Warning: weight_config_helper not available, using inline functions")
    get_component_weights = None
    get_component_priority_weight = None

def parse_component_weights() -> Dict[str, Any]:
    """Parse component weights from environment variables with fallback to defaults"""
    
    # Use helper utility if available
    if get_component_weights is not None:
        return get_component_weights()
    
    # Fallback inline implementation (for backward compatibility)
    default_config = {
        'priority_types': {
            'JCL': 1.0,
            'COB': 1.0, 
            'COBOL': 1.0,
            'CPY': 1.0,
            'BMS': 1.0,
            'TRANSACTION': 1.0,
            'CICS_FILE': 1.0,
            'CSDCOMMAND': 1.0,
            'COMMAREA': 1.0,
            'MAPSET': 1.0
        },
        'medium_types': {
            'Missing Database Object': 0.7,
            'Missing Dataset': 0.7,
            'DATASET': 0.7,
            'VSAM KSDS DATASET': 0.7,
            'PS': 0.7,
            'txt': 0.7,
            'CTL': 0.7,
            'PROC': 0.7
        },
        'scoring_multipliers': {
            'priority_weight': 1.0,
            'medium_weight': 0.7,
            'missing_priority_penalty': 2.0,
            'missing_medium_penalty': 1.4,
            'cics_complexity_factor': 0.5
        }
    }
    
    # Try to parse from environment variable
    component_weights_env = os.environ.get('COMPONENT_WEIGHTS')
    if component_weights_env:
        try:
            env_config = json.loads(component_weights_env)
            
            # Use environment config directly, falling back to defaults for missing sections
            config = default_config.copy()
            
            if 'priority_types' in env_config:
                config['priority_types'] = env_config['priority_types']
            
            if 'medium_types' in env_config:
                config['medium_types'] = env_config['medium_types']
                
            if 'scoring_multipliers' in env_config:
                config['scoring_multipliers'].update(env_config['scoring_multipliers'])
            
            return config
            
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            # Log warning but continue with defaults
            print(f"Warning: Failed to parse COMPONENT_WEIGHTS environment variable: {e}")
            print("Falling back to default component weights")
    
    return default_config

def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    try:
        # Handle both JSON and base64 input
        if isinstance(event, str):
            try:
                decoded = base64.b64decode(event).decode('utf-8')
                event = json.loads(decoded)
            except:
                event = json.loads(event)
        
        # Handle Bedrock agent parameter format
        if 'parameters' in event:
            params = {}
            for param in event['parameters']:
                params[param['name']] = param['value']
        else:
            params = event
        
        # Extract parameters - NO DEFAULTS to force user input
        dependencies_s3_uri = params.get('dependencies_s3_uri')
        target_type = params.get('target_type', 'application_program')
        entry_point_types = params.get('entry_point_types', ['JCL', 'TRANSACTION', 'BMS'])  # Updated for actual CICS types
        missing_components_s3_uri = params.get('missing_components_s3_uri')
        csd_s3_uri = params.get('csd_s3_uri')
        max_results = int(params.get('max_results', 10))
        
        # Validate required S3 URIs
        if not dependencies_s3_uri:
            return create_bedrock_response(event, {
                "error": "Missing required parameter: dependencies_s3_uri",
                "message": "Please provide the S3 URI for your ATX dependency graph JSON file",
                "required_format": "s3://bucket-name/path/dependencies_YYYYMMDDHHMMSS.json"
            })
        
        if not missing_components_s3_uri:
            return create_bedrock_response(event, {
                "error": "Missing required parameter: missing_components_s3_uri", 
                "message": "Please provide the S3 URI for your missing components CSV file",
                "required_format": "s3://bucket-name/path/missing_YYYYMMDDHHMMSS.csv"
            })
        
        # Download and parse dependencies
        dependencies_data = download_json_from_s3(dependencies_s3_uri)
        
        # Download missing components
        missing_data = None
        try:
            missing_data = download_csv_from_s3(missing_components_s3_uri)
        except Exception as e:
            return create_bedrock_response(event, {
                "error": f"Failed to download missing components: {str(e)}",
                "message": "Please verify the missing components S3 URI is correct and accessible"
            })
        
        # Download CSD data if provided
        csd_data = None
        if csd_s3_uri:
            try:
                csd_data = download_csv_from_s3(csd_s3_uri)
            except Exception as e:
                return create_bedrock_response(event, {
                    "warning": f"CSD file could not be loaded: {str(e)}",
                    "message": "Proceeding with analysis without CSD data"
                })
        
        # Detect CICS components with accurate detection logic
        cics_detection = detect_cics_components_accurate(dependencies_data)
        
        # Parse component weights configuration
        weights_config = parse_component_weights()
        
        # Find minimal dependency entry points with CICS support
        results = find_minimal_dependency_entry_points_cics_enhanced(
            dependencies_data, target_type, entry_point_types, missing_data, csd_data, max_results, cics_detection, weights_config
        )
        
        return create_bedrock_response(event, results)
        
    except Exception as e:
        return create_bedrock_response(event, {"error": str(e)})

def create_bedrock_response(event: Dict, data: Dict) -> Dict:
    """Create standardized Bedrock response format"""
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get('actionGroup', 'MinimalDependencyFinder'),
            "function": event.get('function', 'findMinimalDependencies'),
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": json.dumps(data)
                    }
                }
            }
        }
    }

def detect_cics_components_accurate(dependencies_data: List[Dict]) -> Dict:
    """Detect CICS-related components based on actual ATX data patterns"""
    
    # CICS component types found in actual ATX data
    cics_component_types = [
        'TRANSACTION',      # CICS transactions
        'BMS',             # Basic Mapping Support (screens)
        'CICS_FILE',       # CICS file definitions
        'CSDCOMMAND'       # CICS system definition commands
    ]
    
    # Additional CICS indicators in component names or types
    cics_name_indicators = ['CICS', 'DFHCOMMAREA', 'COMMAREA', 'MAPSET']
    
    cics_components = []
    cics_by_type = {}
    
    for item in dependencies_data:
        component_type = item.get('type', '')
        component_name = item.get('name', '')
        
        is_cics_component = False
        
        # Check for direct CICS component types
        if component_type in cics_component_types:
            is_cics_component = True
        
        # Check for CICS indicators in component names
        elif any(indicator.upper() in component_name.upper() or indicator.upper() in component_type.upper() 
                for indicator in cics_name_indicators):
            is_cics_component = True
        
        if is_cics_component:
            cics_components.append({
                'name': component_name,
                'type': component_type,
                'path': item.get('path', ''),
                'dependencies_count': len(item.get('dependencies', []))
            })
            
            # Group by type for summary
            if component_type not in cics_by_type:
                cics_by_type[component_type] = 0
            cics_by_type[component_type] += 1
    
    return {
        'has_cics_components': len(cics_components) > 0,
        'cics_component_count': len(cics_components),
        'cics_components': cics_components[:15],  # Show more examples
        'cics_by_type': cics_by_type,
        'cics_types_detected': list(cics_by_type.keys()),
        'recommendation': f'Found {len(cics_components)} CICS components. Consider providing CSD file (.csd extension) for complete transaction-to-program mapping analysis.' if len(cics_components) > 0 else None,
        'analysis_scope': 'Hybrid batch/online environment detected' if len(cics_components) > 0 else 'Batch-only environment'
    }

def analyze_functionality_pattern(component_name: str, all_deps: Set[str], components: Dict) -> Dict:
    """NEW FUNCTION - Analyze functionality patterns based on dependencies"""
    patterns = {
        'data_heavy': 0,
        'screen_heavy': 0,
        'program_heavy': 0,
        'navigation': 0
    }
    
    for dep_name in all_deps:
        if dep_name in components:
            dep_type = components[dep_name]['type']
            dep_name_upper = dep_name.upper()
            
            # Generic pattern detection
            if dep_type in ['CICS_FILE', 'DATASET', 'VSAM KSDS DATASET', 'PS']:
                patterns['data_heavy'] += 1
            elif dep_type in ['BMS', 'MAPSET']:
                patterns['screen_heavy'] += 1
            elif dep_type in ['COB', 'COBOL']:
                patterns['program_heavy'] += 1
            elif 'MENU' in dep_name_upper or 'NAV' in dep_name_upper:
                patterns['navigation'] += 1
    
    return patterns

def classify_functionality(patterns: Dict) -> tuple:
    """NEW FUNCTION - Classify functionality based on patterns"""
    total_deps = sum(patterns.values())
    if total_deps == 0:
        return "Simple", "simple"
    
    # Find dominant pattern
    dominant_pattern = max(patterns, key=patterns.get)
    
    # Classification mapping
    classifications = {
        'data_heavy': 'Data Processing',
        'screen_heavy': 'User Interface',
        'program_heavy': 'Business Logic',
        'navigation': 'Navigation/Menu'
    }
    
    primary_type = classifications.get(dominant_pattern, 'Mixed Functionality')
    
    return primary_type, dominant_pattern

def get_component_priority_weight_local(component_type: str, config: Dict[str, Any] = None) -> float:
    """Return priority weight for component types - Configurable via environment variables"""
    
    # Use helper utility if available
    if get_component_priority_weight is not None:
        return get_component_priority_weight(component_type, config)
    
    # Fallback inline implementation (for backward compatibility)
    if config is None:
        config = parse_component_weights()
    
    priority_types = config['priority_types']
    medium_types = config['medium_types']
    
    # Ignored components (Weight 0.0) - only truly ignorable components for complexity scoring
    ignored_types = {
        'FILE_DEFINITION': 0.0,
        'Missing Source File': 0.0,    # Documentation artifacts
        'System': 0.0,                 # System components
        'Symbolic parameter': 0.0,     # JCL parameters
        'Unknown': 0.0,                # Unidentified
        'md': 0.0,                     # Documentation files
        'drawio': 0.0,                 # Diagram files
        'zip': 0.0,                    # Archive files
        'INIT': 0.0,                   # Initialization files
        'LISTCAT': 0.0                 # Catalog listings
    }
    # Note: Missing Program removed - should add complexity weight based on risk classification!
    
    # Return appropriate weight
    if component_type in priority_types:
        return priority_types[component_type]
    elif component_type in medium_types:
        return medium_types[component_type]
    elif component_type in ignored_types:
        return ignored_types[component_type]
    else:
        return 0.3  # Default weight for unknown types

def find_minimal_dependency_entry_points_cics_enhanced(
    dependencies_data: List[Dict], 
    target_type: str, 
    entry_point_types: List[str],
    missing_data: pd.DataFrame,
    csd_data: pd.DataFrame,
    max_results: int,
    cics_detection: Dict,
    weights_config: Dict[str, Any]
) -> Dict:
    
    # Build dependency graph and component info
    graph = {}
    components = {}
    
    for item in dependencies_data:
        name = item['name']
        components[name] = item
        graph[name] = [dep['name'] for dep in item['dependencies']]
    
    # Build CSD transaction-to-program mapping if available
    transaction_mapping = {}
    if csd_data is not None:
        transaction_mapping = build_transaction_mapping(csd_data)
    
    # Build missing components map with prioritization
    missing_by_parent = {}
    if missing_data is not None:
        for _, row in missing_data.iterrows():
            parents = str(row.get('Parents', '')).split(',') if pd.notna(row.get('Parents')) else []
            for parent in parents:
                parent = parent.strip()
                if parent:
                    if parent not in missing_by_parent:
                        missing_by_parent[parent] = []
                    missing_by_parent[parent].append({
                        'name': row['Name'],
                        'type': row['Type'],
                        'priority_weight': get_component_priority_weight_local(row['Type'], weights_config)
                    })
    
    # Find entry points that execute target functionality
    entry_point_candidates = []
    
    for comp_name, comp_info in components.items():
        # Enhanced entry point type checking for actual CICS types
        if not is_entry_point_accurate(comp_info['type'], entry_point_types):
            continue
        
        # Check if this entry point executes target functionality
        target_execution = get_target_execution(comp_name, graph, components, target_type)
        
        if target_execution['executes_target']:
            # Calculate prioritized dependency scores with CICS enhancement
            scores = calculate_prioritized_scores_cics_enhanced(
                comp_name, graph, components, missing_by_parent, transaction_mapping, weights_config
            )
            
            entry_point_candidates.append({
                'component_name': comp_name,
                'component_type': comp_info['type'],
                'component_path': comp_info.get('path', ''),
                'entry_point_category': categorize_entry_point_accurate(comp_info['type']),
                'total_dependencies': scores['total_dependencies'],
                'priority_dependencies': scores['priority_dependencies'],
                'medium_dependencies': scores['medium_dependencies'],
                'ignored_dependencies': scores['ignored_dependencies'],
                'missing_priority_count': scores['missing_priority_count'],
                'missing_medium_count': scores['missing_medium_count'],
                'weighted_complexity_score': scores['weighted_complexity_score'],
                'cics_complexity_factor': scores.get('cics_complexity_factor', 0),
                'executes': target_execution['executed_components'],
                'execution_details': target_execution['execution_details'],
                'priority_missing_components': scores['priority_missing_details'],
                'medium_missing_components': scores['medium_missing_details'],
                'transaction_mapping': transaction_mapping.get(comp_name, {}),
                'functionality_pattern': scores['functionality_pattern']  # NEW: Add pattern data
            })
    
    # Sort by weighted complexity score (ascending - least complex first)
    entry_point_candidates.sort(key=lambda x: x['weighted_complexity_score'])
    
    # Limit results
    ranked_results = entry_point_candidates[:max_results]
    
    # Add rank
    for i, result in enumerate(ranked_results, 1):
        result['rank'] = i
    
    # Generate analysis summary with CICS context
    analysis_summary = generate_cics_enhanced_analysis_summary(entry_point_candidates, target_type, cics_detection)
    
    # Build component weight configuration for agent
    component_weights = {}
    for comp_type, weight in weights_config['priority_types'].items():
        component_weights[comp_type] = {'weight': weight, 'category': 'priority'}
    for comp_type, weight in weights_config['medium_types'].items():
        component_weights[comp_type] = {'weight': weight, 'category': 'medium'}
    
    # Add ignored types (only truly ignorable components)
    ignored_types_for_weights = {'FILE_DEFINITION': 0.0, 'Missing Source File': 0.0, 'System': 0.0, 'Symbolic parameter': 0.0, 'Unknown': 0.0}
    for comp_type, weight in ignored_types_for_weights.items():
        component_weights[comp_type] = {'weight': weight, 'category': 'ignored'}

    return {
        'ranked_entry_points': ranked_results,
        'analysis_summary': analysis_summary,
        'cics_detection': cics_detection,
        'component_weights': component_weights,
        'scoring_methodology': {
            'priority_components': f'Configurable priority types (weight: {weights_config["scoring_multipliers"]["priority_weight"]})',
            'medium_components': f'Configurable medium types (weight: {weights_config["scoring_multipliers"]["medium_weight"]})',
            'ignored_components': 'File Definitions, Documentation, System Files (weight: 0.0)',
            'cics_enhancement': f'Additional complexity factor for CICS transaction dependencies (factor: {weights_config["scoring_multipliers"]["cics_complexity_factor"]})',
            'pattern_analysis': 'Functionality patterns: Business Logic, Data Processing, User Interface, Navigation',
            'weighted_formula': f'priority_deps * {weights_config["scoring_multipliers"]["priority_weight"]} + medium_deps * {weights_config["scoring_multipliers"]["medium_weight"]} + missing_priority * {weights_config["scoring_multipliers"]["missing_priority_penalty"]} + missing_medium * {weights_config["scoring_multipliers"]["missing_medium_penalty"]} + cics_factor * {weights_config["scoring_multipliers"]["cics_complexity_factor"]}',
            'configuration_source': 'Environment variable COMPONENT_WEIGHTS' if os.environ.get('COMPONENT_WEIGHTS') else 'Default hardcoded values'
        },
        'search_criteria': {
            'target_type': target_type,
            'entry_point_types': entry_point_types,
            'total_candidates_found': len(entry_point_candidates),
            'results_returned': len(ranked_results),
            'csd_provided': csd_data is not None
        }
    }

def is_entry_point_accurate(component_type: str, entry_point_types: List[str]) -> bool:
    """Enhanced entry point detection for actual CICS types"""
    # Direct type matching
    if component_type in entry_point_types:
        return True
    
    # CICS-specific matching for actual types
    cics_entry_types = ['TRANSACTION', 'BMS', 'CICS_FILE']
    if any(cics_type in entry_point_types for cics_type in ['CICS', 'TRANSACTION', 'BMS']) and component_type in cics_entry_types:
        return True
    
    return False

def categorize_entry_point_accurate(component_type: str) -> str:
    """Categorize entry point as batch or online based on actual types"""
    batch_types = ['JCL', 'PROC']
    online_types = ['TRANSACTION', 'BMS', 'CICS_FILE', 'CSDCOMMAND']
    
    if component_type in batch_types:
        return 'Batch'
    elif component_type in online_types:
        return 'Online'
    else:
        return 'Unknown'

def build_transaction_mapping(csd_data: pd.DataFrame) -> Dict:
    """Build transaction-to-program mapping from CSD data"""
    mapping = {}
    
    # Assuming CSD CSV has columns: Transaction, Program, Description
    for _, row in csd_data.iterrows():
        transaction = row.get('Transaction', '')
        program = row.get('Program', '')
        description = row.get('Description', '')
        
        if transaction and program:
            mapping[transaction] = {
                'program': program,
                'description': description,
                'type': 'CICS_Transaction'
            }
    
    return mapping

def calculate_prioritized_scores_cics_enhanced(
    comp_name: str, 
    graph: Dict, 
    components: Dict, 
    missing_by_parent: Dict,
    transaction_mapping: Dict,
    weights_config: Dict[str, Any]
) -> Dict:
    """Calculate prioritized complexity scores with CICS enhancement and pattern analysis"""
    
    # Get all transitive dependencies
    all_deps = get_all_transitive_dependencies(comp_name, graph)
    
    # NEW: Analyze functionality patterns
    patterns = analyze_functionality_pattern(comp_name, all_deps, components)
    functionality_type, dominant_pattern = classify_functionality(patterns)
    
    # Get scoring multipliers from configuration
    multipliers = weights_config['scoring_multipliers']
    priority_weight = multipliers['priority_weight']
    medium_weight = multipliers['medium_weight']
    
    # Categorize dependencies by priority
    priority_deps = []
    medium_deps = []
    ignored_deps = []
    
    for dep_name in all_deps:
        if dep_name in components:
            dep_type = components[dep_name]['type']
            weight = get_component_priority_weight_local(dep_type, weights_config)
            
            if weight == priority_weight:
                priority_deps.append(dep_name)
            elif weight == medium_weight:
                medium_deps.append(dep_name)
            else:
                ignored_deps.append(dep_name)
        else:
            ignored_deps.append(dep_name)
    
    # Categorize missing components - include transitive dependencies
    missing_components = missing_by_parent.get(comp_name, [])
    
    # Also check for missing components in the entire dependency chain
    if comp_name in graph:
        all_transitive_deps = get_all_transitive_dependencies(comp_name, graph)
        for dep_name in all_transitive_deps:
            if dep_name in missing_by_parent:
                missing_components.extend(missing_by_parent[dep_name])
    
    priority_missing = [m for m in missing_components if m['priority_weight'] == priority_weight]
    medium_missing = [m for m in missing_components if m['priority_weight'] == medium_weight]
    
    # Calculate CICS complexity factor
    cics_complexity_factor = 0
    if comp_name in transaction_mapping:
        cics_complexity_factor = 5  # Additional complexity for CICS transactions
    elif comp_name in components and components[comp_name]['type'] in ['TRANSACTION', 'BMS', 'CICS_FILE']:
        cics_complexity_factor = 3  # Medium complexity for CICS components
    
    # Calculate weighted complexity score with CICS enhancement using configurable multipliers
    weighted_score = (
        len(priority_deps) * multipliers['priority_weight'] +           # Priority dependencies
        len(medium_deps) * multipliers['medium_weight'] +               # Medium dependencies  
        len(priority_missing) * multipliers['missing_priority_penalty'] +  # Missing priority components penalty
        len(medium_missing) * multipliers['missing_medium_penalty'] +   # Missing medium components penalty
        cics_complexity_factor * multipliers['cics_complexity_factor'] # CICS transaction complexity
    )
    
    return {
        'total_dependencies': len(all_deps),
        'priority_dependencies': len(priority_deps),
        'medium_dependencies': len(medium_deps),
        'ignored_dependencies': len(ignored_deps),
        'missing_priority_count': len(priority_missing),
        'missing_medium_count': len(medium_missing),
        'weighted_complexity_score': weighted_score,
        'cics_complexity_factor': cics_complexity_factor,
        'priority_missing_details': priority_missing[:10],
        'medium_missing_details': medium_missing[:10],
        # NEW: Add functionality pattern data
        'functionality_pattern': {
            'primary_type': functionality_type,
            'dominant_pattern': dominant_pattern,
            'pattern_breakdown': patterns
        }
    }

def get_target_execution(entry_point: str, graph: Dict, components: Dict, target_type: str) -> Dict:
    """Check if entry point executes target functionality and return details"""
    
    # Get all transitive dependencies
    all_deps = get_all_transitive_dependencies(entry_point, graph)
    
    # Define target component types based on target_type
    target_component_types = {
        'application_program': ['COB', 'COBOL'],
        'database_reference': ['[SQL]TABLE', '[SQL]CURSOR', 'Missing Database Object'],
        'vsam_reference': ['VSAM KSDS DATASET', 'CICS_FILE', 'DATASET']
    }
    
    target_types = target_component_types.get(target_type, [])
    
    executed_components = []
    execution_details = []
    
    # Check direct dependencies
    for dep_name in graph.get(entry_point, []):
        if dep_name in components:
            dep_info = components[dep_name]
            if dep_info['type'] in target_types:
                executed_components.append(dep_name)
                execution_details.append({
                    'component': dep_name,
                    'type': dep_info['type'],
                    'access_level': 'Direct'
                })
    
    # Check transitive dependencies
    for dep_name in all_deps:
        if dep_name in components and dep_name not in executed_components:
            dep_info = components[dep_name]
            if dep_info['type'] in target_types:
                executed_components.append(dep_name)
                execution_details.append({
                    'component': dep_name,
                    'type': dep_info['type'],
                    'access_level': 'Transitive'
                })
    
    return {
        'executes_target': len(executed_components) > 0,
        'executed_components': executed_components,
        'execution_details': execution_details
    }

def get_all_transitive_dependencies(start: str, graph: Dict, visited: Set[str] = None) -> Set[str]:
    """Get all transitive dependencies for a component"""
    if visited is None:
        visited = set()
    
    if start in visited or start not in graph:
        return set()
    
    visited.add(start)
    all_deps = set()
    
    for dep in graph[start]:
        all_deps.add(dep)
        all_deps.update(get_all_transitive_dependencies(dep, graph, visited.copy()))
    
    return all_deps

def generate_cics_enhanced_analysis_summary(candidates: List[Dict], target_type: str, cics_detection: Dict) -> Dict:
    """Generate summary of prioritized analysis results with CICS context"""
    if not candidates:
        return {
            'message': f'No entry points found that execute {target_type} functionality',
            'recommendations': []
        }
    
    best_candidate = candidates[0]
    
    # Categorize candidates by entry point type
    batch_candidates = [c for c in candidates if c['entry_point_category'] == 'Batch']
    online_candidates = [c for c in candidates if c['entry_point_category'] == 'Online']
    
    return {
        'total_candidates': len(candidates),
        'batch_candidates': len(batch_candidates),
        'online_candidates': len(online_candidates),
        'best_entry_point': {
            'name': best_candidate['component_name'],
            'category': best_candidate['entry_point_category'],
            'weighted_complexity_score': round(best_candidate['weighted_complexity_score'], 1),
            'priority_dependencies': best_candidate['priority_dependencies'],
            'medium_dependencies': best_candidate['medium_dependencies'],
            'missing_priority_components': best_candidate['missing_priority_count'],
            'missing_medium_components': best_candidate['missing_medium_count'],
            'executes_count': len(best_candidate['executes'])
        },
        'cics_analysis': cics_detection,
        'recommendations': [
            f"Start with {best_candidate['component_name']} ({best_candidate['entry_point_category']}) - lowest weighted complexity ({best_candidate['weighted_complexity_score']:.1f})",
            f"Focus on {best_candidate['priority_dependencies']} priority dependencies (JCL/COBOL/Copybooks/BMS/CICS)",
            f"Address {best_candidate['missing_priority_count']} missing priority and {best_candidate['missing_medium_count']} missing medium components",
            f"Consider {'batch-first' if best_candidate['entry_point_category'] == 'Batch' else 'online-first'} modernization approach"
        ]
    }

def download_json_from_s3(s3_uri: str) -> List[Dict]:
    s3 = boto3.client('s3')
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    
    response = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(response['Body'].read().decode('utf-8'))

def download_csv_from_s3(s3_uri: str) -> pd.DataFrame:
    s3 = boto3.client('s3')
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    
    response = s3.get_object(Bucket=bucket, Key=key)
    csv_content = response['Body'].read().decode('utf-8')
    return pd.read_csv(StringIO(csv_content))