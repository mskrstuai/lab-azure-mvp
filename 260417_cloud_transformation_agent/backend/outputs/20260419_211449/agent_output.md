## Summary
Migrate the discovered ThreeTierWebArch scope into a single Azure Resource Group in eastus, preserving the three-tier pattern with managed Azure services. Based on the provided resources, map Aurora MySQL Serverless to Azure Database for MySQL Flexible Server, the internet-facing ALB to Azure Application Gateway or Azure Front Door + Application Gateway, the internal ALB to an internal Application Gateway, and the AWS VPC to an Azure hub-spoke or single-spoke virtual network design. Use staged cutover with database replication or export/import, parallel application deployment, and DNS switchover to minimize downtime.

## Assessment
Moderate complexity based on currently visible resources, but the migration cannot be fully executed from the listed scope alone because the ALBs imply dependent backend compute, target groups, security groups, subnets, routing, and likely DNS/application components that were not provided. Prerequisites include discovery of ALB listeners/rules/target groups, backend application hosts or services, database schema and migration method, private/public subnet topology, security controls, and identity/secrets integration. Cross-region migration from ap-northeast-2 to eastus also requires latency, data residency, and cutover planning.

## Migration steps
### 1. Discover
Inventory all dependencies behind the listed resources and confirm the full application topology for the ThreeTierWebArch logical group.
- **AWS:** RDS Aurora MySQL Serverless, VPC, Application Load Balancers
- **Azure:** Azure Resource Group, Azure Migrate, Azure Virtual Network
- *Notes:* Identify ALB listeners, rules, target groups, backend instances/services, subnets, route tables, NAT/Internet access, security groups, DNS records, certificates, secrets, and application-to-database dependencies. Validation: complete dependency map exists for each listed resource and every ALB target is identified.

### 2. Design Landing Zone
Create the Azure landing zone in eastus with a resource group preserving the logical grouping, network segmentation, identity model, and operational controls.
- **AWS:** VPC
- **Azure:** Azure Resource Group, Azure Virtual Network, Network Security Groups, Azure Firewall or equivalent hub controls, Azure Bastion, ExpressRoute or Site-to-Site VPN, Microsoft Entra ID, Azure RBAC, Azure Key Vault, Azure Monitor
- *Notes:* At minimum, create a VNet with separate subnets for web/app/data and dedicated subnets for Application Gateway. Prefer hub-spoke if this workload will integrate with other environments; otherwise a single spoke VNet is acceptable. Establish private connectivity from AWS to Azure during migration using VPN or ExpressRoute if low-latency/private transfer is required. Validation: Azure network deployed, address space non-overlapping, connectivity tested, RBAC assigned, secrets store available, monitoring baseline enabled.

### 3. Map Database
Plan migration of Aurora MySQL Serverless to Azure Database for MySQL Flexible Server using a managed migration path that minimizes downtime.
- **AWS:** RDS Aurora MySQL Serverless
- **Azure:** Azure Database for MySQL Flexible Server, Azure Database Migration Service
- *Notes:* Match MySQL engine compatibility, sizing, HA requirements, backup retention, maintenance window, and private access. Because source is Aurora MySQL 8.0 compatible, validate feature compatibility before migration. Prefer online migration if supported for the exact source/target versions and workload; otherwise use dump/restore plus controlled cutover. Validation: schema migrated, application queries pass, replication lag acceptable or final cutover window approved, backup/restore tested.

### 4. Map External Traffic
Replace the internet-facing ALB with Azure-managed ingress for public traffic.
- **AWS:** Internet-facing ALB
- **Azure:** Azure Application Gateway WAF v2, Azure Front Door Standard/Premium, Azure DNS
- *Notes:* If only regional HTTP/S load balancing is needed, use Application Gateway WAF v2. If global edge acceleration, CDN, or advanced failover is required, place Front Door in front of Application Gateway. Recreate listeners, host/path routing, health probes, TLS certificates, redirects, and WAF policies. Validation: all ALB listener rules are reproduced, health probes succeed, TLS certs valid, public endpoint returns expected responses.

### 5. Map Internal Traffic
Replace the internal ALB with private Azure application ingress for east-west or private client traffic.
- **AWS:** Internal ALB
- **Azure:** Internal Azure Application Gateway, Internal Load Balancer
- *Notes:* Use internal Application Gateway if Layer 7 routing is required; use Internal Load Balancer only if the backend protocol is Layer 4 and no HTTP/S routing features are needed. Place it in a private subnet and integrate with private DNS if needed. Validation: private clients can resolve and reach the internal endpoint, routing rules match AWS behavior, backend health is green.

### 6. Migrate Application Tier
Deploy the backend application tier that currently sits behind the ALBs onto Azure managed compute, based on the actual AWS backend discovered.
- **AWS:** ALB target groups, Implied EC2/ECS/EKS/Lambda backends
- **Azure:** Azure Virtual Machine Scale Sets, Azure Kubernetes Service, Azure App Service, Azure Container Apps
- *Notes:* Choose target based on current runtime: EC2-based web/app servers typically map to VM/VMSS or App Service; containerized workloads map to AKS or Container Apps; serverless functions map to Azure Functions. Preserve subnet placement, autoscaling, health checks, and secret injection from Key Vault. Validation: application instances register healthy behind Azure ingress and pass functional tests.

