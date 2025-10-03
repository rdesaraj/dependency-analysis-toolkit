# Dependency Analysis Toolkit

## Purpose-Built Solution for AWS Transform Engagements

**The Challenge**: After customers onboard ATX, Without SMEs or source code access, understanding system complexity and scoping POCs becomes a significant bottleneck in customer engagements.

**The Solution**: AI-powered analysis that transforms ATX dependencies and missing components artifacts into actionable modernization insights through natural language conversation.

---

## Three Critical Problems Solved

### 1. System Integration Discovery
**Problem**: Understanding what types of integrations exist in the mainframe system at high level
**Solution**: Automated categorization of database, batch, online, and external system integrations  
**Value**: Understanding system architecture and integration points without discovery calls

### 2. POC Candidate Identification  
**Problem**: Selecting the right functionality to modernize first without domain expertise  
**Solution**: Complexity scoring algorithm that ranks modernization candidates by feasibility  
**Value**: Data-driven POC selection with detailed component analysis

### 3. Missing Component Risk Assessment
**Problem**: Understanding the development impact of missing system components  
**Solution**: Risk analysis of missing programs and database objects across the application landscape  
**Value**: Development scope planning

---

## Architecture
<img width="907" height="512" alt="image" src="https://github.com/user-attachments/assets/157cb6e3-5fa9-4dcf-8520-1d679a1005da" />


## Key Capabilities

- **Natural Language Interface**: Ask questions about system complexity in plain English
- **Complexity Scoring**: Algorithmic ranking of POC candidates based on dependency analysis
- **Integration Classification**: Automatic categorization of system integration patterns
- **Risk Assessment**: Impact analysis of missing components on modernization effort
- **Configurable Weighting**: Adjust complexity factors based on customer priorities
- **Dependency Chain Analysis**: Complete transitive dependency mapping

---

## Architecture

**AI-Powered Analysis ** built on Amazon Bedrock for natural language processing, supported by AWS Lambda functions for dependency analysis and complexity scoring.

**Input**: ATX Dependencies JSON + Missing Components CSV  
**Output**: Structured analysis and recommendations through conversational interface

---

## Sample Analysis Workflow

```
"What are the integration types in this system?"
→ Categorized breakdown of database, file, and external integrations (FTP, MQ etc)

"Recommend POC candidates for modernization"  
→ Ranked list with complexity scores and component analysis

"Compare POC recommendations"  
→ Comparison table for recommended functions with dependencies, integrations ,missing components and complexity scoring

"What missing components pose the highest risk?"
→ Prioritized list of missing elements with impact assessment
```

---

## Business Value

**Accelerated Engagement Scoping**: Transform complex dependency analysis into immediate insights  
**Risk Mitigation**: Identify potential development challenges before POC selection  
**Data-Driven Decisions**: Remove guesswork from modernization planning  
**Customer Confidence**: Provide clear rationale for recommended modernization approach

---

## Deployment

Complete CloudFormation automation for rapid deployment in customer environments. All components designed for seamless integration into existing AWS Transform workflows.
