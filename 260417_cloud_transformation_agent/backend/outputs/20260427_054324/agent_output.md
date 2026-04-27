## Summary
Migrate the AWS stack to Azure managed services in eastus using a spoke VNet pattern: Application Load Balancer maps to Azure Application Gateway, ECS Fargate services map to Azure Container Apps in a managed environment, RDS PostgreSQL maps to Azure Database for PostgreSQL Flexible Server, S3 static assets map to Azure Storage Account with blob containers, ElastiCache Redis maps to Azure Cache for Redis, Secrets Manager maps to Azure Key Vault, and CloudWatch maps to Log Analytics plus Azure Monitor diagnostics. The Terraform module deploys a secure baseline with private networking for data services, managed identities, centralized logging, and ingress suitable for low-downtime cutover.

## Assessment
Moderate complexity. Main dependencies are target hub-spoke connectivity design, DNS/certificate strategy for ingress, database migration approach, and container image registry/source. The provided Terraform uses safe defaults and managed services, but final production rollout needs confirmation of CIDRs, private DNS integration with the hub, TLS certificates, and application container images/environment variables.

## Migration steps
### 1. Discover
Inventory current ALB listeners/rules, ECS services/task definitions, PostgreSQL version/size/extensions, Redis usage, S3 buckets/static website behavior, Secrets Manager secrets, and CloudWatch dashboards/alarms/log retention. Capture DNS names, certificates, scaling thresholds, and network dependencies.
- **AWS:** Application Load Balancer, ECS Fargate, RDS PostgreSQL, S3, ElastiCache Redis, Secrets Manager, CloudWatch
- **Azure:** Application Gateway, Azure Container Apps, Azure Database for PostgreSQL Flexible Server, Storage Account, Azure Cache for Redis, Key Vault, Log Analytics Workspace / Azure Monitor
- *Notes:* Do not begin cutover until app config, image sources, and database compatibility are validated. Confirm whether static assets require CDN/Front Door beyond current scope.

### 2. Design
Design a spoke VNet in eastus aligned to the hub-spoke model with dedicated subnets for Application Gateway, Container Apps infrastructure, private endpoints, database, and cache. Use private access for PostgreSQL, Redis, and Key Vault. Plan DNS resolution to the hub and certificate management for HTTPS ingress.
- **AWS:** VPC/Subnets, Security Groups, ALB, RDS, ElastiCache, Secrets Manager
- **Azure:** Virtual Network/Subnets, Network Security Groups, Application Gateway WAF_v2, Private DNS Zones, PostgreSQL Flexible Server, Azure Cache for Redis, Key Vault
- *Notes:* If the hub is pre-existing, peer this spoke and link private DNS zones as needed. CIDRs are parameterized because they were not provided.

### 3. Build
Deploy the Azure landing components with Terraform: resource group, VNet/subnets, NSGs, Log Analytics, Key Vault, Storage Account/containers, PostgreSQL Flexible Server, Redis, Container Apps environment and apps, Application Gateway, and monitoring diagnostics.
- **AWS:** CloudWatch, Secrets Manager, S3, RDS, ElastiCache, ECS Fargate, ALB
- **Azure:** Azure Monitor, Key Vault, Storage Account, PostgreSQL Flexible Server, Azure Cache for Redis, Container Apps, Application Gateway
- *Notes:* The module uses managed identity for Container Apps and stores generated DB admin password in Key Vault. Application images are variable-driven.

### 4. Migrate Data
Migrate PostgreSQL using Azure Database Migration Service or native logical replication/pg_dump depending on size and downtime tolerance. Sync S3 static assets to Blob Storage with AzCopy or Storage Mover. Recreate Redis data only if persistence/use case requires it; otherwise warm cache after cutover. Replicate secrets into Key Vault.
- **AWS:** RDS PostgreSQL, S3, ElastiCache Redis, Secrets Manager
- **Azure:** PostgreSQL Flexible Server, Blob Storage, Azure Cache for Redis, Key Vault
- *Notes:* For minimal downtime, use continuous replication for PostgreSQL until final cutover. Validate extensions, parameter settings, and connection strings.

