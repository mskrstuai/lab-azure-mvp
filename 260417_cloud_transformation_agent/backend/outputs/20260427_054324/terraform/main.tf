data "azurerm_client_config" "current" {}

# One suffix per apply so names stay unique (subscription/region) and do not clash across stacks.
resource "random_string" "suffix" {
  length  = 4
  upper   = false
  special = false
}

locals {
  suffix = random_string.suffix.result
  # Do not use a single short hash of (env+location+suffix) for global names: suffix is often
  # truncated. Key Vault, Postgres, and Redis get explicit `*-{suffix}-*` patterns instead.
  # Key Vault: global 3-24 char name
  key_vault_name = lower(substr("kv-${local.suffix}-${replace(var.environment, "-", "")}", 0, 24))
  # Storage account: global namespace, max 24 characters, lowercase alphanumeric.
  storage_account_name = lower(substr("st${replace(var.environment, "-", "")}${local.suffix}${replace(var.location, "-", "")}", 0, 24))
  # PostgreSQL Flexible Server: global 3-63 char name; suffix first avoids ServerNameAlreadyExists
  postgresql_server_name = lower(substr("psql-${local.suffix}-${replace(var.environment, "-", "")}", 0, 63))
  # Azure Cache for Redis: global name; suffix first
  redis_cache_name = lower(substr("redis-${local.suffix}-${replace(var.environment, "-", "")}", 0, 63))
  common_tags           = merge(var.tags, { environment = var.environment })
  first_container_app   = keys(var.container_apps)[0]
  # Resource group: optional separate stack per deployment; keeps RG names unique in subscription.
  resource_group_suffixed = "${var.resource_group_name}-${local.suffix}"
  # Private DNS for PostgreSQL Flexible: must be unique; label must be valid DNS.
  postgresql_private_zone_name = "pg${replace("${var.environment}${local.suffix}", "-", "")}.postgres.database.azure.com"
}

# Resource group for all migrated services.
resource "azurerm_resource_group" "main" {
  name     = local.resource_group_suffixed
  location = var.location
  tags     = local.common_tags
}

# Log Analytics workspace for Azure Monitor and Container Apps logs.
resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-${var.environment}-${var.location}-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = var.log_analytics_retention_in_days
  tags                = local.common_tags
}

# Spoke virtual network aligned to hub-spoke networking.
resource "azurerm_virtual_network" "main" {
  name                = "vnet-${var.environment}-${var.location}-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = var.vnet_address_space
  tags                = local.common_tags
}

# Network security group for the application gateway subnet.
# v2 (Standard_v2 / WAF_v2) must allow GatewayManager 65200-65535, Azure load balancer, and public listener ports.
# See: https://learn.microsoft.com/en-us/azure/application-gateway/configuration-infrastructure#network-security-groups
resource "azurerm_network_security_group" "appgw" {
  name                = "nsg-appgw-${var.environment}-${var.location}-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags

  security_rule {
    name                       = "AllowGWM-65200-65535"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "65200-65535"
    source_address_prefix      = "GatewayManager"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowInternet-65200-65535"
    priority                   = 102
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "65200-65535"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowAzureLoadBalancerIn"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "AzureLoadBalancer"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowInternet-HTTP"
    priority                   = 120
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = tostring(var.application_gateway_frontend_port)
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "AllowInternet-HTTPS"
    priority                   = 130
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "Internet"
    destination_address_prefix = "*"
  }
}