### 7. Security and Identity
Implement Azure-native identity, access, and secret management for the migrated stack.
- **AWS:** VPC security boundaries, Implied IAM roles/secrets/certificates
- **Azure:** Microsoft Entra ID, Azure RBAC, Managed Identities, Azure Key Vault, Network Security Groups, Defender for Cloud
- *Notes:* Map AWS IAM usage to Entra ID, RBAC, and managed identities where applicable. Store database credentials, TLS certificates, and application secrets in Key Vault. Recreate least-privilege network rules with NSGs and private endpoints where appropriate. Validation: no hard-coded secrets remain, access reviews completed, privileged access minimized, security alerts enabled.

### 8. Observability and Protection
Establish monitoring, logging, backup, and disaster recovery for the Azure deployment before cutover.
- **AWS:** RDS, ALBs, VPC
- **Azure:** Azure Monitor, Log Analytics, Application Insights, Azure Backup, MySQL automated backups
- *Notes:* Enable metrics, logs, dashboards, and alerts for Application Gateway, compute, database, and network. Configure backup retention and test restore for MySQL. Define DR expectations because the target region is eastus and source is in ap-northeast-2; if regional resilience is required in Azure, design paired-region or cross-region backup strategy. Validation: alerts fire in test, logs are centralized, backup and restore tests succeed, RTO/RPO documented.

### 9. Cutover
Execute phased cutover with minimal downtime using pre-synced data, production validation, and DNS switchover.
- **AWS:** RDS endpoint, ALB DNS names
- **Azure:** Azure DNS, Application Gateway or Front Door endpoint, Azure Database for MySQL Flexible Server
- *Notes:* Run final data sync, place application in maintenance mode if required, switch connection strings/secrets, validate application health, then update DNS with reduced TTL. Keep AWS environment available for rollback until stabilization criteria are met. Validation: successful smoke tests, database writes confirmed on Azure, no critical errors in monitoring, rollback plan time-tested.

### 10. Decommission
Retire AWS resources only after stabilization and data retention requirements are met.
- **AWS:** RDS, VPC, ALBs
- **Azure:** Azure Resource Group
- *Notes:* Remove AWS resources in dependency order after confirming no traffic, no replication needs, and no compliance hold. Validation: DNS fully points to Azure, AWS metrics show no production traffic, final backups retained, decommission approvals recorded.

## Risks
- **Dependencies:** The listed ALBs almost certainly depend on backend compute and target groups that were not provided, so migration sequencing cannot be finalized.
  - *Mitigation:* Complete dependency discovery for listeners, rules, target groups, backend instances/services, and application runtime before design lock.
- **Data:** Aurora MySQL feature differences versus Azure Database for MySQL Flexible Server may cause incompatibilities or migration issues.
  - *Mitigation:* Run schema and feature compatibility assessment, test migration on a non-production copy, and remediate unsupported features before cutover.
- **Downtime:** Database cutover may require write freeze or brief outage if continuous replication is not feasible for the exact source/target combination.
  - *Mitigation:* Use online migration where supported, reduce DNS TTL in advance, rehearse cutover, and define rollback criteria.
- **Networking:** Cross-cloud migration from ap-northeast-2 to eastus introduces latency and may affect data transfer time, application behavior, and user experience.
  - *Mitigation:* Benchmark latency, size the migration window, use private connectivity or accelerated transfer where needed, and validate application performance in eastus.
- **Security:** IAM roles, secrets, certificates, and network controls are not visible in the provided scope and may be missed during migration.
  - *Mitigation:* Perform explicit identity and secret inventory, migrate secrets to Key Vault, map access to Entra ID/RBAC, and validate TLS/certificate dependencies.
- **Operations:** Insufficient monitoring and backup setup in Azure before cutover can increase incident and recovery risk.
  - *Mitigation:* Enable Azure Monitor, Log Analytics, alerts, database backups, and restore testing before production switchover.

## Open questions
- What are the backend targets behind each ALB (EC2, ECS, EKS, IP targets, Lambda, or other)?
- What listener ports, host/path routing rules, health probes, and TLS certificates are configured on the public and internal ALBs?
- Which DNS records currently point to the public ALB, and is there any private DNS dependency for the internal ALB?
- What subnets, route tables, NAT gateways, internet gateways, and security groups are attached to the VPC and ALBs?
- Is the Aurora cluster single-writer only, or are there reader endpoints and application read/write split requirements?
- What is the actual Aurora database size, transaction rate, acceptable RPO/RTO, and maximum allowed cutover downtime?
- Are there application features or SQL constructs specific to Aurora MySQL that must be preserved?
- Is private connectivity between AWS and Azure required during migration, and is VPN or ExpressRoute already available?
- What identity model is used by the application today (IAM roles, local secrets, external IdP), and what should map to Entra ID or managed identities?
- Are there compliance, residency, or latency constraints that affect moving the workload from ap-northeast-2 to eastus?
- Should the Azure design use a simple single-VNet deployment for this workload or integrate into an existing hub-spoke landing zone?
- What backup retention, disaster recovery, and secondary-region requirements must be met in Azure?