### 5. Cutover
Deploy application containers to Container Apps, validate through Application Gateway, switch application secrets/config to Azure endpoints, then update DNS to Azure ingress. Keep AWS stack in read-only or standby mode during observation window.
- **AWS:** ALB, ECS Fargate, Route53 if used externally
- **Azure:** Application Gateway, Container Apps, Azure DNS or external DNS
- *Notes:* Use low TTL before cutover. Blue/green or canary is possible by adding additional backend routing rules if needed.

### 6. Validate
Run smoke, performance, and failover tests; verify logs, metrics, alerts, backups, and private connectivity. Confirm static asset delivery, DB performance, Redis connectivity, and secret retrieval via managed identity.
- **AWS:** CloudWatch, ALB, ECS, RDS, S3, ElastiCache
- **Azure:** Azure Monitor, Application Gateway, Container Apps, PostgreSQL Flexible Server, Storage Account, Azure Cache for Redis
- *Notes:* Validation criteria: HTTPS 200 responses, successful app-to-DB and app-to-Redis connections, expected log ingestion, backup policies enabled, and no public exposure for private services.

## Risks
- **Data:** PostgreSQL version/extensions or parameter incompatibilities may block migration or cause runtime issues.
  - *Mitigation:* Assess engine version, extensions, collations, and parameter groups early; test restore/replication into Azure PostgreSQL Flexible Server before cutover.
- **Networking:** Hub-spoke DNS and private endpoint/private service resolution may fail if private DNS zones and peering are not integrated correctly.
  - *Mitigation:* Confirm hub DNS architecture, zone linking, and peering/UDR requirements before deployment; validate name resolution from application subnet.
- **Security:** Ingress TLS and secret access may be misconfigured, exposing services or causing outages.
  - *Mitigation:* Use Key Vault, managed identities, HTTPS listeners, and least-privilege RBAC; confirm certificate source and access policies before production.
- **Operations:** Container Apps may differ from ECS Fargate in scaling, networking, and revision behavior, affecting application runtime.
  - *Mitigation:* Load test Container Apps with production-like settings, tune min/max replicas and probes, and validate environment variables and secret references.
- **Availability:** Cutover may incur downtime if database sync lag or DNS propagation is not controlled.
  - *Mitigation:* Use continuous DB replication where possible, reduce DNS TTL ahead of time, and execute a rehearsed rollback plan.

## Open questions
- What are the required VNet and subnet CIDRs for the spoke, and will it be peered to an existing hub VNet?
- Should ingress use Azure Application Gateway only, or also Azure Front Door/CDN for global/static asset acceleration?
- What container images, ports, CPU/memory, and autoscaling settings are required for each ECS service?
- How many ECS services need to be migrated, and do they require internal-only or public ingress?
- What PostgreSQL version, storage size, HA requirement, backup retention, and maintenance window are needed?
- Is Redis required in a private network only, and what SKU/capacity is needed?
- What S3 buckets/containers are required, and should static assets be publicly accessible or private behind the application?
- What secrets must be created in Key Vault beyond the generated database password?
- What TLS certificate source should be used for Application Gateway listeners: uploaded PFX, Key Vault certificate, or existing enterprise PKI?
- What alerts, log retention, and diagnostic settings are required to match current CloudWatch behavior?
- Is Azure Container Registry available, or should images be pulled from another registry?
- Are there compliance requirements for customer-managed keys, private endpoints for Storage/Key Vault, or zone-redundancy?

## Azure Terraform module
Generated 5 file(s). Run `terraform init && terraform plan && terraform apply` from the `terraform/` directory saved alongside this run.

