## Summary
Migrate the AWS three-tier web architecture into a single Azure Resource Group named ThreeTierWebArch in eastus using managed Azure equivalents: Virtual Network with public/app/db subnets, Application Gateway for the public and internal ALB patterns, Linux VM Scale Sets for web and app tiers based on the two Launch Templates, Azure Database for PostgreSQL Flexible Server as the closest managed relational target for the Aurora cluster, Key Vault for secret storage, NAT Gateway for private egress, NSGs for Security Groups, route tables for subnet routing, and Azure Monitor/Log Analytics for observability. The design preserves the logical three-tier separation and supports phased cutover to minimize downtime.

## Assessment
Complexity is moderate: the AWS inventory clearly shows a classic three-tier pattern, but key implementation details are missing, including VPC/subnet CIDRs, listener ports, target group health probes, EC2 AMIs/user data, Aurora engine type/version, security group rules, and secret contents. The Terraform module below provides a safe, deployable Azure landing zone with defaults and variables for the missing values. Prerequisites: Azure subscription access, Azure CLI login, Terraform 1.5+, and decisions on database engine compatibility, DNS/cutover, and application image/bootstrap details.

## Migration steps
### 1. Discover
Confirm source configuration details that are not present in the inventory: subnet CIDRs, ALB listener ports and TLS settings, target group health checks, Launch Template OS/bootstrap, Aurora engine/version, security group ingress/egress rules, and application dependencies on Secrets Manager and IAM roles.
- **AWS:** VPC, Subnet, RouteTable, InternetGateway, NatGateway, SecurityGroup, LaunchTemplate, ALB Listener, ALB LoadBalancer, TargetGroup, RDS Cluster, DBInstance, Secrets Manager, IAM Role
- **Azure:** Azure Resource Group, Virtual Network, Subnets, Route Tables, NSGs, Application Gateway, VM Scale Sets, Azure Database for PostgreSQL Flexible Server, Key Vault, Managed Identity
- *Notes:* This phase determines whether Aurora maps to PostgreSQL or MySQL Flexible Server and whether the internal ALB should become an internal Application Gateway or internal Load Balancer.

### 2. Design
Create an Azure landing zone in eastus with one resource group, one VNet, six subnets aligned to public/app/db tiers across two zones, NSGs per tier, NAT Gateway for private outbound, public Application Gateway for internet ingress, internal Application Gateway for app-tier ingress, VM Scale Sets for web and app tiers, private DNS for database resolution, Key Vault for secrets, and Log Analytics/Azure Monitor for diagnostics.
- **AWS:** VPC, Subnet, RouteTable, InternetGateway, NatGateway, SecurityGroup, LaunchTemplate, ALB
- **Azure:** azurerm_virtual_network, azurerm_subnet, azurerm_route_table, azurerm_nat_gateway, azurerm_network_security_group, azurerm_application_gateway, azurerm_linux_virtual_machine_scale_set, azurerm_private_dns_zone, azurerm_log_analytics_workspace
- *Notes:* Use zones 1 and 2 in eastus where supported to mirror the two-subnet-per-tier pattern and improve availability.

### 3. Build
Deploy the Azure infrastructure with Terraform, parameterizing all unknown values. Bootstrap VMSS instances with cloud-init placeholders or custom image references, create Key Vault secrets for database admin credentials, and enable diagnostics on core resources.
- **AWS:** LaunchTemplate, IAM Role, Secrets Manager
- **Azure:** VM Scale Sets, System-assigned Managed Identity, Key Vault, Role Assignments, Azure Monitor
- *Notes:* Managed identities replace many IAM role use cases for Azure-native access. Application-specific RBAC should be added after dependency review.

### 4. Data Migration
Provision the managed database target and migrate Aurora data using Azure Database Migration Service or native dump/replication tooling, depending on engine compatibility and downtime tolerance.
- **AWS:** RDS Cluster, DBInstance, RDS Subnet Group, Secrets Manager
- **Azure:** Azure Database for PostgreSQL Flexible Server, Azure Database Migration Service, Key Vault
- *Notes:* For minimal downtime, prefer continuous replication or logical replication where supported, then perform a short final cutover window.

### 5. Application Migration
Deploy web and app tier software to the VM Scale Sets, configure internal routing from public Application Gateway to web tier and from internal Application Gateway to app tier, and update application configuration to use Azure database FQDN and Key Vault-backed secrets.
- **AWS:** ALB, TargetGroup, LaunchTemplate, IAM Role, Secrets Manager
- **Azure:** Application Gateway, VM Scale Sets, Managed Identity, Key Vault
- *Notes:* If the app currently relies on instance profiles, replace with managed identity and Azure RBAC or Key Vault access policies.

