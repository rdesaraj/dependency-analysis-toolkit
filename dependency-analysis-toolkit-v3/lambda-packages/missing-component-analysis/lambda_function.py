import json
import boto3
import pandas as pd
import os
import base64
from typing import Dict, List, Any
from urllib.parse import urlparse
from io import StringIO

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
        
        # Extract parameters with defaults
        missing_components_s3_uri = params.get('missing_components_s3_uri', 's3://dependency-analysis/missing_files.csv')
        dependencies_s3_uri = params.get('dependencies_s3_uri', 's3://dependency-analysis/dependencies_20250911203624.json')
        risk_threshold = params.get('risk_threshold', 'MEDIUM')
        
        # Download and parse missing components
        missing_data = download_csv_from_s3(missing_components_s3_uri)
        
        # Download dependencies if provided for context
        dependencies_data = None
        if dependencies_s3_uri:
            dependencies_data = download_json_from_s3(dependencies_s3_uri)
        
        # Analyze missing components
        results = analyze_missing_components(missing_data, dependencies_data, risk_threshold)
        
        # Return in Bedrock format
        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": event.get('actionGroup', 'MissingComponentAnalysis'),
                "function": event.get('function', 'analyzeMissingComponents'),
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
                "actionGroup": event.get('actionGroup', 'MissingComponentAnalysis'),
                "function": event.get('function', 'analyzeMissingComponents'),
                "functionResponse": {
                    "responseBody": {
                        "TEXT": {
                            "body": json.dumps({"error": str(e)})
                        }
                    }
                }
            }
        }

def download_csv_from_s3(s3_uri: str) -> pd.DataFrame:
    s3 = boto3.client('s3')
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    
    response = s3.get_object(Bucket=bucket, Key=key)
    csv_content = response['Body'].read().decode('utf-8')
    return pd.read_csv(StringIO(csv_content))

def download_json_from_s3(s3_uri: str) -> List[Dict]:
    s3 = boto3.client('s3')
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip('/')
    
    response = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(response['Body'].read().decode('utf-8'))

def analyze_missing_components(missing_df: pd.DataFrame, dependencies_data: List[Dict], risk_threshold: str) -> Dict:
    # Calculate risk scores
    risk_analysis = calculate_risk_scores(missing_df, dependencies_data)
    
    # Calculate completeness score
    completeness = calculate_completeness_score(missing_df, dependencies_data)
    
    # Generate mitigation suggestions
    mitigations = generate_mitigation_suggestions(missing_df, risk_analysis)
    
    # Categorize by risk level
    risk_categories = categorize_by_risk(risk_analysis, risk_threshold)
    
    return {
        'risk_assessment': {
            'overall_risk': determine_overall_risk(risk_analysis),
            'missing_count': len(missing_df),
            'critical_missing': risk_categories.get('CRITICAL', [])[:10],  # Limit for response size
            'high_risk_missing': risk_categories.get('HIGH', [])[:15],
            'medium_risk_missing': risk_categories.get('MEDIUM', [])[:20],
            'low_risk_missing': risk_categories.get('LOW', [])[:10]
        },
        'completeness_score': completeness,
        'mitigation_suggestions': mitigations[:10],  # Limit suggestions
        'missing_by_type': analyze_missing_by_type(missing_df),
        'impact_analysis': analyze_impact_on_parents(missing_df, dependencies_data)
    }