### `providers.tf`
_Terraform and provider requirements for AzureRM and random._
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
_Input variables with safe defaults for networking, compute, database, cache, storage, and monitoring._
```hcl
variable "location" {
  description = "Azure region for deployment."
  type        = string
  default     = "eastus"
}

variable "resource_group_name" {
  description = "Name of the resource group to create."
  type        = string
  default     = "rg-aws-migration-eastus"
}

variable "environment" {
  description = "Environment name used in resource naming."
  type        = string
  default     = "prod"
}

variable "tags" {
  description = "Tags applied to supported resources."
  type        = map(string)
  default = {
    environment = "prod"
    workload    = "aws-migration"
    managed_by  = "terraform"
  }
}

variable "vnet_address_space" {
  description = "Address space for the spoke virtual network."
  type        = list(string)
  default     = ["10.50.0.0/16"]
}

variable "subnet_prefixes" {
  description = "Subnet CIDRs for application gateway, container apps, private endpoints, database, and cache."
  type = object({
    appgw          = string
    container_apps = string
    private_endpoints = string
    database       = string
    cache          = string
  })
  default = {
    appgw             = "10.50.0.0/24"
    container_apps    = "10.50.1.0/23"
    private_endpoints = "10.50.3.0/24"
    database          = "10.50.4.0/24"
    cache             = "10.50.5.0/24"
  }
}

variable "container_apps" {
  description = "Container Apps to deploy, representing ECS Fargate services."
  type = map(object({
    image          = string
    target_port    = number
    cpu            = number
    memory         = string
    min_replicas   = number
    max_replicas   = number
    external_ingress = bool
  }))
  default = {
    app = {
      image            = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      target_port      = 80
      cpu              = 0.5
      memory           = "1Gi"
      min_replicas     = 1
      max_replicas     = 3
      external_ingress = true
    }
  }
}

variable "postgresql_version" {
  description = "Azure Database for PostgreSQL Flexible Server version."
  type        = string
  default     = "15"
}

variable "db_sku_name" {
  description = "SKU for PostgreSQL Flexible Server."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "db_storage_mb" {
  description = "Allocated PostgreSQL storage in MB."
  type        = number
  default     = 32768
}

variable "db_backup_retention_days" {
  description = "Backup retention for PostgreSQL Flexible Server."
  type        = number
  default     = 7
}

variable "db_admin_username" {
  description = "Administrator username for PostgreSQL Flexible Server."
  type        = string
  default     = "pgadmin"
}

variable "redis_capacity" {
  description = "Azure Cache for Redis capacity."
  type        = number
  default     = 1
}

variable "redis_family" {
  description = "Azure Cache for Redis family."
  type        = string
  default     = "C"
}

variable "redis_sku_name" {
  description = "Azure Cache for Redis SKU."
  type        = string
  default     = "Standard"
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

variable "storage_containers" {
  description = "Blob containers to create for static assets."
  type        = list(string)
  default     = ["static-assets"]
}

variable "log_analytics_retention_in_days" {
  description = "Retention for Log Analytics workspace."
  type        = number
  default     = 30
}

variable "application_gateway_sku_name" {
  description = "Application Gateway SKU name."
  type        = string
  default     = "WAF_v2"
}

variable "application_gateway_sku_tier" {
  description = "Application Gateway SKU tier."
  type        = string
  default     = "WAF_v2"
}

variable "application_gateway_capacity" {
  description = "Application Gateway instance capacity."
  type        = number
  default     = 2
}

variable "application_gateway_frontend_port" {
  description = "Frontend port for Application Gateway listener."
  type        = number
  default     = 80
}

variable "key_vault_sku_name" {
  description = "Key Vault SKU name."
  type        = string
  default     = "standard"
}
```

