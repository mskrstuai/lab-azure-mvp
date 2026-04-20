## Summary
Migrate the AWS three-tier web architecture into a single Azure Resource Group named ThreeTierWebArch in eastus, preserving the logical tiers: public web ingress, private app tier, and managed database tier. The closest managed Azure mapping is Application Gateway for the public/internal ALBs, Linux Virtual Machine Scale Sets for the web and app launch-template-based tiers, Azure Virtual Network with six subnets mirroring the AWS layout, NAT Gateway for private egress, Azure Database for PostgreSQL Flexible Server as the managed Aurora-compatible target, Key Vault for secret storage, and Azure Monitor/Log Analytics for observability. Because key AWS details such as CIDRs, listener ports, AMI/OS, autoscaling settings, and Aurora engine are not provided, the Terraform module uses safe defaults and variables so it validates and can be adapted with discovered values before cutover.

## Assessment
Complexity is moderate: the topology is standard three-tier, but successful migration depends on missing configuration details from the launch templates, security groups, ALB listeners/health probes, and Aurora engine/schema. Prerequisites include Azure subscription access, Azure CLI login, Terraform 1.5+, and decisions on connectivity/cutover strategy. To minimize downtime, use parallel deployment in Azure, database replication or logical migration to Azure Database, staged application validation, DNS cutover, and rollback planning. Identity/role mappings from AWS IAM roles should be translated to managed identities and Azure RBAC after application permission requirements are confirmed.

## Migration steps
### 1. Discover
Inventory the AWS launch templates, ALB listeners, target groups, security group rules, subnet CIDRs, route behavior, Aurora engine/version, database size, and application secrets. Confirm whether the two ALBs represent internet-facing web ingress and internal app ingress, and whether EC2 instances are Linux-based and stateless.
- **AWS:** EC2 LaunchTemplate, ELB LoadBalancer, ELB Listener, ELB TargetGroup, EC2 SecurityGroup, EC2 Subnet, EC2 RouteTable, RDS Cluster, Secrets Manager Secret, IAM Role
- **Azure:** Azure VM Scale Sets, Application Gateway, Network Security Groups, Azure Database for PostgreSQL Flexible Server, Key Vault, Managed Identity
- *Notes:* This phase fills the gaps required to finalize ports, health probes, autoscaling, image selection, and DB engine mapping. Export current app configuration and dependency graph before building Azure equivalents.

### 2. Design
Create an Azure landing zone in one resource group with a VNet and six subnets aligned to public, app, and database tiers across two availability zones where possible. Place a public Application Gateway in the public subnet, an internal Application Gateway or internal Load Balancer for app-tier east-west ingress if required, VM Scale Sets for web and app tiers in private subnets, NAT Gateway for outbound internet from private subnets, and a private managed database in dedicated DB subnets. Add NSGs, private DNS, Key Vault, Log Analytics, and monitoring alerts.
- **AWS:** VPC, Subnet, InternetGateway, Natgateway, RouteTable, SecurityGroup, ELB LoadBalancer, LaunchTemplate, RDS Cluster, Secrets Manager
- **Azure:** Virtual Network, Subnets, NAT Gateway, Route Tables, Network Security Groups, Application Gateway, Linux VM Scale Sets, Azure Database for PostgreSQL Flexible Server, Private DNS Zone, Key Vault, Log Analytics Workspace
- *Notes:* Azure does not use an Internet Gateway resource; internet exposure is via public IPs on Application Gateway and outbound via NAT Gateway. If the internal ALB is only app-tier balancing, an internal Application Gateway v2 is a good L7 match.

### 3. Build
Deploy the Azure foundation and platform services with Terraform. Parameterize all unknown values such as CIDRs, ports, VM image, admin credentials, and database settings. Store generated or supplied secrets in Key Vault and enable diagnostics to Log Analytics.
- **AWS:** All in-scope resources
- **Azure:** Resource Group, VNet, Subnets, NSGs, Route Tables, NAT Gateway, Application Gateways, VM Scale Sets, Azure Database, Key Vault, Azure Monitor
- *Notes:* The provided Terraform module is intentionally safe and generic so it validates immediately and can be refined with discovered workload specifics.