def calculate_risk_scores(missing_df: pd.DataFrame, dependencies_data: List[Dict]) -> Dict[str, Dict]:
    """Calculate risk score for each missing component using configurable parameters"""
    risk_scores = {}
    
    # Configurable risk scoring parameters from environment variables (with defaults)
    parent_high_threshold = int(os.environ.get('RISK_PARENT_HIGH_THRESHOLD', '5'))
    parent_medium_threshold = int(os.environ.get('RISK_PARENT_MEDIUM_THRESHOLD', '2'))
    parent_high_score = int(os.environ.get('RISK_PARENT_HIGH_SCORE', '30'))
    parent_medium_score = int(os.environ.get('RISK_PARENT_MEDIUM_SCORE', '20'))
    parent_low_score = int(os.environ.get('RISK_PARENT_LOW_SCORE', '10'))
    
    critical_type_score = int(os.environ.get('RISK_CRITICAL_TYPE_SCORE', '40'))
    high_risk_type_score = int(os.environ.get('RISK_HIGH_TYPE_SCORE', '25'))
    medium_risk_type_score = int(os.environ.get('RISK_MEDIUM_TYPE_SCORE', '15'))
    
    jcl_parent_bonus = int(os.environ.get('RISK_JCL_PARENT_BONUS', '20'))
    
    critical_threshold = int(os.environ.get('RISK_CRITICAL_THRESHOLD', '70'))
    high_threshold = int(os.environ.get('RISK_HIGH_THRESHOLD', '50'))
    medium_threshold = int(os.environ.get('RISK_MEDIUM_THRESHOLD', '30'))
    
    # Component type classifications - now configurable via environment variables
    critical_types = os.environ.get('CRITICAL_RISK_TYPES', 'Missing Program,Missing Copybook').split(',')
    critical_types = [t.strip() for t in critical_types if t.strip()]
    
    high_risk_types = os.environ.get('HIGH_RISK_TYPES', 'Missing Database Object,Missing Control Card').split(',')
    high_risk_types = [t.strip() for t in high_risk_types if t.strip()]
    
    medium_risk_types = os.environ.get('MEDIUM_RISK_TYPES', 'Missing Dataset').split(',')
    medium_risk_types = [t.strip() for t in medium_risk_types if t.strip()]
    
    no_risk_types = os.environ.get('NO_RISK_TYPES', 'Missing Source File,Missing Header,System').split(',')
    no_risk_types = [t.strip() for t in no_risk_types if t.strip()]
    
    # Build parent dependency map if dependencies available
    parent_map = {}
    if dependencies_data:
        for item in dependencies_data:
            for dep in item['dependencies']:
                dep_name = dep['name']
                if dep_name not in parent_map:
                    parent_map[dep_name] = []
                parent_map[dep_name].append({
                    'parent': item['name'],
                    'parent_type': item['type'],
                    'relationship': dep.get('dependencyType', 'Unknown')
                })
    
    for _, row in missing_df.iterrows():
        missing_name = row['Name']
        missing_type = row['Type']
        parents = str(row.get('Parents', '')).split(',') if pd.notna(row.get('Parents')) else []
        
        # Calculate risk based on multiple factors
        risk_score = 0
        risk_factors = []
        
        # Factor 1: Number of parents (more parents = higher risk)
        parent_count = len([p for p in parents if p.strip()])
        if parent_count > parent_high_threshold:
            risk_score += parent_high_score
            risk_factors.append(f"High parent count ({parent_count})")
        elif parent_count > parent_medium_threshold:
            risk_score += parent_medium_score
            risk_factors.append(f"Medium parent count ({parent_count})")
        elif parent_count > 0:
            risk_score += parent_low_score
            risk_factors.append(f"Low parent count ({parent_count})")
        
        # Factor 2: Type of missing component
        if missing_type in no_risk_types:
            # No additional risk score for no-risk types
            risk_factors.append(f"No-risk component type ({missing_type})")
        elif missing_type in critical_types:
            risk_score += critical_type_score
            risk_factors.append(f"Critical component type ({missing_type})")
        elif missing_type in high_risk_types:
            risk_score += high_risk_type_score
            risk_factors.append(f"High-risk component type ({missing_type})")
        elif missing_type in medium_risk_types:
            risk_score += medium_risk_type_score
            risk_factors.append(f"Medium-risk component type ({missing_type})")
        
        # Factor 3: Parent types (JCL parents are more critical)
        if dependencies_data:
            parent_info = parent_map.get(missing_name, [])
            jcl_parents = [p for p in parent_info if p['parent_type'] == 'JCL']
            if jcl_parents:
                risk_score += jcl_parent_bonus
                risk_factors.append(f"Referenced by JCL ({len(jcl_parents)} JCLs)")
        
        # Determine risk level using configurable thresholds
        if risk_score >= critical_threshold:
            risk_level = 'CRITICAL'
        elif risk_score >= high_threshold:
            risk_level = 'HIGH'
        elif risk_score >= medium_threshold:
            risk_level = 'MEDIUM'
        else:
            risk_level = 'LOW'
        
        risk_scores[missing_name] = {
            'name': missing_name,
            'type': missing_type,
            'risk_score': risk_score,
            'risk_level': risk_level,
            'risk_factors': risk_factors,
            'parent_count': parent_count,
            'parents': [p.strip() for p in parents if p.strip()]
        }
    
    return risk_scores

def calculate_completeness_score(missing_df: pd.DataFrame, dependencies_data: List[Dict]) -> Dict:
    """Calculate system completeness score"""
    if not dependencies_data:
        return {'score': 0, 'message': 'Cannot calculate without dependency data'}
    
    total_components = len(dependencies_data)
    missing_count = len(missing_df)
    
    # Calculate completeness percentage
    completeness_pct = ((total_components - missing_count) / total_components) * 100 if total_components > 0 else 0
    
    return {
        'score': round(completeness_pct, 1),
        'total_components': total_components,
        'missing_components': missing_count,
        'available_components': total_components - missing_count,
        'assessment': get_completeness_assessment(completeness_pct)
    }