### `main.tf`
_Core Azure resources implementing the AWS-to-Azure migration target architecture._
```hcl
data "azurerm_client_config" "current" {}

locals {
  name_prefix          = substr(replace("${var.environment}${var.location}", "-", ""), 0, 12)
  storage_account_name = lower(substr("st${replace(var.environment, "-", "")}${replace(var.location, "-", "")}", 0, 24))
  common_tags          = merge(var.tags, { environment = var.environment })
  first_container_app  = keys(var.container_apps)[0]
}

# Resource group for all migrated services.
resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.common_tags
}

# Log Analytics workspace for Azure Monitor and Container Apps logs.
resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-${var.environment}-${var.location}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_analytics_retention_in_days
  tags                = local.common_tags
}

# Spoke virtual network aligned to hub-spoke networking.
resource "azurerm_virtual_network" "main" {
  name                = "vnet-${var.environment}-${var.location}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = var.vnet_address_space
  tags                = local.common_tags
}

# Network security group for the application gateway subnet.
resource "azurerm_network_security_group" "appgw" {
  name                = "nsg-appgw-${var.environment}-${var.location}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Network security group for the container apps subnet.
resource "azurerm_network_security_group" "container_apps" {
  name                = "nsg-ca-${var.environment}-${var.location}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Network security group for the database subnet.
resource "azurerm_network_security_group" "database" {
  name                = "nsg-db-${var.environment}-${var.location}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Network security group for the cache subnet.
resource "azurerm_network_security_group" "cache" {
  name                = "nsg-cache-${var.environment}-${var.location}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Application Gateway subnet.
resource "azurerm_subnet" "appgw" {
  name                 = "snet-appgw"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.appgw]
}

# Container Apps infrastructure subnet.
resource "azurerm_subnet" "container_apps" {
  name                 = "snet-container-apps"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.container_apps]

  delegation {
    name = "containerapps-delegation"

    service_delegation {
      name = "Microsoft.App/environments"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action"
      ]
    }
  }
}

# Private endpoints subnet.
resource "azurerm_subnet" "private_endpoints" {
  name                 = "snet-private-endpoints"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.private_endpoints]

  private_endpoint_network_policies_enabled = false
}

# PostgreSQL delegated subnet.
resource "azurerm_subnet" "database" {
  name                 = "snet-database"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.database]

  delegation {
    name = "postgres-flex-delegation"

    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action"
      ]
    }
  }
}

# Redis subnet.
resource "azurerm_subnet" "cache" {
  name                 = "snet-cache"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.cache]
}

# Associate NSG to Application Gateway subnet.
resource "azurerm_subnet_network_security_group_association" "appgw" {
  subnet_id                 = azurerm_subnet.appgw.id
  network_security_group_id = azurerm_network_security_group.appgw.id
}

# Associate NSG to Container Apps subnet.
resource "azurerm_subnet_network_security_group_association" "container_apps" {
  subnet_id                 = azurerm_subnet.container_apps.id
  network_security_group_id = azurerm_network_security_group.container_apps.id
}

# Associate NSG to database subnet.
resource "azurerm_subnet_network_security_group_association" "database" {
  subnet_id                 = azurerm_subnet.database.id
  network_security_group_id = azurerm_network_security_group.database.id
}

# Associate NSG to cache subnet.
resource "azurerm_subnet_network_security_group_association" "cache" {
  subnet_id                 = azurerm_subnet.cache.id
  network_security_group_id = azurerm_network_security_group.cache.id
}

# Public IP for Application Gateway ingress.
resource "azurerm_public_ip" "appgw" {
  name                = "pip-appgw-${var.environment}-${var.location}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.common_tags
}

# Key Vault for migrated secrets.
resource "azurerm_key_vault" "main" {
  name                       = substr("kv-${var.environment}-${var.location}-${local.name_prefix}", 0, 24)
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = var.key_vault_sku_name
  purge_protection_enabled   = false
  soft_delete_retention_days = 7
  tags                       = local.common_tags
}

# Access policy for the current deployment identity.
resource "azurerm_key_vault_access_policy" "current" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = [
    "Get",
    "List",
    "Set",
    "Delete",
    "Purge",
    "Recover"
  ]
}

# Random password for PostgreSQL admin.
resource "random_password" "db_admin" {
  length           = 24
  special          = true
  override_special = "!@#%^*-_"
}

# Store PostgreSQL admin password in Key Vault.
resource "azurerm_key_vault_secret" "db_admin_password" {
  name         = "postgres-admin-password"
  value        = random_password.db_admin.result
  key_vault_id = azurerm_key_vault.main.id

  depends_on = [azurerm_key_vault_access_policy.current]
}

# Private DNS zone for PostgreSQL Flexible Server.
resource "azurerm_private_dns_zone" "postgres" {
  name                = "${var.environment}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Link PostgreSQL private DNS zone to the spoke VNet.
resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "postgres-link-${var.environment}"
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  resource_group_name   = azurerm_resource_group.main.name
  virtual_network_id    = azurerm_virtual_network.main.id
  tags                  = local.common_tags
}

# PostgreSQL Flexible Server replacing RDS PostgreSQL.
resource "azurerm_postgresql_flexible_server" "main" {
  name                   = "psql-${var.environment}-${local.name_prefix}"
  resource_group_name    = azurerm_resource_group.main.name
  location               = azurerm_resource_group.main.location
  version                = var.postgresql_version
  delegated_subnet_id    = azurerm_subnet.database.id
  private_dns_zone_id    = azurerm_private_dns_zone.postgres.id
  administrator_login    = var.db_admin_username
  administrator_password = random_password.db_admin.result
  zone                   = "1"
  storage_mb             = var.db_storage_mb
  sku_name               = var.db_sku_name
  backup_retention_days  = var.db_backup_retention_days
  tags                   = local.common_tags

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

# Azure Cache for Redis replacing ElastiCache Redis.
resource "azurerm_redis_cache" "main" {
  name                = "redis-${var.environment}-${local.name_prefix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  capacity            = var.redis_capacity
  family              = var.redis_family
  sku_name            = var.redis_sku_name
  minimum_tls_version = "1.2"
  non_ssl_port_enabled = false
  tags                = local.common_tags
}

# Storage account replacing S3 for static assets.
resource "azurerm_storage_account" "main" {
  name                            = local.storage_account_name
  resource_group_name             = azurerm_resource_group.main.name
  location                        = azurerm_resource_group.main.location
  account_tier                    = var.storage_account_tier
  account_replication_type        = var.storage_account_replication_type
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = local.common_tags
}

# Blob containers for static assets.
resource "azurerm_storage_container" "containers" {
  for_each              = toset(var.storage_containers)
  name                  = each.value
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

# Managed environment for Container Apps replacing ECS Fargate cluster/services.
resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${var.environment}-${var.location}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  infrastructure_subnet_id   = azurerm_subnet.container_apps.id
  tags                       = local.common_tags
}

# User-assigned managed identity for application access to Azure services.
resource "azurerm_user_assigned_identity" "container_apps" {
  name                = "id-ca-${var.environment}-${var.location}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Grant Container Apps identity read access to Key Vault secrets.
resource "azurerm_key_vault_access_policy" "container_apps" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_user_assigned_identity.container_apps.principal_id

  secret_permissions = [
    "Get",
    "List"
  ]
}

# Container Apps representing ECS Fargate services.
resource "azurerm_container_app" "apps" {
  for_each                     = var.container_apps
  name                         = "ca-${each.key}-${var.environment}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = local.common_tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.container_apps.id]
  }

  ingress {
    external_enabled = each.value.external_ingress
    target_port      = each.value.target_port
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = each.value.min_replicas
    max_replicas = each.value.max_replicas

    container {
      name   = each.key
      image  = each.value.image
      cpu    = each.value.cpu
      memory = each.value.memory

      env {
        name  = "POSTGRES_HOST"
        value = azurerm_postgresql_flexible_server.main.fqdn
      }

      env {
        name  = "POSTGRES_USER"
        value = "${var.db_admin_username}"
      }

      env {
        name        = "POSTGRES_PASSWORD"
        secret_name = "postgres-admin-password"
      }

      env {
        name  = "REDIS_HOST"
        value = azurerm_redis_cache.main.hostname
      }

      env {
        name  = "STORAGE_ACCOUNT_NAME"
        value = azurerm_storage_account.main.name
      }
    }
  }

  secret {
    name  = "postgres-admin-password"
    value = random_password.db_admin.result
  }

  depends_on = [azurerm_key_vault_access_policy.container_apps]
}

# Application Gateway replacing AWS ALB.
resource "azurerm_application_gateway" "main" {
  name                = "agw-${var.environment}-${var.location}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags

  sku {
    name     = var.application_gateway_sku_name
    tier     = var.application_gateway_sku_tier
    capacity = var.application_gateway_capacity
  }

  gateway_ip_configuration {
    name      = "appgw-ip-config"
    subnet_id = azurerm_subnet.appgw.id
  }

  frontend_port {
    name = "frontend-port"
    port = var.application_gateway_frontend_port
  }

  frontend_ip_configuration {
    name                 = "frontend-ip"
    public_ip_address_id = azurerm_public_ip.appgw.id
  }

  backend_address_pool {
    name  = "backend-pool"
    fqdns = [azurerm_container_app.apps[local.first_container_app].latest_revision_fqdn]
  }

  backend_http_settings {
    name                                = "backend-http-settings"
    cookie_based_affinity               = "Disabled"
    port                                = 80
    protocol                            = "Http"
    request_timeout                     = 30
    pick_host_name_from_backend_address = true
  }

  http_listener {
    name                           = "http-listener"
    frontend_ip_configuration_name = "frontend-ip"
    frontend_port_name             = "frontend-port"
    protocol                       = "Http"
  }

  request_routing_rule {
    name                       = "routing-rule"
    rule_type                  = "Basic"
    http_listener_name         = "http-listener"
    backend_address_pool_name  = "backend-pool"
    backend_http_settings_name = "backend-http-settings"
    priority                   = 100
  }

  depends_on = [azurerm_container_app.apps]
}

# Diagnostic settings for Application Gateway to Log Analytics.
resource "azurerm_monitor_diagnostic_setting" "appgw" {
  name                       = "diag-appgw"
  target_resource_id         = azurerm_application_gateway.main.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

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

# Diagnostic settings for PostgreSQL to Log Analytics.
resource "azurerm_monitor_diagnostic_setting" "postgres" {
  name                       = "diag-postgres"
  target_resource_id         = azurerm_postgresql_flexible_server.main.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "PostgreSQLLogs"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

# Diagnostic settings for Key Vault to Log Analytics.
resource "azurerm_monitor_diagnostic_setting" "key_vault" {
  name                       = "diag-kv"
  target_resource_id         = azurerm_key_vault.main.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "AuditEvent"
  }

  metric {
    category = "AllMetrics"
    enabled  = true
  }
}

# Diagnostic settings for Storage Account to Log Analytics.
resource "azurerm_monitor_diagnostic_setting" "storage" {
  name                       = "diag-storage"
  target_resource_id         = "${azurerm_storage_account.main.id}/blobServices/default"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  enabled_log {
    category = "StorageRead"
  }

  enabled_log {
    category = "StorageWrite"
  }

  enabled_log {
    category = "StorageDelete"
  }

  metric {
    category = "Transaction"
    enabled  = true
  }
}
```

