import json
import boto3
import os
import re
import base64
from typing import Dict, List, Any, Set
from urllib.parse import urlparse

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
        
        # Extract parameters
        dependencies_s3_uri = params['dependencies_s3_uri']
        query_text = params['query_text']
        include_transitive = params.get('include_transitive', True)
        component_types = params.get('component_types', [])
        
        # Download and parse dependencies
        dependencies_data = download_json_from_s3(dependencies_s3_uri)
        
        # Analyze dependencies based on query
        results = analyze_dependencies(dependencies_data, query_text, include_transitive, component_types)
        
        # Return in Bedrock format
        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": event.get('actionGroup', 'DependencyAnalysis'),
                "function": event.get('function', 'analyzeDependencies'),
                "functionResponse": {
                    "responseBody": {
                        "TEXT": {
                            "body": json.dumps(results)
                        }
                    }
                }
            }
        }
        
    except Exception as e:
        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": event.get('actionGroup', 'DependencyAnalysis'),
                "function": event.get('function', 'analyzeDependencies'),
                "functionResponse": {
                    "responseBody": {
                        "TEXT": {
                            "body": json.dumps({"error": str(e)})
                        }
                    }
                }
            }
        }

def download_json_from_s3(s3_uri: str) -> List[Dict]:
    s3 = boto3.client('s3')
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    
    response = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(response['Body'].read().decode('utf-8'))

def analyze_dependencies(data: List[Dict], query: str, include_transitive: bool, component_types: List[str]) -> Dict:
    # Configurable limits from environment variables
    direct_deps_limit = int(os.environ.get('DIRECT_DEPS_LIMIT', '10'))
    transitive_chains_limit = int(os.environ.get('TRANSITIVE_CHAINS_LIMIT', '10'))
    dependents_limit = int(os.environ.get('DEPENDENTS_LIMIT', '30'))
    dependencies_limit = int(os.environ.get('DEPENDENCIES_LIMIT', '20'))
    results_limit = int(os.environ.get('RESULTS_LIMIT', '50'))
    chains_results_limit = int(os.environ.get('CHAINS_RESULTS_LIMIT', '20'))
    max_depth = int(os.environ.get('MAX_DEPTH', '10'))
    
    # Build dependency graph
    graph = {}
    components = {}
    
    for item in data:
        name = item['name']
        components[name] = item
        graph[name] = [dep['name'] for dep in item['dependencies']]
    
    # Check if this is a component type search query
    query_intent = detect_query_intent(query)
    
    if query_intent['intent'] == 'component_type_search':
        # Return components by type instead of dependency analysis
        matching_components = []
        for name, comp_info in components.items():
            if comp_info['type'] in query_intent['types']:
                matching_components.append({
                    'component_name': name,
                    'component_type': comp_info['type'],
                    'component_path': comp_info.get('path', ''),
                    'dependency_count': len(graph.get(name, [])),
                    'access_details': [],
                    'is_target': False
                })
        
        return {
            'dependency_results': matching_components[:results_limit],
            'transitive_chains': [],
            'impact_scope': {
                'total_components': len(matching_components),
                'targets_found': 0,
                'component_types_affected': query_intent['types'],
                'bidirectional_analysis': False
            },
            'query_interpretation': {
                'query_type': 'component_type_search',
                'types_requested': query_intent['types'],
                'description': query_intent['description']
            }
        }
    
    # Parse query to find target components
    target_components = extract_targets_from_query(query, components)
    
    if not target_components:
        sample_limit = int(os.environ.get('SAMPLE_LIMIT', '10'))
        return {
            'error': 'No target components found in query',
            'available_components_sample': list(components.keys())[:sample_limit],
            'query_received': query
        }
    
    # Find components related to targets (BIDIRECTIONAL)
    dependency_results = []
    transitive_chains = []
    
    for target in target_components:
        # Find what depends ON this target (reverse dependencies) - IMPACT ANALYSIS
        dependents = find_dependents(target, graph, components, include_transitive)
        
        # Find what this target depends ON (forward dependencies)  
        dependencies = find_dependencies(target, graph, components, include_transitive)
        
        # Add target itself with its direct dependencies
        if target in components:
            target_info = components[target]
            dependency_results.append({
                'component_name': target,
                'component_type': target_info['type'],
                'component_path': target_info.get('path', ''),
                'dependency_count': len(graph.get(target, [])),
                'access_details': [{
                    'target': dep_name,
                    'relationship': 'Direct',
                    'direction': f"{target} → {dep_name}",
                    'access_type': 'Target Dependencies'
                } for dep_name in graph.get(target, [])[:direct_deps_limit]],
                'is_target': True
            })
            
            # Add transitive chains from target
            if include_transitive:
                chains = get_dependency_chains(target, graph, components, max_depth=max_depth)
                transitive_chains.extend(chains[:transitive_chains_limit])
        
        # Add dependents (what would be affected) - THIS IS KEY FOR IMPACT ANALYSIS
        dependency_results.extend(dependents[:dependents_limit])
        dependency_results.extend(dependencies[:dependencies_limit])
    
    # Filter by component types if specified
    if component_types:
        dependency_results = [r for r in dependency_results if r['component_type'] in component_types]
    
    return {
        'dependency_results': dependency_results[:results_limit],
        'transitive_chains': transitive_chains[:chains_results_limit],
        'impact_scope': {
            'total_components': len(dependency_results),
            'targets_found': len(target_components),
            'component_types_affected': list(set(r['component_type'] for r in dependency_results)),
            'bidirectional_analysis': True
        },
        'query_interpretation': {
            'targets_identified': target_components,
            'include_transitive': include_transitive,
            'component_type_filter': component_types,
            'analysis_directions': ['dependencies_of_target', 'dependents_on_target', 'transitive_both_ways']
        }
    }

