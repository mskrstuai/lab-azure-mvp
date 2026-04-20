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
