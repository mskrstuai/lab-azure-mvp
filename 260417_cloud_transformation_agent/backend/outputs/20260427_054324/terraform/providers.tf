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
  # Data-plane reads (e.g. queue properties) use storage keys by default. If the account or a
  # policy disables key-based auth, plan/apply returns 403 KeyBasedAuthenticationNotPermitted
  # unless the provider uses Entra ID for storage. Grant the run identity (SP/user) data-plane
  # roles on the storage account (e.g. Storage Queue Data Reader, Storage Blob Data Owner).
  storage_use_azuread = true
}