### 6. Validate
Run functional, network, and resilience tests: internet access to public endpoint, web-to-app connectivity, app-to-db private connectivity, outbound internet from private subnets via NAT, health probes, autoscaling behavior, and log/metric collection.
- **AWS:** ALB Listener, TargetGroup, SecurityGroup, RouteTable, NatGateway, RDS
- **Azure:** Application Gateway probes, NSGs, Route Tables, NAT Gateway, Azure Monitor, Database connectivity
- *Notes:* Validation should include failover across zones and rollback readiness before DNS cutover.

### 7. Cutover
Lower DNS TTL, freeze writes if needed, complete final database sync, switch DNS or frontend endpoint to Azure, monitor errors and latency, and retain AWS resources during a rollback window.
- **AWS:** ALB, RDS, Secrets Manager
- **Azure:** Application Gateway public IP/DNS, Azure DNS or external DNS, Azure Monitor
- *Notes:* Use staged traffic shifting if possible. Keep AWS environment intact until acceptance criteria are met.

## Risks
- **Data:** Aurora engine/version is not specified, so the chosen Azure managed database may be incompatible or require schema/application changes.
  - *Mitigation:* Confirm whether Aurora is PostgreSQL- or MySQL-compatible and set the Terraform variable accordingly; use Azure DMS assessment before migration.
- **Networking:** Subnet CIDRs, route rules, and security group rules are missing, which can lead to overlapping address spaces or incorrect access control in Azure.
  - *Mitigation:* Collect exact CIDRs and SG rules before production deployment; current Terraform uses safe defaults and explicit variables for override.
- **Application:** Launch Templates do not include AMI, user data, package dependencies, or health check endpoints in the provided scope.
  - *Mitigation:* Extract Launch Template details and convert bootstrap logic into cloud-init or custom images; validate health probes before cutover.
- **Security:** Secrets Manager contents and IAM role permissions are unknown, so applications may fail after migration if secrets or permissions are incomplete.
  - *Mitigation:* Inventory all secrets and IAM permissions; map to Key Vault secrets and managed identity/RBAC assignments.
- **Availability:** A direct cutover without replication or staged validation could increase downtime.
  - *Mitigation:* Use Azure DMS or native replication, pre-stage infrastructure, test in parallel, and perform a short final sync during cutover.
- **Operations:** Monitoring and backup settings may differ from AWS defaults, creating blind spots or recovery gaps.
  - *Mitigation:* Enable Azure Monitor diagnostics, Log Analytics, database backups, and define RPO/RTO with geo-redundancy decisions before go-live.

## Open questions
- What are the VPC CIDR and the six subnet CIDRs for PublicSubnet1/2, PrivateAppSubnet1/2, and DatabaseSubnet1/2?
- What are the listener ports, protocols, certificates, and health probe paths for the two ALBs/listeners/target groups?
- Should the internal ALB map to an internal Application Gateway or an internal Azure Load Balancer?
- What OS/image, instance type, user data, and scaling settings are defined in the two Launch Templates?
- What are the exact inbound/outbound rules for the five Security Groups?
- Is the Aurora cluster PostgreSQL-compatible or MySQL-compatible, and what engine version is in use?
- What database size, HA requirement, backup retention, and private access requirements are needed?
- What secrets are stored in Secrets Manager, and which applications consume them?
- What permissions do the two IAM roles grant, and which should be replaced by Azure managed identity and RBAC?
- Will DNS be hosted in Azure DNS, or will an external DNS provider be used for cutover?
- Is there any hybrid connectivity requirement to on-premises or other clouds via VPN/ExpressRoute?
- Are there compliance requirements for encryption keys, private endpoints, or geo-redundant backup/DR?

## Azure Terraform module
Generated 5 file(s). Run `terraform init && terraform plan && terraform apply` from the `terraform/` directory saved alongside this run.

### `providers.tf`
_Terraform and provider requirements for AzureRM and Random._
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
_Input variables with safe defaults for networking, compute, ingress, database, storage, and monitoring._
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
    source      = "aws-migration"
  }
}

variable "vnet_address_space" {
  description = "Address space for the Azure VNet. Override to match non-overlapping enterprise IP plan."
  type        = list(string)
  default     = ["10.50.0.0/16"]
}