# Network security group for the container apps subnet.
resource "azurerm_network_security_group" "container_apps" {
  name                = "nsg-ca-${var.environment}-${var.location}-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Network security group for the database subnet.
resource "azurerm_network_security_group" "database" {
  name                = "nsg-db-${var.environment}-${var.location}-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Network security group for the cache subnet.
resource "azurerm_network_security_group" "cache" {
  name                = "nsg-cache-${var.environment}-${var.location}-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Application Gateway subnet.
resource "azurerm_subnet" "appgw" {
  name                 = "snet-appgw-${local.suffix}"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.appgw]
}

# Container Apps infrastructure subnet.
resource "azurerm_subnet" "container_apps" {
  name                 = "snet-container-apps-${local.suffix}"
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
  name                 = "snet-private-endpoints-${local.suffix}"
  resource_group_name  = azurerm_resource_group.main.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [var.subnet_prefixes.private_endpoints]

  private_endpoint_network_policies = "Disabled"
}

# PostgreSQL delegated subnet.
resource "azurerm_subnet" "database" {
  name                 = "snet-database-${local.suffix}"
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
  name                 = "snet-cache-${local.suffix}"
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
  name                = "pip-appgw-${var.environment}-${var.location}-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.common_tags
}

# Key Vault for migrated secrets.
resource "azurerm_key_vault" "main" {
  name                       = local.key_vault_name
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
  name                = local.postgresql_private_zone_name
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags
}

# Link PostgreSQL private DNS zone to the spoke VNet.
resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                  = "postgres-link-${var.environment}-${local.suffix}"
  private_dns_zone_name = azurerm_private_dns_zone.postgres.name
  resource_group_name   = azurerm_resource_group.main.name
  virtual_network_id    = azurerm_virtual_network.main.id
  tags                  = local.common_tags
}

# PostgreSQL Flexible Server replacing RDS PostgreSQL.
resource "azurerm_postgresql_flexible_server" "main" {
  name                   = local.postgresql_server_name
  resource_group_name    = azurerm_resource_group.main.name
  location               = azurerm_resource_group.main.location
  version                = var.postgresql_version
  delegated_subnet_id    = azurerm_subnet.database.id
  private_dns_zone_id    = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false
  administrator_login    = var.db_admin_username
  administrator_password = random_password.db_admin.result
  zone                   = "1"
  storage_mb             = var.db_storage_mb
  sku_name               = var.db_sku_name
  backup_retention_days  = var.db_backup_retention_days
  tags                   = local.common_tags

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]
}

# Azure Cache for Redis replacing ElastiCache Redis. Optional: set `deploy_redis = false` to validate the rest of the stack without long Redis provisioning.
resource "azurerm_redis_cache" "main" {
  count = var.deploy_redis ? 1 : 0

  name                = local.redis_cache_name
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  capacity            = var.redis_capacity
  family              = var.redis_family
  sku_name            = var.redis_sku_name
  minimum_tls_version = "1.2"
  non_ssl_port_enabled = false
  tags                = local.common_tags

  # Standard/ Premium Redis often needs 20–45+ min to provision; plan/apply is polling until "Running".
  timeouts {
    create = "90m"
    update = "90m"
    delete = "60m"
  }
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
  # Explicitly allow key-based data-plane access unless disabled by policy; the provider
  # can use Entra ID instead when `storage_use_azuread` is set on the provider.
  shared_access_key_enabled        = true
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
  name                       = "cae-${var.environment}-${var.location}-${local.suffix}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  infrastructure_subnet_id   = azurerm_subnet.container_apps.id
  tags                       = local.common_tags
}

# User-assigned managed identity for application access to Azure services.
resource "azurerm_user_assigned_identity" "container_apps" {
  name                = "id-ca-${var.environment}-${var.location}-${local.suffix}"
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
  name                         = "ca-${each.key}-${var.environment}-${local.suffix}"
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
        value = var.deploy_redis ? azurerm_redis_cache.main[0].hostname : var.redis_host_when_skipped
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

# WAF policy is required when using Application Gateway SKU tier WAF_v2.
resource "azurerm_web_application_firewall_policy" "main" {
  name                = "waf-${var.environment}-${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags

  policy_settings {
    enabled = true
    mode    = "Detection"
  }

  managed_rules {
    managed_rule_set {
      type    = "OWASP"
      version = "3.2"
    }
  }
}

# Application Gateway replacing AWS ALB.
resource "azurerm_application_gateway" "main" {
  name                = "agw-${var.environment}-${var.location}-${local.suffix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  tags                = local.common_tags

  firewall_policy_id = azurerm_web_application_firewall_policy.main.id

  sku {
    name     = var.application_gateway_sku_name
    tier     = var.application_gateway_sku_tier
    capacity = var.application_gateway_capacity
  }

  # Azure no longer accepts the legacy default AppGwSslPolicy20150501; set a current predefined policy.
  # See: https://learn.microsoft.com/en-us/azure/application-gateway/application-gateway-ssl-policy-overview
  ssl_policy {
    policy_type = "Predefined"
    policy_name = "AppGwSslPolicy20220101"
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