### 4. Data Migration
Migrate Aurora to Azure Database using the appropriate engine-compatible path. For Aurora PostgreSQL, use Azure Database for PostgreSQL Flexible Server with pg_dump/pg_restore, DMS, or logical replication. For Aurora MySQL, switch to Azure Database for MySQL Flexible Server and use MySQL replication or dump/restore. Keep source and target in sync until cutover.
- **AWS:** RDS Cluster, RDS DBInstance, Secrets Manager Secret
- **Azure:** Azure Database for PostgreSQL Flexible Server or Azure Database for MySQL Flexible Server, Key Vault
- *Notes:* The Terraform defaults to PostgreSQL Flexible Server because Aurora engine was not provided. Change the module if discovery confirms MySQL.

### 5. Application Migration
Bake or configure Azure-compatible images for the web and app tiers, deploy to VM Scale Sets, attach backend pools, configure health probes and listener rules, and validate private connectivity from web to app and app to database. Replace AWS IAM role assumptions with managed identity and Azure RBAC where the application integrates with Azure services.
- **AWS:** LaunchTemplate, IAM Role, TargetGroup, Listener
- **Azure:** VM Scale Sets, Application Gateway backend pools, Managed Identity, Role Assignments
- *Notes:* If the application is containerized or can be modernized, AKS or Azure Container Apps may be considered later, but VMSS is the closest migration target for EC2 launch templates.

### 6. Validate
Run functional, performance, and security validation: HTTP/HTTPS reachability, health probe success, autoscale behavior, outbound internet from private tiers via NAT, DB connectivity, secret retrieval from Key Vault, and log/metric visibility in Azure Monitor.
- **AWS:** ALB, EC2, RDS, Security Groups
- **Azure:** Application Gateway, VM Scale Sets, Azure Database, NSGs, Azure Monitor
- *Notes:* Validation criteria: public endpoint returns expected app response, internal app path is reachable only from allowed subnets, DB is private-only, and no tier requires direct public IP except ingress.

### 7. Cutover
Lower DNS TTL, perform final database sync, switch application endpoints to Azure, monitor error rates and latency, and keep AWS resources available for rollback during a defined observation window.
- **AWS:** Route53 if used externally, ALB, RDS
- **Azure:** Azure DNS if adopted, Application Gateway public IP/DNS, Azure Database
- *Notes:* Because Route53 resources were not listed, DNS ownership and cutover mechanism must be confirmed. Use blue/green or canary if the application supports it.

### 8. Operate
Enable backup, patching, alerting, and DR controls. Use Azure Backup where applicable for VMs, automated backups for the managed database, zone redundancy where supported, and document runbooks for scaling and failover.
- **AWS:** CloudWatch equivalent not listed but implied, RDS backups
- **Azure:** Azure Monitor, Log Analytics, Backup policies, Database backups, Availability Zones
- *Notes:* Add Defender for Cloud, update management, and policy guardrails in the broader landing zone if this moves beyond a workshop environment.

## Risks
- **Data:** Aurora engine/version is unknown, so the selected Azure managed database may be incorrect or require schema/feature changes.
  - *Mitigation:* Confirm Aurora engine and version first. If PostgreSQL, keep current module. If MySQL, swap to Azure Database for MySQL Flexible Server and retest migration tooling.
- **Networking:** Subnet CIDRs, route intents, and security group rules are not provided, which can break connectivity or create over-permissive defaults.
  - *Mitigation:* Extract actual VPC CIDRs, subnet ranges, and SG rules from AWS and replace Terraform defaults before production deployment. Validate with connectivity tests per tier.
- **Application:** Launch template details such as AMI, bootstrap scripts, instance profile usage, and scaling policies are missing.
  - *Mitigation:* Inspect launch templates and user data, create Azure images or cloud-init equivalents, and define autoscale rules based on observed CPU/request metrics.
- **Security:** Secrets currently in AWS Secrets Manager may be embedded in app config or bootstrap logic and not yet mapped to Key Vault.
  - *Mitigation:* Inventory all secret consumers, migrate secrets to Key Vault, and update applications to use managed identity or secure secret injection.