def detect_query_intent(query: str) -> Dict:
    """Detect if query is asking for component types rather than specific components"""
    query_lower = query.lower()
    
    # Get configurable keyword mappings from environment
    database_keywords = os.environ.get('DATABASE_KEYWORDS', 'database,sql,ddl,dcl,db2,table,schema,integration').split(',')
    database_types = os.environ.get('DATABASE_TYPES', 'DDL,DCL,SQL,dcl').split(',')
    
    cics_keywords = os.environ.get('CICS_KEYWORDS', 'cics,transaction,bms,screen,online').split(',')
    cics_types = os.environ.get('CICS_TYPES', 'TRANSACTION,BMS,CICS_FILE,CSDCOMMAND').split(',')
    
    batch_keywords = os.environ.get('BATCH_KEYWORDS', 'jcl,job,batch,procedure').split(',')
    batch_types = os.environ.get('BATCH_TYPES', 'JCL,PROC').split(',')
    
    cobol_keywords = os.environ.get('COBOL_KEYWORDS', 'cobol,program,copybook').split(',')
    cobol_types = os.environ.get('COBOL_TYPES', 'COB,COBOL,CPY').split(',')
    
    if any(keyword.strip() in query_lower for keyword in database_keywords):
        return {
            'intent': 'component_type_search',
            'types': [t.strip() for t in database_types],
            'description': 'database components'
        }
    
    if any(keyword.strip() in query_lower for keyword in cics_keywords):
        return {
            'intent': 'component_type_search',
            'types': [t.strip() for t in cics_types], 
            'description': 'CICS/online components'
        }
    
    if any(keyword.strip() in query_lower for keyword in batch_keywords):
        return {
            'intent': 'component_type_search',
            'types': [t.strip() for t in batch_types],
            'description': 'JCL/batch components'
        }
    
    if any(keyword.strip() in query_lower for keyword in cobol_keywords):
        return {
            'intent': 'component_type_search',
            'types': [t.strip() for t in cobol_types],
            'description': 'COBOL components'
        }
    
    return {'intent': 'dependency_analysis'}

def extract_targets_from_query(query: str, components: Dict) -> List[str]:
    targets = []
    
    # More flexible patterns to catch component names
    patterns = [
        r'\b[A-Z][A-Z0-9]*\.[a-zA-Z]+\b',  # COMPONENT.ext
        r'\b[A-Z][A-Z0-9]*[A-Z0-9]\b',     # UPPERCASE names
        r'\b\w+\.\w+\b'                     # any.extension
    ]
    
    # Try each pattern
    for pattern in patterns:
        matches = re.findall(pattern, query)
        for match in matches:
            # Check if this match exists in components (exact match)
            if match in components:
                targets.append(match)
            else:
                # Try case-insensitive match
                for comp_name in components.keys():
                    if comp_name.lower() == match.lower():
                        targets.append(comp_name)
                        break
    
    # If no patterns worked, try direct substring matching
    if not targets:
        query_upper = query.upper()
        for comp_name in components.keys():
            if comp_name.upper() in query_upper:
                targets.append(comp_name)
    
    return list(set(targets))

