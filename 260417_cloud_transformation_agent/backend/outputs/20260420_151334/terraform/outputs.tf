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
