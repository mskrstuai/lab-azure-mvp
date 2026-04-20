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
