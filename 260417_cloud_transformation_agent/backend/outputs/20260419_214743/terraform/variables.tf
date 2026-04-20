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