- **Availability:** Cutover may cause downtime if database synchronization and DNS transition are not staged.
  - *Mitigation:* Use parallel run, continuous replication where possible, low DNS TTL, and a rollback window with AWS left intact until Azure is stable.
- **Operations:** Monitoring and alerting parity with AWS may be incomplete if application logs and metrics are not wired into Azure Monitor.
  - *Mitigation:* Enable diagnostics on all Azure resources, install Azure Monitor Agent on VMs if needed, and define baseline alerts before go-live.

## Open questions
- What are the VPC CIDR and the six subnet CIDR ranges for public, app, and database tiers?
- What OS, AMI, instance type, user data, and autoscaling settings are defined in AppLaunchTemplate and WebLaunchTemplate?
- What listener ports, protocols, TLS certificates, path rules, and health probe paths are configured on the two ALBs and target groups?
- Is the second ALB internal-only for app-tier traffic, and does the application require L7 routing between web and app tiers?
- What exact inbound/outbound rules exist on the five AWS security groups?
- What Aurora engine and version are in use: PostgreSQL or MySQL? What are storage size, HA, backup retention, and performance requirements?
- What credentials and secret names/values from AWS Secrets Manager must be migrated to Key Vault?
- Does the application depend on any AWS services not listed, such as S3, CloudWatch, Route53, SES, SSM, or ECR?
- What DNS zones and certificates are used for the public application, and will Azure DNS and Azure-managed certificates be adopted?
- Is there required hybrid connectivity to on-premises or other clouds, implying VPN or ExpressRoute?
- Are there compliance requirements for encryption keys, private-only access, or regional data residency beyond the eastus preference?
- Should the Azure resource group name remain exactly ThreeTierWebArch, or should environment suffixes be added for dev/test/prod separation?

## Azure Terraform module
Generated 5 file(s). Run `terraform init && terraform plan && terraform apply` from the `terraform/` directory saved alongside this run.

### `providers.tf`
_Terraform and provider requirements for AzureRM and random resources._
```hcl
terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
}
```

### `variables.tf`
_Input variables with safe defaults for networking, compute, ingress, database, and observability._
```hcl
variable "location" {
  description = "Azure region for deployment."
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Azure Resource Group name preserving the AWS logical grouping."
  type        = string
  default     = "ThreeTierWebArch"
}

variable "environment" {
  description = "Environment label used in naming."
  type        = string
  default     = "prod"
}

variable "tags" {
  description = "Tags applied to all supported resources."
  type        = map(string)
  default = {
    workload    = "three-tier-web"
    environment = "prod"
    managed_by  = "terraform"
    source      = "aws-migration"
  }
}

variable "vnet_address_space" {
  description = "Address space for the Azure VNet. Replace with the AWS VPC CIDR during detailed design."
  type        = list(string)
  default     = ["10.50.0.0/16"]
}

variable "subnet_prefixes" {
  description = "Subnet CIDRs for public, app, and database tiers across two zones."
  type = object({
    public_1 = string
    public_2 = string
    app_1    = string
    app_2    = string
    db_1     = string
    db_2     = string
  })
  default = {
    public_1 = "10.50.1.0/24"
    public_2 = "10.50.2.0/24"
    app_1    = "10.50.11.0/24"
    app_2    = "10.50.12.0/24"
    db_1     = "10.50.21.0/24"
    db_2     = "10.50.22.0/24"
  }
}

variable "web_vmss_instances" {
  description = "Initial instance count for the web tier VM scale set."
  type        = number
  default     = 2
}

variable "app_vmss_instances" {
  description = "Initial instance count for the app tier VM scale set."
  type        = number
  default     = 2
}

variable "web_vm_size" {
  description = "VM size for the web tier."
  type        = string
  default     = "Standard_B2s"
}

variable "app_vm_size" {
  description = "VM size for the app tier."
  type        = string
  default     = "Standard_B2s"
}

variable "admin_username" {
  description = "Admin username for Linux VMs."
  type        = string
  default     = "azureuser"
}

variable "admin_ssh_public_key" {
  description = "SSH public key for Linux VMs."
  type        = string
  default     = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7exampleplaceholdergeneratedkeyreplace"
}

variable "web_custom_data" {
  description = "Base64-encoded cloud-init or custom data for the web tier. Leave null if not used."
  type        = string
  default     = null
}

variable "app_custom_data" {
  description = "Base64-encoded cloud-init or custom data for the app tier. Leave null if not used."
  type        = string
  default     = null
}

variable "web_backend_port" {
  description = "Backend port for the web tier."
  type        = number
  default     = 80
}

variable "app_backend_port" {
  description = "Backend port for the app tier."
  type        = number
  default     = 8080
}

variable "public_listener_port" {
  description = "Public listener port on the internet-facing Application Gateway."
  type        = number
  default     = 80
}

variable "internal_listener_port" {
  description = "Internal listener port on the internal Application Gateway."
  type        = number
  default     = 8080
}

variable "db_engine" {
  description = "Managed database engine target. Current module implements postgresql."
  type        = string
  default     = "postgresql"
}

variable "db_sku_name" {
  description = "SKU for Azure Database for PostgreSQL Flexible Server."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "db_storage_mb" {
  description = "Database storage in MB."
  type        = number
  default     = 32768
}

variable "db_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "14"
}

variable "db_admin_username" {
  description = "Database administrator username."
  type        = string
  default     = "pgadmin"
}

variable "db_admin_password" {
  description = "Optional database administrator password. If null, a random password is generated and stored in Key Vault."
  type        = string
  default     = null
  sensitive   = true
}

variable "db_name" {
  description = "Application database name."
  type        = string
  default     = "appdb"
}

variable "key_vault_sku_name" {
  description = "SKU for Key Vault."
  type        = string
  default     = "standard"
}

variable "enable_internal_application_gateway" {
  description = "Whether to deploy an internal Application Gateway for the app tier to mirror the internal ALB pattern."
  type        = bool
  default     = true
}

variable "log_analytics_sku" {
  description = "SKU for Log Analytics Workspace."
  type        = string
  default     = "PerGB2018"
}

variable "log_retention_in_days" {
  description = "Retention for Log Analytics Workspace."
  type        = number
  default     = 30
}
```