def find_dependents(target: str, graph: Dict, components: Dict, include_transitive: bool) -> List[Dict]:
    """Find components that depend ON the target (what would be affected if target changes)"""
    dependents = []
    
    for comp_name, comp_deps in graph.items():
        if comp_name == target:
            continue
            
        if target in comp_deps:
            # Direct dependent - this component directly uses the target
            comp_info = components.get(comp_name, {'type': 'Unknown', 'path': ''})
            dependents.append({
                'component_name': comp_name,
                'component_type': comp_info['type'],
                'component_path': comp_info.get('path', ''),
                'dependency_count': len(comp_deps),
                'access_details': [{
                    'target': target,
                    'relationship': 'Direct',
                    'direction': f"{comp_name} → {target}",
                    'access_type': 'Would Be Affected (Direct)'
                }],
                'is_target': False
            })
        elif include_transitive:
            # Check transitive dependents
            if target in get_all_transitive_dependencies(comp_name, graph):
                comp_info = components.get(comp_name, {'type': 'Unknown', 'path': ''})
                dependents.append({
                    'component_name': comp_name,
                    'component_type': comp_info['type'],
                    'component_path': comp_info.get('path', ''),
                    'dependency_count': len(comp_deps),
                    'access_details': [{
                        'target': target,
                        'relationship': 'Transitive',
                        'direction': f"{comp_name} ⇉ {target}",
                        'access_type': 'Would Be Affected (Transitive)'
                    }],
                    'is_target': False
                })
    
    return dependents

def find_dependencies(target: str, graph: Dict, components: Dict, include_transitive: bool) -> List[Dict]:
    dependencies = []
    
    if target not in graph:
        return dependencies
    
    # Direct dependencies
    for dep_name in graph[target]:
        dep_info = components.get(dep_name, {'type': 'Unknown', 'path': ''})
        dependencies.append({
            'component_name': dep_name,
            'component_type': dep_info['type'],
            'component_path': dep_info.get('path', ''),
            'dependency_count': len(graph.get(dep_name, [])),
            'access_details': [{
                'target': dep_name,
                'relationship': 'Direct',
                'direction': f"{target} → {dep_name}",
                'access_type': 'Target Uses This'
            }],
            'is_target': False
        })
    
    # Transitive dependencies
    if include_transitive:
        all_transitive = get_all_transitive_dependencies(target, graph)
        direct_deps = set(graph[target])
        
        for dep_name in all_transitive:
            if dep_name not in direct_deps:
                dep_info = components.get(dep_name, {'type': 'Unknown', 'path': ''})
                dependencies.append({
                    'component_name': dep_name,
                    'component_type': dep_info['type'],
                    'component_path': dep_info.get('path', ''),
                    'dependency_count': len(graph.get(dep_name, [])),
                    'access_details': [{
                        'target': dep_name,
                        'relationship': 'Transitive',
                        'direction': f"{target} ⇉ {dep_name}",
                        'access_type': 'Target Uses This (Indirect)'
                    }],
                    'is_target': False
                })
    
    return dependencies

def get_all_transitive_dependencies(start: str, graph: Dict, visited: Set[str] = None) -> Set[str]:
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

def get_dependency_chains(start: str, graph: Dict, components: Dict, max_depth: int = 3, current_chain: List[str] = None) -> List[Dict]:
    if current_chain is None:
        current_chain = [start]
    
    if len(current_chain) >= max_depth or start not in graph:
        return []
    
    chains = []
    
    for dep in graph[start]:
        new_chain = current_chain + [dep]
        chains.append({
            'chain': new_chain,
            'depth': len(new_chain) - 1,
            'direction': 'FROM_SOURCE',
            'source': current_chain[0],
            'chain_types': [components.get(comp, {}).get('type', 'Unknown') for comp in new_chain]
        })
        
        # Recursively get longer chains
        chains.extend(get_dependency_chains(dep, graph, components, max_depth, new_chain))
    
    return chains