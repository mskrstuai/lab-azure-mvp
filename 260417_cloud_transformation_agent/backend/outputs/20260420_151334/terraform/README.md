This module deploys an Azure target landing zone for the AWS ThreeTierWebArch migration.
It creates one Resource Group, VNet with public/app/db subnets, NSGs, route tables, NAT Gateway, public and internal Application Gateways, web/app Linux VM Scale Sets, managed database, Key Vault, Storage Account, and Log Analytics.

Prerequisites: Azure CLI installed and authenticated with `az login`, Terraform >= 1.5.0, and permission to create networking, compute, database, and Key Vault resources.

Run:
terraform init
terraform plan -out tfplan
terraform apply tfplan

Override defaults in a .tfvars file for subnet CIDRs, SSH key, listener ports, VM sizes, and database engine/version.
After deployment, load application code/bootstrap into the VM Scale Sets, migrate the Aurora database with Azure DMS or native tooling, update secrets in Key Vault, and cut over DNS to the public Application Gateway IP.
Validate web, app, and database connectivity before production cutover.
