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
