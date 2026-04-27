This Terraform module deploys an Azure target platform for migrating AWS ALB, ECS Fargate, RDS PostgreSQL, S3, ElastiCache Redis, Secrets Manager, and CloudWatch.
It creates a resource group, spoke VNet/subnets, Application Gateway, Container Apps environment/apps, PostgreSQL Flexible Server, Redis, Storage Account, Key Vault, and Log Analytics diagnostics.
Prerequisite: install Terraform and Azure CLI, then authenticate with `az login` and select the correct subscription.
Review and customize variables in `variables.tf` or a `.tfvars` file, especially container images, CIDRs, database sizing, and ingress settings.
Run: `terraform init`
Run: `terraform plan -out tfplan`
Run: `terraform apply tfplan`
After deployment, migrate PostgreSQL data, sync S3 assets to Blob Storage, load required secrets into Key Vault, and update DNS/certificates for Application Gateway.
For production, confirm hub-spoke peering, private DNS integration, TLS listener configuration, and monitoring/alert requirements.