### `main.tf`
_Core Azure resources implementing the three-tier migration target with networking, ingress, compute, database, secrets, identity, and monitoring._
```hcl
locals {
  name_prefix = lower(replace("${var.resource_group_name}-${var.environment}", "_", "-"))

  common_tags = merge(var.tags, {
    environment = var.environment
  })
}

# Resource group preserving the AWS logical grouping.
resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.common_tags
}

# Current Azure client configuration for RBAC and Key Vault access policies.
data "azurerm_client_config" "current" {}

# Random suffix to keep globally unique resource names valid.
resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

# Random password for the database if one is not supplied.
resource "random_password" "db_admin" {
  length           = 20
  special          = true
  override_special = "!@#%^*-_"
}

# Virtual network matching the AWS VPC role.
resource "azurerm_virtual_network" "this" {
  name                = "${local.name_prefix}-vnet"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = var.vnet_address_space
  tags                = local.common_tags
}

# Public subnet 1.
resource "azurerm_subnet" "public_1" {
  name                 = "public-subnet-1"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_prefixes.public_1]
}

# Public subnet 2.
resource "azurerm_subnet" "public_2" {
  name                 = "public-subnet-2"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_prefixes.public_2]
}

# Private app subnet 1.
resource "azurerm_subnet" "app_1" {
  name                 = "private-app-subnet-1"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_prefixes.app_1]
}

# Private app subnet 2.
resource "azurerm_subnet" "app_2" {
  name                 = "private-app-subnet-2"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_prefixes.app_2]
}

# Database subnet 1 delegated for PostgreSQL Flexible Server.
resource "azurerm_subnet" "db_1" {
  name                 = "database-subnet-1"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_prefixes.db_1]

  delegation {
    name = "postgres-flex-delegation"

    service_delegation {
      name    = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

# Database subnet 2 reserved to mirror AWS topology and future expansion.
resource "azurerm_subnet" "db_2" {
  name                 = "database-subnet-2"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [var.subnet_prefixes.db_2]
}

# Network security group for the public ingress tier.
resource "azurerm_network_security_group" "public" {
  name                = "${local.name_prefix}-public-nsg"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Allow HTTP to the public Application Gateway.
resource "azurerm_network_security_rule" "public_http_in" {
  name                        = "allow-http-in"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = tostring(var.public_listener_port)
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.public.name
}

# Network security group for the app tier.
resource "azurerm_network_security_group" "app" {
  name                = "${local.name_prefix}-app-nsg"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Allow web tier traffic to the app tier.
resource "azurerm_network_security_rule" "app_from_web" {
  name                        = "allow-web-to-app"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = tostring(var.app_backend_port)
  source_address_prefix       = var.subnet_prefixes.public_1
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.app.name
}

# Allow web tier traffic from second public subnet to the app tier.
resource "azurerm_network_security_rule" "app_from_web_2" {
  name                        = "allow-web2-to-app"
  priority                    = 110
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = tostring(var.app_backend_port)
  source_address_prefix       = var.subnet_prefixes.public_2
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.app.name
}

# Network security group for the database tier.
resource "azurerm_network_security_group" "db" {
  name                = "${local.name_prefix}-db-nsg"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Allow app tier traffic to PostgreSQL.
resource "azurerm_network_security_rule" "db_from_app_1" {
  name                        = "allow-app1-to-db"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "5432"
  source_address_prefix       = var.subnet_prefixes.app_1
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.db.name
}

# Allow app tier traffic from second app subnet to PostgreSQL.
resource "azurerm_network_security_rule" "db_from_app_2" {
  name                        = "allow-app2-to-db"
  priority                    = 110
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "5432"
  source_address_prefix       = var.subnet_prefixes.app_2
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.db.name
}

# Associate the public NSG to public subnet 1.
resource "azurerm_subnet_network_security_group_association" "public_1" {
  subnet_id                 = azurerm_subnet.public_1.id
  network_security_group_id = azurerm_network_security_group.public.id
}

# Associate the public NSG to public subnet 2.
resource "azurerm_subnet_network_security_group_association" "public_2" {
  subnet_id                 = azurerm_subnet.public_2.id
  network_security_group_id = azurerm_network_security_group.public.id
}

# Associate the app NSG to app subnet 1.
resource "azurerm_subnet_network_security_group_association" "app_1" {
  subnet_id                 = azurerm_subnet.app_1.id
  network_security_group_id = azurerm_network_security_group.app.id
}

# Associate the app NSG to app subnet 2.
resource "azurerm_subnet_network_security_group_association" "app_2" {
  subnet_id                 = azurerm_subnet.app_2.id
  network_security_group_id = azurerm_network_security_group.app.id
}

# Associate the database NSG to database subnet 1.
resource "azurerm_subnet_network_security_group_association" "db_1" {
  subnet_id                 = azurerm_subnet.db_1.id
  network_security_group_id = azurerm_network_security_group.db.id
}

# Associate the database NSG to database subnet 2.
resource "azurerm_subnet_network_security_group_association" "db_2" {
  subnet_id                 = azurerm_subnet.db_2.id
  network_security_group_id = azurerm_network_security_group.db.id
}

# Public IP for NAT Gateway outbound internet access.
resource "azurerm_public_ip" "nat" {
  name                = "${local.name_prefix}-nat-pip"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.common_tags
}

# NAT Gateway replacing the AWS NAT Gateway for private subnet egress.
resource "azurerm_nat_gateway" "this" {
  name                = "${local.name_prefix}-natgw"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku_name            = "Standard"
  tags                = local.common_tags
}

# Associate the NAT public IP.
resource "azurerm_nat_gateway_public_ip_association" "this" {
  nat_gateway_id       = azurerm_nat_gateway.this.id
  public_ip_address_id = azurerm_public_ip.nat.id
}

# Attach NAT Gateway to app subnet 1.
resource "azurerm_subnet_nat_gateway_association" "app_1" {
  subnet_id      = azurerm_subnet.app_1.id
  nat_gateway_id = azurerm_nat_gateway.this.id
}

# Attach NAT Gateway to app subnet 2.
resource "azurerm_subnet_nat_gateway_association" "app_2" {
  subnet_id      = azurerm_subnet.app_2.id
  nat_gateway_id = azurerm_nat_gateway.this.id
}

# Route table for public subnets.
resource "azurerm_route_table" "public" {
  name                = "${local.name_prefix}-public-rt"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Route table for app subnets.
resource "azurerm_route_table" "app" {
  name                = "${local.name_prefix}-app-rt"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Route table for database subnets.
resource "azurerm_route_table" "db" {
  name                = "${local.name_prefix}-db-rt"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Associate public route table to public subnet 1.
resource "azurerm_subnet_route_table_association" "public_1" {
  subnet_id      = azurerm_subnet.public_1.id
  route_table_id = azurerm_route_table.public.id
}

# Associate public route table to public subnet 2.
resource "azurerm_subnet_route_table_association" "public_2" {
  subnet_id      = azurerm_subnet.public_2.id
  route_table_id = azurerm_route_table.public.id
}

# Associate app route table to app subnet 1.
resource "azurerm_subnet_route_table_association" "app_1" {
  subnet_id      = azurerm_subnet.app_1.id
  route_table_id = azurerm_route_table.app.id
}

# Associate app route table to app subnet 2.
resource "azurerm_subnet_route_table_association" "app_2" {
  subnet_id      = azurerm_subnet.app_2.id
  route_table_id = azurerm_route_table.app.id
}

# Associate database route table to database subnet 1.
resource "azurerm_subnet_route_table_association" "db_1" {
  subnet_id      = azurerm_subnet.db_1.id
  route_table_id = azurerm_route_table.db.id
}

# Associate database route table to database subnet 2.
resource "azurerm_subnet_route_table_association" "db_2" {
  subnet_id      = azurerm_subnet.db_2.id
  route_table_id = azurerm_route_table.db.id
}

# Public IP for the internet-facing Application Gateway.
resource "azurerm_public_ip" "public_agw" {
  name                = "${local.name_prefix}-public-agw-pip"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.common_tags
}

# Public Application Gateway replacing the internet-facing ALB.
resource "azurerm_application_gateway" "public" {
  name                = "${local.name_prefix}-public-agw"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags

  sku {
    name     = "Standard_v2"
    tier     = "Standard_v2"
    capacity = 2
  }

  gateway_ip_configuration {
    name      = "public-gateway-ip-config"
    subnet_id = azurerm_subnet.public_1.id
  }

  frontend_port {
    name = "frontend-port-http"
    port = var.public_listener_port
  }

  frontend_ip_configuration {
    name                 = "frontend-public"
    public_ip_address_id = azurerm_public_ip.public_agw.id
  }

  backend_address_pool {
    name = "web-backend-pool"
  }

  backend_http_settings {
    name                  = "web-http-settings"
    cookie_based_affinity = "Disabled"
    path                  = "/"
    port                  = var.web_backend_port
    protocol              = "Http"
    request_timeout       = 30
  }

  http_listener {
    name                           = "public-http-listener"
    frontend_ip_configuration_name = "frontend-public"
    frontend_port_name             = "frontend-port-http"
    protocol                       = "Http"
  }

  request_routing_rule {
    name                       = "public-routing-rule"
    rule_type                  = "Basic"
    http_listener_name         = "public-http-listener"
    backend_address_pool_name  = "web-backend-pool"
    backend_http_settings_name = "web-http-settings"
    priority                   = 100
  }
}

# Private IP for the internal Application Gateway.
resource "azurerm_private_dns_zone" "postgres" {
  name                = "${local.name_prefix}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Link the PostgreSQL private DNS zone to the VNet.
resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "${local.name_prefix}-postgres-link"
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  resource_group_name   = azurerm_resource_group.this.name
  virtual_network_id    = azurerm_virtual_network.this.id
  tags                  = local.common_tags
}

# Internal Application Gateway replacing the internal ALB pattern.
resource "azurerm_application_gateway" "internal" {
  count               = var.enable_internal_application_gateway ? 1 : 0
  name                = "${local.name_prefix}-internal-agw"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags

  sku {
    name     = "Standard_v2"
    tier     = "Standard_v2"
    capacity = 2
  }

  gateway_ip_configuration {
    name      = "internal-gateway-ip-config"
    subnet_id = azurerm_subnet.public_2.id
  }

  frontend_port {
    name = "frontend-port-internal"
    port = var.internal_listener_port
  }

  frontend_ip_configuration {
    name                          = "frontend-internal"
    private_ip_address_allocation = "Dynamic"
    subnet_id                     = azurerm_subnet.public_2.id
  }

  backend_address_pool {
    name = "app-backend-pool"
  }

  backend_http_settings {
    name                  = "app-http-settings"
    cookie_based_affinity = "Disabled"
    path                  = "/"
    port                  = var.app_backend_port
    protocol              = "Http"
    request_timeout       = 30
  }

  http_listener {
    name                           = "internal-http-listener"
    frontend_ip_configuration_name = "frontend-internal"
    frontend_port_name             = "frontend-port-internal"
    protocol                       = "Http"
  }

  request_routing_rule {
    name                       = "internal-routing-rule"
    rule_type                  = "Basic"
    http_listener_name         = "internal-http-listener"
    backend_address_pool_name  = "app-backend-pool"
    backend_http_settings_name = "app-http-settings"
    priority                   = 100
  }
}

# Log Analytics Workspace for Azure Monitor.
resource "azurerm_log_analytics_workspace" "this" {
  name                = "${local.name_prefix}-law"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = var.log_analytics_sku
  retention_in_days   = var.log_retention_in_days
  tags                = local.common_tags
}

# User-assigned managed identity for the web tier.
resource "azurerm_user_assigned_identity" "web" {
  name                = "${local.name_prefix}-web-mi"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# User-assigned managed identity for the app tier.
resource "azurerm_user_assigned_identity" "app" {
  name                = "${local.name_prefix}-app-mi"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Key Vault for migrated secrets.
resource "azurerm_key_vault" "this" {
  name                        = substr(replace("${local.name_prefix}${random_string.suffix.result}kv", "-", ""), 0, 24)
  location                    = azurerm_resource_group.this.location
  resource_group_name         = azurerm_resource_group.this.name
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = var.key_vault_sku_name
  purge_protection_enabled    = false
  soft_delete_retention_days  = 7
  enabled_for_disk_encryption = true
  tags                        = local.common_tags

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = [
      "Get",
      "List",
      "Set",
      "Delete",
      "Purge",
      "Recover"
    ]
  }
}

# Store the database admin password in Key Vault.
resource "azurerm_key_vault_secret" "db_admin_password" {
  name         = "db-admin-password"
  value        = coalesce(var.db_admin_password, random_password.db_admin.result)
  key_vault_id = azurerm_key_vault.this.id
  tags         = local.common_tags
}

# PostgreSQL Flexible Server as the managed Aurora-compatible target.
resource "azurerm_postgresql_flexible_server" "this" {
  name                   = substr(replace("${local.name_prefix}-${random_string.suffix.result}-pg", "_", "-"), 0, 63)
  resource_group_name    = azurerm_resource_group.this.name
  location               = azurerm_resource_group.this.location
  version                = var.db_version
  delegated_subnet_id    = azurerm_subnet.db_1.id
  private_dns_zone_id    = azurerm_private_dns_zone.postgres.id
  administrator_login    = var.db_admin_username
  administrator_password = coalesce(var.db_admin_password, random_password.db_admin.result)
  storage_mb             = var.db_storage_mb
  sku_name               = var.db_sku_name
  backup_retention_days  = 7
  zone                   = "1"
  tags                   = local.common_tags

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

# Application database on the PostgreSQL server.
resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = var.db_name
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "UTF8"
}

# Web tier VM Scale Set replacing the web launch template and target group.
resource "azurerm_linux_virtual_machine_scale_set" "web" {
  name                = "${local.name_prefix}-web-vmss"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = var.web_vm_size
  instances           = var.web_vmss_instances
  admin_username      = var.admin_username
  custom_data         = var.web_custom_data
  tags                = local.common_tags

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  network_interface {
    name    = "webnic"
    primary = true

    ip_configuration {
      name      = "internal"
      primary   = true
      subnet_id = azurerm_subnet.app_1.id
      application_gateway_backend_address_pool_ids = [
        azurerm_application_gateway.public.backend_address_pool[0].id
      ]
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.web.id]
  }
}

# App tier VM Scale Set replacing the app launch template and target group.
resource "azurerm_linux_virtual_machine_scale_set" "app" {
  name                = "${local.name_prefix}-app-vmss"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = var.app_vm_size
  instances           = var.app_vmss_instances
  admin_username      = var.admin_username
  custom_data         = var.app_custom_data
  tags                = local.common_tags

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  network_interface {
    name    = "appnic"
    primary = true

    ip_configuration {
      name      = "internal"
      primary   = true
      subnet_id = azurerm_subnet.app_2.id
      application_gateway_backend_address_pool_ids = var.enable_internal_application_gateway ? [
        azurerm_application_gateway.internal[0].backend_address_pool[0].id
      ] : []
    }
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }
}

# Diagnostic settings for the public Application Gateway.
resource "azurerm_monitor_diagnostic_setting" "public_agw" {
  name                       = "public-agw-diagnostics"
  target_resource_id         = azurerm_application_gateway.public.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id

  enabled_log {
    category = "ApplicationGatewayAccessLog"
  }

  enabled_log {
    category = "ApplicationGatewayPerformanceLog"
  }

  enabled_log {
    category = "ApplicationGatewayFirewallLog"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

# Diagnostic settings for the PostgreSQL Flexible Server.
resource "azurerm_monitor_diagnostic_setting" "postgres" {
  name                       = "postgres-diagnostics"
  target_resource_id         = azurerm_postgresql_flexible_server.this.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}
```

