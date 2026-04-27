variable "location" {
  description = <<-EOT
    Azure region for the entire stack (VNet, Container Apps, PostgreSQL Flexible, etc. must be colocated).
    If `LocationIsOfferRestricted` appears for PostgreSQL, your subscription cannot create
    `Microsoft.DBforPostgreSQL/flexibleServers` in that region—try e.g. koreacentral, westeurope, japaneast, or
    request access: https://aka.ms/postgres-request-quota-increase
  EOT
  type        = string
  default     = "koreacentral"
}

variable "resource_group_name" {
  description = "Base name of the resource group. A 4-character random suffix is appended so parallel deployments do not clash."
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
    appgw             = string
    container_apps    = string
    private_endpoints = string
    database          = string
    cache             = string
  })
  default = {
    appgw = "10.50.0.0/24"
    # /23 CIDRs must start on a /23 boundary (e.g. .0, .2, .4 in the third octet). 10.50.0.0/23
    # would overlap the app gateway subnet, so 10.50.2.0/23 is used; private/DB/cache follow after.
    container_apps    = "10.50.2.0/23"
    private_endpoints = "10.50.4.0/24"
    database          = "10.50.5.0/24"
    cache             = "10.50.6.0/24"
  }
}

variable "container_apps" {
  description = "Container Apps to deploy, representing ECS Fargate services."
  type = map(object({
    image            = string
    target_port      = number
    cpu              = number
    memory           = string
    min_replicas     = number
    max_replicas     = number
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

variable "deploy_redis" {
  description = "Set to false to skip Azure Cache for Redis (faster apply) and check the rest of the stack. Container apps use redis_host_when_skipped for REDIS_HOST."
  type        = bool
  default     = true
}

variable "redis_host_when_skipped" {
  description = "Value for REDIS_HOST when deploy_redis is false (placeholder; app should tolerate it if Redis is not used)."
  type        = string
  default     = "127.0.0.1"
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