def get_completeness_assessment(score: float) -> str:
    """Get qualitative assessment of completeness score"""
    if score >= 90:
        return 'Excellent - System is highly complete'
    elif score >= 80:
        return 'Good - System is mostly complete'
    elif score >= 70:
        return 'Fair - Some gaps exist'
    elif score >= 60:
        return 'Poor - Significant gaps exist'
    else:
        return 'Critical - Major components missing'

def generate_mitigation_suggestions(missing_df: pd.DataFrame, risk_analysis: Dict) -> List[str]:
    """Generate mitigation suggestions based on missing components"""
    suggestions = []
    
    # Analyze critical and high-risk components
    critical_components = [comp for comp in risk_analysis.values() if comp['risk_level'] == 'CRITICAL']
    high_risk_components = [comp for comp in risk_analysis.values() if comp['risk_level'] == 'HIGH']
    
    if critical_components:
        suggestions.append(f"Immediate action required: {len(critical_components)} critical components missing")
        suggestions.append("Focus on critical missing programs and database objects first")
    
    if high_risk_components:
        suggestions.append(f"High priority: Address {len(high_risk_components)} high-risk missing components")
    
    # Type-specific suggestions
    missing_by_type = missing_df['Type'].value_counts().to_dict()
    
    if missing_by_type.get('Missing Dataset', 0) > 0:
        suggestions.append(f"Create or locate {missing_by_type['Missing Dataset']} missing datasets")
    
    if missing_by_type.get('Missing Program', 0) > 0:
        suggestions.append(f"Develop or recover {missing_by_type['Missing Program']} missing programs")
    
    if missing_by_type.get('Missing Database Object', 0) > 0:
        suggestions.append(f"Create {missing_by_type['Missing Database Object']} missing database objects")
    
    suggestions.append("Consider phased approach: address critical components first")
    suggestions.append("Validate missing components - some may be system-provided or obsolete")
    
    return suggestions

def categorize_by_risk(risk_analysis: Dict, threshold: str) -> Dict[str, List[Dict]]:
    """Categorize components by risk level"""
    categories = {'CRITICAL': [], 'HIGH': [], 'MEDIUM': [], 'LOW': []}
    
    for comp_name, comp_info in risk_analysis.items():
        risk_level = comp_info['risk_level']
        categories[risk_level].append(comp_info)
    
    # Sort each category by risk score (descending)
    for category in categories:
        categories[category].sort(key=lambda x: x['risk_score'], reverse=True)
    
    return categories

def determine_overall_risk(risk_analysis: Dict) -> str:
    """Determine overall system risk based on missing components"""
    if not risk_analysis:
        return 'UNKNOWN'
    
    risk_counts = {'CRITICAL': 0, 'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
    
    for comp_info in risk_analysis.values():
        risk_counts[comp_info['risk_level']] += 1
    
    # Configurable overall risk thresholds
    high_risk_count_threshold = int(os.environ.get('OVERALL_RISK_HIGH_COUNT_THRESHOLD', '5'))
    medium_risk_count_threshold = int(os.environ.get('OVERALL_RISK_MEDIUM_COUNT_THRESHOLD', '10'))
    
    if risk_counts['CRITICAL'] > 0:
        return 'CRITICAL'
    elif risk_counts['HIGH'] > high_risk_count_threshold:
        return 'HIGH'
    elif risk_counts['HIGH'] > 0 or risk_counts['MEDIUM'] > medium_risk_count_threshold:
        return 'MEDIUM'
    else:
        return 'LOW'

def analyze_missing_by_type(missing_df: pd.DataFrame) -> Dict:
    """Analyze missing components by type"""
    type_counts = missing_df['Type'].value_counts().to_dict()
    
    return {
        'type_breakdown': type_counts,
        'most_common_missing': max(type_counts.items(), key=lambda x: x[1]) if type_counts else ('None', 0),
        'total_types': len(type_counts)
    }

def analyze_impact_on_parents(missing_df: pd.DataFrame, dependencies_data: List[Dict]) -> Dict:
    """Analyze impact of missing components on parent components"""
    if not dependencies_data:
        return {'message': 'Cannot analyze impact without dependency data'}
    
    # Build parent impact map
    parent_impact = {}
    
    for _, row in missing_df.iterrows():
        missing_name = row['Name']
        parents = str(row.get('Parents', '')).split(',') if pd.notna(row.get('Parents')) else []
        
        for parent in parents:
            parent = parent.strip()
            if parent:
                if parent not in parent_impact:
                    parent_impact[parent] = []
                parent_impact[parent].append(missing_name)
    
    # Sort parents by impact (number of missing dependencies)
    sorted_parents = sorted(parent_impact.items(), key=lambda x: len(x[1]), reverse=True)
    
    return {
        'most_impacted_parents': sorted_parents[:10],  # Top 10 most impacted
        'total_impacted_parents': len(parent_impact),
        'average_missing_per_parent': sum(len(missing) for missing in parent_impact.values()) / len(parent_impact) if parent_impact else 0
    }