### `outputs.tf`
_Useful outputs for resource IDs, ingress endpoints, database endpoint, and operational integration._
```hcl
output "resource_group_name" {
  description = "Name of the Azure Resource Group."
  value       = azurerm_resource_group.this.name
}

output "vnet_id" {
  description = "ID of the Azure Virtual Network."
  value       = azurerm_virtual_network.this.id
}

output "public_application_gateway_public_ip" {
  description = "Public IP address of the internet-facing Application Gateway."
  value       = azurerm_public_ip.public_agw.ip_address
}

output "internal_application_gateway_private_ip" {
  description = "Private IP address of the internal Application Gateway if enabled."
  value       = var.enable_internal_application_gateway ? azurerm_application_gateway.internal[0].frontend_ip_configuration[0].private_ip_address : null
}

output "postgresql_fqdn" {
  description = "Private FQDN of the PostgreSQL Flexible Server."
  value       = azurerm_postgresql_flexible_server.this.fqdn
}

output "postgresql_database_name" {
  description = "Application database name."
  value       = azurerm_postgresql_flexible_server_database.app.name
}

output "key_vault_name" {
  description = "Key Vault name storing migrated secrets."
  value       = azurerm_key_vault.this.name
}

output "log_analytics_workspace_id" {
  description = "Log Analytics Workspace ID for Azure Monitor integration."
  value       = azurerm_log_analytics_workspace.this.id
}

output "web_vmss_name" {
  description = "Web tier VM Scale Set name."
  value       = azurerm_linux_virtual_machine_scale_set.web.name
}

output "app_vmss_name" {
  description = "App tier VM Scale Set name."
  value       = azurerm_linux_virtual_machine_scale_set.app.name
}
```

### `README.md`
_Short usage guide for deploying and adapting the Azure migration module._
```markdown
This Terraform module deploys an Azure target for the AWS ThreeTierWebArch workload.
It creates one Resource Group, a six-subnet VNet, NSGs, route tables, NAT Gateway, public/internal Application Gateways, web/app Linux VM Scale Sets, PostgreSQL Flexible Server, Key Vault, and Log Analytics.

Prerequisites: Azure CLI, Terraform >= 1.5, and an authenticated session with `az login`.
Set the target subscription if needed with `az account set --subscription <subscription-id>`.

Run:
terraform init
terraform plan -out tfplan
terraform apply tfplan

Before production use, replace default CIDRs, SSH key, listener ports, health settings, VM bootstrap data, and database engine/settings with discovered AWS values.
Post-deploy, load application code/config onto the VM Scale Sets, migrate the database, validate connectivity tier by tier, then perform DNS cutover.
```