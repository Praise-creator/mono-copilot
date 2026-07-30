# BRD: Network Connectivity Optimization

## Executive Summary
During peak hours, network connectivity issues have led to significant revenue loss due to prolonged downtimes and manual resolution processes. The current manual process of logging and ticketing network failures is inefficient, taking over 8 hours for initial diagnostics. We propose an automated system that detects connectivity problems within 30 seconds, enabling quicker failover and significantly reducing resolution time.

## Current Process Flow
**Customer Journey:**
- **Entry:** Customer experiences connectivity issue.
- **Interaction:** Customer calls support.
- **Resolution:** Support logs issue manually, creates a ticket, and resolves within 24-48 hours.

**System Behavior:**
- **Support Portal:** Used for taking calls and manually entering incident logs.
- **Network Monitoring:** Passively monitors network but does not trigger any alerts.
  
**Bottlenecks:**
- Manual investigation by support staff, averaging 8+ hours before initiating a proper response.

## Proposed Process Flow
**Customer Journey:**
- **Entry:** Customer experiences connectivity issue.
- **Interaction:** AI Detection System automatically detects the issue in real-time.
- **Resolution:** System immediately triggers a failover to backup network; ticket is auto-generated for permanent fix.

**System Changes:**
- **Network Monitoring:** Upgraded to interact with AI Detection System for real-time performance issues.
- **AI Detection System:** Analyzes network traffic and detects anomalies instantly.
- **Failover System:** Activated automatically upon detection of a fault.

**Flow Improvements:**
- **Reduction in Detection Time:** From 8+ hours to 30 seconds.
- **Decrease in Resolution Time:** Potential issues resolved preemptively with instant failover; permanent solutions expedited by immediate ticket generation.

**Swimlanes:** Customer → AI Detection System → Failover Process → Network Team

## Use Cases

### Business Use Cases
- **UC1:** As a network administrator, I want to be immediately alerted of connectivity issues, so that I can ensure high uptime.
- **UC2:** As a customer, I want minimal service interruption, so that my business operations can continue smoothly.

### Technical Use Cases
- **UC1:** Network Monitoring streams data to AI Detection, which uses machine learning to detect anomalies and trigger failovers.
- **UC2:** On detection of a fault, AI Detection directly interfaces with Failover System to switch operations to a backup network.

## Integration Architecture

### System Integrations
- **Network Monitoring → AI Detection:** Stream data using WebSocket for real-time analysis.
- **AI Detection → Failover System:** REST API to initiate immediate failover.
- **Failover System → Support Portal:** Automatically logs tickets for follow-up using an internal REST API.

## Exception Management

### Failure Scenarios & Handling
1. **AI Detection Failure:**
   - **Detection:** Failure to analyze incoming data.
   - **User Impact:** Delay in fault detection.
   - **Recovery:** Switch to secondary AI Detection System.
   - **System Action:** Alert admin and switch to backup.
   - **Support Action:** Review incident and optimize system resilience.

2. **Failover Process Interruption:**
   - **Detection:** Incomplete failover protocol execution.
   - **User Impact:** Extended network downtime.
   - **Recovery:** Manual failover activation.
   - **System Action:** System-wide alert and manual override.
   - **Support Action:** Immediate manual intervention and system audit.

## Business Rules

### Validation Rules
- **AI Alerts:** Must trigger if loss exceeds 5% normal throughput.
- **Data Integrity:** Ensure all streamed data is complete and timely.

### Authorization Rules
- **System Access:** Only certified technicians can modify AI and failover configurations.
- **Data Privacy:** Network data handled must comply with GDPR and other relevant laws.

### Calculation Rules
- **Anomaly Detection:** Trigger based on statistical deviations from historical mean performance values.

## Conclusion
The proposed automated detection and failover system will significantly enhance network reliability and customer satisfaction by reducing downtime and operational disruptions during peak times, thereby retaining customer trust and minimizing revenue losses.