### `outputs.tf`
_Useful outputs for ingress, application endpoints, database, cache, storage, and secrets._
```hcl
output "resource_group_name" {
  description = "Resource group name."
  value       = azurerm_resource_group.main.name
}

output "vnet_id" {
  description = "Virtual network ID."
  value       = azurerm_virtual_network.main.id
}

output "application_gateway_public_ip" {
  description = "Public IP address of the Application Gateway."
  value       = azurerm_public_ip.appgw.ip_address
}

output "application_gateway_frontend_fqdn" {
  description = "Frontend FQDN if DNS label is later assigned to the public IP."
  value       = azurerm_public_ip.appgw.fqdn
}

output "container_app_fqdns" {
  description = "FQDNs of deployed Container Apps."
  value       = { for k, v in azurerm_container_app.apps : k => v.latest_revision_fqdn }
}

output "postgresql_fqdn" {
  description = "PostgreSQL Flexible Server FQDN."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "redis_hostname" {
  description = "Azure Cache for Redis hostname."
  value       = azurerm_redis_cache.main.hostname
}

output "storage_account_name" {
  description = "Storage account name for static assets."
  value       = azurerm_storage_account.main.name
}

output "storage_primary_blob_endpoint" {
  description = "Primary blob endpoint."
  value       = azurerm_storage_account.main.primary_blob_endpoint
}

output "key_vault_name" {
  description = "Key Vault name."
  value       = azurerm_key_vault.main.name
}

output "db_admin_password_secret_id" {
  description = "Key Vault secret ID containing the PostgreSQL admin password."
  value       = azurerm_key_vault_secret.db_admin_password.id
  sensitive   = true
}
```

### `README.md`
_Short usage guide for deploying and completing the migration._
```markdown
This Terraform module deploys an Azure target platform for migrating AWS ALB, ECS Fargate, RDS PostgreSQL, S3, ElastiCache Redis, Secrets Manager, and CloudWatch.
It creates a resource group, spoke VNet/subnets, Application Gateway, Container Apps environment/apps, PostgreSQL Flexible Server, Redis, Storage Account, Key Vault, and Log Analytics diagnostics.
Prerequisite: install Terraform and Azure CLI, then authenticate with `az login` and select the correct subscription.
Review and customize variables in `variables.tf` or a `.tfvars` file, especially container images, CIDRs, database sizing, and ingress settings.
Run: `terraform init`
Run: `terraform plan -out tfplan`
Run: `terraform apply tfplan`
After deployment, migrate PostgreSQL data, sync S3 assets to Blob Storage, load required secrets into Key Vault, and update DNS/certificates for Application Gateway.
For production, confirm hub-spoke peering, private DNS integration, TLS listener configuration, and monitoring/alert requirements.
```