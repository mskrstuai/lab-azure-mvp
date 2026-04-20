This Terraform module deploys an Azure target for the AWS ThreeTierWebArch workload.
It creates one Resource Group, a six-subnet VNet, NSGs, route tables, NAT Gateway, public/internal Application Gateways, web/app Linux VM Scale Sets, PostgreSQL Flexible Server, Key Vault, and Log Analytics.

Prerequisites: Azure CLI, Terraform >= 1.5, and an authenticated session with `az login`.
Set the target subscription if needed with `az account set --subscription <subscription-id>`.

Run:
terraform init
terraform plan -out tfplan
terraform apply tfplan

Before production use, replace default CIDRs, SSH key, listener ports, health settings, VM bootstrap data, and database engine/settings with discovered AWS values.
Post-deploy, load application code/config onto the VM Scale Sets, migrate the database, validate connectivity tier by tier, then perform DNS cutover.