variable "subnet_prefixes" {
  description = "CIDR prefixes for the six subnets aligned to public, app, and database tiers across two zones."
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

variable "web_vmss_sku" {
  description = "SKU for the web tier VM Scale Set."
  type        = string
  default     = "Standard_B2s"
}

variable "app_vmss_sku" {
  description = "SKU for the app tier VM Scale Set."
  type        = string
  default     = "Standard_B2s"
}

variable "web_instance_count" {
  description = "Initial instance count for the web tier VM Scale Set."
  type        = number
  default     = 2
}

variable "app_instance_count" {
  description = "Initial instance count for the app tier VM Scale Set."
  type        = number
  default     = 2
}

variable "admin_username" {
  description = "Admin username for Linux VMs."
  type        = string
  default     = "azureuser"
}

variable "admin_ssh_public_key" {
  description = "SSH public key for Linux VM access."
  type        = string
  default     = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7exampleplaceholderreplacewithrealkey"
}

variable "web_custom_data" {
  description = "Base64-encoded cloud-init for the web tier. Leave null if not used."
  type        = string
  default     = null
}

variable "app_custom_data" {
  description = "Base64-encoded cloud-init for the app tier. Leave null if not used."
  type        = string
  default     = null
}

variable "web_health_probe_path" {
  description = "Health probe path for the public Application Gateway to the web tier."
  type        = string
  default     = "/"
}

variable "app_health_probe_path" {
  description = "Health probe path for the internal Application Gateway to the app tier."
  type        = string
  default     = "/"
}

variable "public_listener_port" {
  description = "Frontend listener port for the public Application Gateway."
  type        = number
  default     = 80
}

variable "internal_listener_port" {
  description = "Frontend listener port for the internal Application Gateway."
  type        = number
  default     = 80
}

variable "web_backend_port" {
  description = "Backend port on the web tier instances."
  type        = number
  default     = 80
}

variable "app_backend_port" {
  description = "Backend port on the app tier instances."
  type        = number
  default     = 8080
}

variable "database_engine" {
  description = "Managed database engine target. Supported by this module: postgresql or mysql."
  type        = string
  default     = "postgresql"

  validation {
    condition     = contains(["postgresql", "mysql"], var.database_engine)
    error_message = "database_engine must be either 'postgresql' or 'mysql'."
  }
}

variable "db_sku_name" {
  description = "SKU name for the managed database server."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "db_storage_mb" {
  description = "Allocated storage in MB for the managed database server."
  type        = number
  default     = 32768
}

variable "db_version_postgresql" {
  description = "PostgreSQL version if database_engine is postgresql."
  type        = string
  default     = "14"
}

variable "db_version_mysql" {
  description = "MySQL version if database_engine is mysql."
  type        = string
  default     = "8.0.21"
}

variable "db_admin_username" {
  description = "Administrator username for the managed database."
  type        = string
  default     = "dbadmin"
}

variable "db_backup_retention_days" {
  description = "Backup retention for the managed database."
  type        = number
  default     = 7
}

variable "db_zone" {
  description = "Availability zone for the primary managed database server."
  type        = string
  default     = "1"
}

variable "enable_geo_redundant_backup" {
  description = "Enable geo-redundant backup where supported."
  type        = bool
  default     = false
}

variable "storage_account_tier" {
  description = "Storage account tier."
  type        = string
  default     = "Standard"
}

variable "storage_account_replication_type" {
  description = "Storage account replication type."
  type        = string
  default     = "LRS"
}

variable "log_analytics_sku" {
  description = "SKU for Log Analytics workspace."
  type        = string
  default     = "PerGB2018"
}

variable "log_retention_in_days" {
  description = "Retention in days for Log Analytics workspace."
  type        = number
  default     = 30
}
```

### `main.tf`
_Core Azure infrastructure implementing the three-tier migration target with networking, ingress, compute, database, secrets, storage, and monitoring._
```hcl
locals {
  name_prefix = lower(replace("${var.resource_group_name}-${var.environment}", "_", "-"))

  common_tags = merge(var.tags, {
    environment = var.environment
  })

  subnets = {
    public_1 = {
      name             = "public-1"
      prefix           = var.subnet_prefixes.public_1
      nsg_key          = "public"
      route_table_key  = "public"
      delegation       = false
    }
    public_2 = {
      name             = "public-2"
      prefix           = var.subnet_prefixes.public_2
      nsg_key          = "public"
      route_table_key  = "public"
      delegation       = false
    }
    app_1 = {
      name             = "app-1"
      prefix           = var.subnet_prefixes.app_1
      nsg_key          = "app"
      route_table_key  = "private"
      delegation       = false
    }
    app_2 = {
      name             = "app-2"
      prefix           = var.subnet_prefixes.app_2
      nsg_key          = "app"
      route_table_key  = "private"
      delegation       = false
    }
    db_1 = {
      name             = "db-1"
      prefix           = var.subnet_prefixes.db_1
      nsg_key          = "db"
      route_table_key  = "private"
      delegation       = true
    }
    db_2 = {
      name             = "db-2"
      prefix           = var.subnet_prefixes.db_2
      nsg_key          = "db"
      route_table_key  = "private"
      delegation       = false
    }
  }

  nsgs = {
    public = "public"
    app    = "app"
    db     = "db"
  }
}

# Resource group preserving the AWS logical grouping.
resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.common_tags
}

# Random suffix for globally unique resource names.
resource "random_string" "suffix" {
  length  = 6
  upper   = false
  special = false
}

# Random password for the managed database administrator.
resource "random_password" "db_admin" {
  length           = 20
  special          = true
  override_special = "!@#%^*-_"
}

# Virtual network for the three-tier architecture.
resource "azurerm_virtual_network" "this" {
  name                = "${local.name_prefix}-vnet"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = var.vnet_address_space
  tags                = local.common_tags
}

# Public IP for the NAT Gateway.
resource "azurerm_public_ip" "nat" {
  name                = "${local.name_prefix}-nat-pip"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = ["1"]
  tags                = local.common_tags
}

# NAT Gateway for private subnet outbound access.
resource "azurerm_nat_gateway" "this" {
  name                    = "${local.name_prefix}-natgw"
  location                = azurerm_resource_group.this.location
  resource_group_name     = azurerm_resource_group.this.name
  sku_name                = "Standard"
  idle_timeout_in_minutes = 10
  zones                   = ["1"]
  tags                    = local.common_tags
}

# Associate the public IP to the NAT Gateway.
resource "azurerm_nat_gateway_public_ip_association" "this" {
  nat_gateway_id       = azurerm_nat_gateway.this.id
  public_ip_address_id = azurerm_public_ip.nat.id
}

# Route table for public subnets.
resource "azurerm_route_table" "public" {
  name                = "${local.name_prefix}-rt-public"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Route table for private subnets.
resource "azurerm_route_table" "private" {
  name                = "${local.name_prefix}-rt-private"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Network security groups aligned to public, app, and db tiers.
resource "azurerm_network_security_group" "this" {
  for_each            = local.nsgs
  name                = "${local.name_prefix}-nsg-${each.value}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Public tier allow HTTP inbound.
resource "azurerm_network_security_rule" "public_http_in" {
  name                        = "allow-http-in"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = tostring(var.public_listener_port)
  source_address_prefix       = "Internet"
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.this["public"].name
}

# Public tier allow HTTPS inbound.
resource "azurerm_network_security_rule" "public_https_in" {
  name                        = "allow-https-in"
  priority                    = 110
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "443"
  source_address_prefix       = "Internet"
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.this["public"].name
}

# App tier allow traffic from the VNet to the application backend port.
resource "azurerm_network_security_rule" "app_in" {
  name                        = "allow-app-in"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = tostring(var.app_backend_port)
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.this["app"].name
}

# Database tier allow PostgreSQL inbound from the VNet.
resource "azurerm_network_security_rule" "db_postgresql_in" {
  count                       = var.database_engine == "postgresql" ? 1 : 0
  name                        = "allow-postgresql-in"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "5432"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.this["db"].name
}

# Database tier allow MySQL inbound from the VNet.
resource "azurerm_network_security_rule" "db_mysql_in" {
  count                       = var.database_engine == "mysql" ? 1 : 0
  name                        = "allow-mysql-in"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "3306"
  source_address_prefix       = "VirtualNetwork"
  destination_address_prefix  = "*"
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.this["db"].name
}

# Subnets for public, app, and database tiers.
resource "azurerm_subnet" "this" {
  for_each             = local.subnets
  name                 = each.value.name
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = [each.value.prefix]

  dynamic "delegation" {
    for_each = each.value.delegation && var.database_engine == "postgresql" ? [1] : []
    content {
      name = "fs"

      service_delegation {
        name    = "Microsoft.DBforPostgreSQL/flexibleServers"
        actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
      }
    }
  }

  dynamic "delegation" {
    for_each = each.value.delegation && var.database_engine == "mysql" ? [1] : []
    content {
      name = "fs"

      service_delegation {
        name    = "Microsoft.DBforMySQL/flexibleServers"
        actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
      }
    }
  }
}

# Associate NSGs to subnets.
resource "azurerm_subnet_network_security_group_association" "this" {
  for_each                  = local.subnets
  subnet_id                 = azurerm_subnet.this[each.key].id
  network_security_group_id = azurerm_network_security_group.this[each.value.nsg_key].id
}

# Associate route tables to subnets.
resource "azurerm_subnet_route_table_association" "this" {
  for_each       = local.subnets
  subnet_id      = azurerm_subnet.this[each.key].id
  route_table_id = each.value.route_table_key == "public" ? azurerm_route_table.public.id : azurerm_route_table.private.id
}

# Associate NAT Gateway to private app subnet 1.
resource "azurerm_subnet_nat_gateway_association" "app_1" {
  subnet_id      = azurerm_subnet.this["app_1"].id
  nat_gateway_id = azurerm_nat_gateway.this.id
}

# Associate NAT Gateway to private app subnet 2.
resource "azurerm_subnet_nat_gateway_association" "app_2" {
  subnet_id      = azurerm_subnet.this["app_2"].id
  nat_gateway_id = azurerm_nat_gateway.this.id
}

# Associate NAT Gateway to database subnet 2 for controlled outbound if needed.
resource "azurerm_subnet_nat_gateway_association" "db_2" {
  subnet_id      = azurerm_subnet.this["db_2"].id
  nat_gateway_id = azurerm_nat_gateway.this.id
}

# Log Analytics workspace for Azure Monitor.
resource "azurerm_log_analytics_workspace" "this" {
  name                = "${local.name_prefix}-law"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = var.log_analytics_sku
  retention_in_days   = var.log_retention_in_days
  tags                = local.common_tags
}

# Storage account for application assets and diagnostics.
resource "azurerm_storage_account" "this" {
  name                     = substr(replace("${local.name_prefix}${random_string.suffix.result}", "-", ""), 0, 24)
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = var.storage_account_tier
  account_replication_type = var.storage_account_replication_type
  min_tls_version          = "TLS1_2"
  tags                     = local.common_tags
}

# Private container for application data or migration artifacts.
resource "azurerm_storage_container" "app" {
  name                  = "appdata"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

# Key Vault for migrated secrets.
resource "azurerm_key_vault" "this" {
  name                       = substr(replace("${local.name_prefix}-kv-${random_string.suffix.result}", "-", ""), 0, 24)
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  tags                       = local.common_tags
}

# Current client config for Key Vault access policy.
data "azurerm_client_config" "current" {}

# Access policy for the current deployment identity.
resource "azurerm_key_vault_access_policy" "current" {
  key_vault_id = azurerm_key_vault.this.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = [
    "Get",
    "Set",
    "List",
    "Delete",
    "Purge",
    "Recover"
  ]
}

# Store the generated database password in Key Vault.
resource "azurerm_key_vault_secret" "db_password" {
  name         = "db-admin-password"
  value        = random_password.db_admin.result
  key_vault_id = azurerm_key_vault.this.id
  tags         = local.common_tags

  depends_on = [azurerm_key_vault_access_policy.current]
}

# Public IP for the internet-facing Application Gateway.
resource "azurerm_public_ip" "public_agw" {
  name                = "${local.name_prefix}-agw-public-pip"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = ["1", "2"]
  tags                = local.common_tags
}

# Public Application Gateway replacing the internet-facing ALB.
resource "azurerm_application_gateway" "public" {
  name                = "${local.name_prefix}-agw-public"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags

  sku {
    name     = "Standard_v2"
    tier     = "Standard_v2"
    capacity = 2
  }

  gateway_ip_configuration {
    name      = "gateway-ip-config"
    subnet_id = azurerm_subnet.this["public_1"].id
  }

  frontend_port {
    name = "frontend-port-http"
    port = var.public_listener_port
  }

  frontend_ip_configuration {
    name                 = "frontend-ip-public"
    public_ip_address_id = azurerm_public_ip.public_agw.id
  }

  backend_address_pool {
    name         = "web-backend-pool"
    ip_addresses = []
  }

  backend_http_settings {
    name                  = "web-http-settings"
    cookie_based_affinity = "Disabled"
    path                  = "/"
    port                  = var.web_backend_port
    protocol              = "Http"
    request_timeout       = 30
    probe_name            = "web-probe"
  }

  http_listener {
    name                           = "public-http-listener"
    frontend_ip_configuration_name = "frontend-ip-public"
    frontend_port_name             = "frontend-port-http"
    protocol                       = "Http"
  }

  probe {
    name                                      = "web-probe"
    protocol                                  = "Http"
    path                                      = var.web_health_probe_path
    interval                                  = 30
    timeout                                   = 30
    unhealthy_threshold                       = 3
    pick_host_name_from_backend_http_settings = false
    match {
      status_code = ["200-399"]
    }
  }

  request_routing_rule {
    name                       = "public-http-rule"
    rule_type                  = "Basic"
    http_listener_name         = "public-http-listener"
    backend_address_pool_name  = "web-backend-pool"
    backend_http_settings_name = "web-http-settings"
    priority                   = 100
  }
}

# Internal Application Gateway replacing the internal ALB.
resource "azurerm_application_gateway" "internal" {
  name                = "${local.name_prefix}-agw-internal"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags

  sku {
    name     = "Standard_v2"
    tier     = "Standard_v2"
    capacity = 2
  }

  gateway_ip_configuration {
    name      = "gateway-ip-config"
    subnet_id = azurerm_subnet.this["public_2"].id
  }

  frontend_port {
    name = "frontend-port-http"
    port = var.internal_listener_port
  }

  frontend_ip_configuration {
    name                          = "frontend-ip-private"
    private_ip_address            = cidrhost(var.subnet_prefixes.public_2, 10)
    private_ip_address_allocation = "Static"
    subnet_id                     = azurerm_subnet.this["public_2"].id
  }

  backend_address_pool {
    name         = "app-backend-pool"
    ip_addresses = []
  }

  backend_http_settings {
    name                  = "app-http-settings"
    cookie_based_affinity = "Disabled"
    path                  = "/"
    port                  = var.app_backend_port
    protocol              = "Http"
    request_timeout       = 30
    probe_name            = "app-probe"
  }

  http_listener {
    name                           = "internal-http-listener"
    frontend_ip_configuration_name = "frontend-ip-private"
    frontend_port_name             = "frontend-port-http"
    protocol                       = "Http"
  }

  probe {
    name                                      = "app-probe"
    protocol                                  = "Http"
    path                                      = var.app_health_probe_path
    interval                                  = 30
    timeout                                   = 30
    unhealthy_threshold                       = 3
    pick_host_name_from_backend_http_settings = false
    match {
      status_code = ["200-399"]
    }
  }

  request_routing_rule {
    name                       = "internal-http-rule"
    rule_type                  = "Basic"
    http_listener_name         = "internal-http-listener"
    backend_address_pool_name  = "app-backend-pool"
    backend_http_settings_name = "app-http-settings"
    priority                   = 100
  }
}

# Public load balancer for the web VM Scale Set.
resource "azurerm_lb" "web" {
  name                = "${local.name_prefix}-lb-web"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Standard"
  tags                = local.common_tags

  frontend_ip_configuration {
    name                 = "frontend"
    public_ip_address_id = azurerm_public_ip.public_agw.id
  }
}

# Backend pool for the web VM Scale Set.
resource "azurerm_lb_backend_address_pool" "web" {
  loadbalancer_id = azurerm_lb.web.id
  name            = "web-backend-pool"
}

# Health probe for the web VM Scale Set.
resource "azurerm_lb_probe" "web" {
  loadbalancer_id = azurerm_lb.web.id
  name            = "web-probe"
  port            = var.web_backend_port
  protocol        = "Tcp"
}

# Load balancing rule for the web VM Scale Set.
resource "azurerm_lb_rule" "web" {
  loadbalancer_id                = azurerm_lb.web.id
  name                           = "web-rule"
  protocol                       = "Tcp"
  frontend_port                  = var.web_backend_port
  backend_port                   = var.web_backend_port
  frontend_ip_configuration_name = "frontend"
  backend_address_pool_ids       = [azurerm_lb_backend_address_pool.web.id]
  probe_id                       = azurerm_lb_probe.web.id
}

# Internal load balancer for the app VM Scale Set.
resource "azurerm_lb" "app" {
  name                = "${local.name_prefix}-lb-app"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Standard"
  tags                = local.common_tags

  frontend_ip_configuration {
    name                          = "frontend"
    subnet_id                     = azurerm_subnet.this["app_1"].id
    private_ip_address_allocation = "Dynamic"
  }
}

# Backend pool for the app VM Scale Set.
resource "azurerm_lb_backend_address_pool" "app" {
  loadbalancer_id = azurerm_lb.app.id
  name            = "app-backend-pool"
}

# Health probe for the app VM Scale Set.
resource "azurerm_lb_probe" "app" {
  loadbalancer_id = azurerm_lb.app.id
  name            = "app-probe"
  port            = var.app_backend_port
  protocol        = "Tcp"
}

# Load balancing rule for the app VM Scale Set.
resource "azurerm_lb_rule" "app" {
  loadbalancer_id                = azurerm_lb.app.id
  name                           = "app-rule"
  protocol                       = "Tcp"
  frontend_port                  = var.app_backend_port
  backend_port                   = var.app_backend_port
  frontend_ip_configuration_name = "frontend"
  backend_address_pool_ids       = [azurerm_lb_backend_address_pool.app.id]
  probe_id                       = azurerm_lb_probe.app.id
}

# Web tier VM Scale Set replacing the web Launch Template and target group.
resource "azurerm_linux_virtual_machine_scale_set" "web" {
  name                            = "${local.name_prefix}-vmss-web"
  resource_group_name             = azurerm_resource_group.this.name
  location                        = azurerm_resource_group.this.location
  sku                             = var.web_vmss_sku
  instances                       = var.web_instance_count
  admin_username                  = var.admin_username
  disable_password_authentication = true
  zones                           = ["1", "2"]
  overprovision                   = false
  custom_data                     = var.web_custom_data
  tags                            = local.common_tags

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  network_interface {
    name    = "web-nic"
    primary = true

    ip_configuration {
      name                                   = "internal"
      primary                                = true
      subnet_id                              = azurerm_subnet.this["app_1"].id
      load_balancer_backend_address_pool_ids = [azurerm_lb_backend_address_pool.web.id]
    }
  }

  identity {
    type = "SystemAssigned"
  }

  boot_diagnostics {
    storage_account_uri = azurerm_storage_account.this.primary_blob_endpoint
  }
}

# App tier VM Scale Set replacing the app Launch Template and target group.
resource "azurerm_linux_virtual_machine_scale_set" "app" {
  name                            = "${local.name_prefix}-vmss-app"
  resource_group_name             = azurerm_resource_group.this.name
  location                        = azurerm_resource_group.this.location
  sku                             = var.app_vmss_sku
  instances                       = var.app_instance_count
  admin_username                  = var.admin_username
  disable_password_authentication = true
  zones                           = ["1", "2"]
  overprovision                   = false
  custom_data                     = var.app_custom_data
  tags                            = local.common_tags

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  admin_ssh_key {
    username   = var.admin_username
    public_key = var.admin_ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  network_interface {
    name    = "app-nic"
    primary = true

    ip_configuration {
      name                                   = "internal"
      primary                                = true
      subnet_id                              = azurerm_subnet.this["app_2"].id
      load_balancer_backend_address_pool_ids = [azurerm_lb_backend_address_pool.app.id]
    }
  }

  identity {
    type = "SystemAssigned"
  }

  boot_diagnostics {
    storage_account_uri = azurerm_storage_account.this.primary_blob_endpoint
  }
}

# Private DNS zone for PostgreSQL Flexible Server.
resource "azurerm_private_dns_zone" "postgresql" {
  count               = var.database_engine == "postgresql" ? 1 : 0
  name                = "${local.name_prefix}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Link VNet to PostgreSQL private DNS zone.
resource "azurerm_private_dns_zone_virtual_network_link" "postgresql" {
  count                 = var.database_engine == "postgresql" ? 1 : 0
  name                  = "${local.name_prefix}-postgres-link"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.postgresql[0].name
  virtual_network_id    = azurerm_virtual_network.this.id
  tags                  = local.common_tags
}

# PostgreSQL Flexible Server as the default Aurora target.
resource "azurerm_postgresql_flexible_server" "this" {
  count                          = var.database_engine == "postgresql" ? 1 : 0
  name                           = "${substr(replace(local.name_prefix, "-", ""), 0, 20)}pg${random_string.suffix.result}"
  resource_group_name            = azurerm_resource_group.this.name
  location                       = azurerm_resource_group.this.location
  version                        = var.db_version_postgresql
  delegated_subnet_id            = azurerm_subnet.this["db_1"].id
  private_dns_zone_id            = azurerm_private_dns_zone.postgresql[0].id
  administrator_login            = var.db_admin_username
  administrator_password         = random_password.db_admin.result
  zone                           = var.db_zone
  storage_mb                     = var.db_storage_mb
  sku_name                       = var.db_sku_name
  backup_retention_days          = var.db_backup_retention_days
  geo_redundant_backup_enabled   = var.enable_geo_redundant_backup
  public_network_access_enabled  = false
  tags                           = local.common_tags

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgresql]
}

# Private DNS zone for MySQL Flexible Server.
resource "azurerm_private_dns_zone" "mysql" {
  count               = var.database_engine == "mysql" ? 1 : 0
  name                = "${local.name_prefix}.mysql.database.azure.com"
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.common_tags
}

# Link VNet to MySQL private DNS zone.
resource "azurerm_private_dns_zone_virtual_network_link" "mysql" {
  count                 = var.database_engine == "mysql" ? 1 : 0
  name                  = "${local.name_prefix}-mysql-link"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.mysql[0].name
  virtual_network_id    = azurerm_virtual_network.this.id
  tags                  = local.common_tags
}

# MySQL Flexible Server as an alternative Aurora target.
resource "azurerm_mysql_flexible_server" "this" {
  count                          = var.database_engine == "mysql" ? 1 : 0
  name                           = "${substr(replace(local.name_prefix, "-", ""), 0, 20)}my${random_string.suffix.result}"
  resource_group_name            = azurerm_resource_group.this.name
  location                       = azurerm_resource_group.this.location
  version                        = var.db_version_mysql
  delegated_subnet_id            = azurerm_subnet.this["db_1"].id
  private_dns_zone_id            = azurerm_private_dns_zone.mysql[0].id
  administrator_login            = var.db_admin_username
  administrator_password         = random_password.db_admin.result
  zone                           = var.db_zone
  storage_mb                     = var.db_storage_mb
  sku_name                       = var.db_sku_name
  backup_retention_days          = var.db_backup_retention_days
  geo_redundant_backup_enabled   = var.enable_geo_redundant_backup
  public_network_access_enabled  = false
  tags                           = local.common_tags

  depends_on = [azurerm_private_dns_zone_virtual_network_link.mysql]
}
```

### `outputs.tf`
_Useful outputs for resource IDs, ingress endpoints, database endpoint, storage, and secret references._
```hcl
output "resource_group_name" {
  description = "Name of the Azure Resource Group."
  value       = azurerm_resource_group.this.name
}

output "vnet_id" {
  description = "ID of the Azure Virtual Network."
  value       = azurerm_virtual_network.this.id
}

output "subnet_ids" {
  description = "IDs of the created subnets."
  value = {
    for k, v in azurerm_subnet.this : k => v.id
  }
}

output "public_application_gateway_public_ip" {
  description = "Public IP address of the internet-facing Application Gateway."
  value       = azurerm_public_ip.public_agw.ip_address
}

output "public_application_gateway_id" {
  description = "ID of the internet-facing Application Gateway."
  value       = azurerm_application_gateway.public.id
}

output "internal_application_gateway_private_ip" {
  description = "Private IP of the internal Application Gateway."
  value       = cidrhost(var.subnet_prefixes.public_2, 10)
}

output "web_vmss_id" {
  description = "ID of the web tier VM Scale Set."
  value       = azurerm_linux_virtual_machine_scale_set.web.id
}

output "app_vmss_id" {
  description = "ID of the app tier VM Scale Set."
  value       = azurerm_linux_virtual_machine_scale_set.app.id
}

output "database_fqdn" {
  description = "FQDN of the managed database server."
  value       = var.database_engine == "postgresql" ? azurerm_postgresql_flexible_server.this[0].fqdn : azurerm_mysql_flexible_server.this[0].fqdn
}

output "storage_account_name" {
  description = "Name of the storage account."
  value       = azurerm_storage_account.this.name
}

output "key_vault_name" {
  description = "Name of the Key Vault storing migrated secrets."
  value       = azurerm_key_vault.this.name
}

output "db_admin_password_secret_id" {
  description = "Key Vault secret ID for the database admin password."
  value       = azurerm_key_vault_secret.db_password.id
  sensitive   = true
}
```

### `README.md`
_Short usage guide for deploying and completing the migration._
```markdown
This module deploys an Azure target landing zone for the AWS ThreeTierWebArch migration.
It creates one Resource Group, VNet with public/app/db subnets, NSGs, route tables, NAT Gateway, public and internal Application Gateways, web/app Linux VM Scale Sets, managed database, Key Vault, Storage Account, and Log Analytics.

Prerequisites: Azure CLI installed and authenticated with `az login`, Terraform >= 1.5.0, and permission to create networking, compute, database, and Key Vault resources.

Run:
terraform init
terraform plan -out tfplan
terraform apply tfplan

Override defaults in a .tfvars file for subnet CIDRs, SSH key, listener ports, VM sizes, and database engine/version.
After deployment, load application code/bootstrap into the VM Scale Sets, migrate the Aurora database with Azure DMS or native tooling, update secrets in Key Vault, and cut over DNS to the public Application Gateway IP.
Validate web, app, and database connectivity before production cutover.
```