output "name_suffix" {
  description = "Random per-apply suffix appended to group and other resource names for uniqueness."
  value       = local.suffix
}

output "resource_group_name" {
  description = "Resource group name (base name with random suffix applied)."
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
  description = "Azure Cache for Redis hostname; null if deploy_redis is false."
  value       = var.deploy_redis ? azurerm_redis_cache.main[0].hostname : null
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
