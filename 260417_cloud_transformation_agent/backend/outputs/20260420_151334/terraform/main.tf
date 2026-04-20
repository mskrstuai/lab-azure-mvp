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
