"""Deterministic Terraform generators — Phase 1 graph + Phase 2 mappings → HCL.

No LLM calls.  Each generator is a pure function from MigrationContext to a
TerraformModule.  Topology relationships (subnet→VPC, EC2→SG, RDS→subnet
group) are preserved by direct reference, not text re-parsing.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .context import MigrationContext
from .schema import TerraformModule


# ── String/HCL helpers ──────────────────────────────────────────────

def slugify(s: str) -> str:
    """Convert to a valid Terraform identifier (lowercase, _ separated)."""
    s = re.sub(r"[^a-zA-Z0-9_]", "_", s or "unnamed")
    s = re.sub(r"_+", "_", s).strip("_")
    return s.lower() or "resource"


def _esc(s: str) -> str:
    """Escape a string for an HCL string literal."""
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def _hcl_str_list(items: List[str]) -> str:
    return "[" + ", ".join(f'"{_esc(x)}"' for x in items) + "]"


def _common_module_vars() -> str:
    return '''variable "resource_group_name" {
  description = "Azure Resource Group name"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
}

variable "tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default     = {}
}
'''


def _storage_vars() -> str:
    """Storage module also needs a globally-unique suffix for Storage Account names."""
    return _common_module_vars() + '''
variable "name_suffix" {
  description = "Suffix appended to globally-unique resource names (e.g., storage account)"
  type        = string
}
'''


# ── Networking module ─────────────────────────────────────────────────

def _format_nsg_rule(rule: Dict[str, Any], direction: str, priority: int, prefix: str) -> str:
    proto_in = (rule.get("protocol") or "*").lower()
    if proto_in == "tcp":
        proto_az = "Tcp"
    elif proto_in == "udp":
        proto_az = "Udp"
    elif proto_in in ("-1", "*", "all"):
        proto_az = "*"
    else:
        proto_az = proto_in.title() or "*"

    from_p = rule.get("from_port")
    to_p = rule.get("to_port")
    if from_p is None and to_p is None:
        port_range = "*"
    elif from_p is None or to_p is None:
        port_range = str(from_p if from_p is not None else to_p)
    elif from_p == to_p:
        port_range = str(from_p)
    else:
        port_range = f"{from_p}-{to_p}"

    sources = rule.get("sources") or []
    cidrs: List[str] = []
    for s in sources:
        if s and ("/" in s or s == "0.0.0.0/0"):
            cidrs.append(s)
    if not cidrs:
        cidrs = ["0.0.0.0/0"]

    return f'''  security_rule {{
    name                       = "{prefix}-{direction.lower()}-{priority}"
    priority                   = {priority}
    direction                  = "{direction}"
    access                     = "Allow"
    protocol                   = "{proto_az}"
    source_port_range          = "*"
    destination_port_range     = "{port_range}"
    source_address_prefixes    = {_hcl_str_list(cidrs)}
    destination_address_prefix = "*"
  }}'''


def generate_networking_module(ctx: MigrationContext) -> TerraformModule:
    """VPC → VNet, Subnet → Subnet, SG → NSG, NAT → NAT Gateway."""
    main: List[str] = []
    out_lines: List[str] = []
    outputs: List[str] = []

    vpcs = ctx.get_vpcs()
    if not vpcs:
        return TerraformModule(
            name="networking",
            files={"main.tf": "# No VPCs in scope.\n", "outputs.tf": "", "variables.tf": _common_module_vars()},
            inputs=["resource_group_name", "location", "tags"],
        )

    for vpc in vpcs:
        vnet_id = slugify(vpc.get("name") or vpc["id"])
        cidr = vpc.get("cidr") or "10.0.0.0/16"
        vnet_name_attr = vpc.get("name") or vpc["id"]

        main.append(f'''
# Source: AWS VPC {vpc['id']}  (CIDR {cidr})
resource "azurerm_virtual_network" "{vnet_id}" {{
  name                = "{_esc(vnet_name_attr)}-vnet"
  address_space       = ["{cidr}"]
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}}'''.rstrip())
        outputs.append(f"vnet_{vnet_id}_id")
        out_lines.append(f'''
output "vnet_{vnet_id}_id" {{
  description = "Resource ID of the {vnet_name_attr} VNet"
  value       = azurerm_virtual_network.{vnet_id}.id
}}'''.rstrip())

        # ── Subnets ──────────────────────────────────────
        for subnet in vpc.get("subnets") or []:
            snet_id = slugify(subnet.get("name") or subnet["id"])
            scidr = subnet.get("cidr") or "10.0.0.0/24"
            visibility = "public" if subnet.get("public") else "private"

            main.append(f'''
# Source: AWS Subnet {subnet['id']}  ({subnet.get('az','?')}, {visibility}, {scidr})
resource "azurerm_subnet" "{snet_id}" {{
  name                 = "{_esc(subnet.get('name') or subnet['id'])}"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.{vnet_id}.name
  address_prefixes     = ["{scidr}"]
}}'''.rstrip())
            outputs.append(f"subnet_{snet_id}_id")
            out_lines.append(f'''
output "subnet_{snet_id}_id" {{
  description = "Resource ID of subnet {snet_id}"
  value       = azurerm_subnet.{snet_id}.id
}}'''.rstrip())

        # ── NSGs (Security Groups) ─────────────────────────
        for sg in vpc.get("security_groups") or []:
            nsg_id = slugify(sg.get("name") or sg["id"])
            rules: List[str] = []
            priority = 100
            for r in sg.get("ingress") or []:
                rules.append(_format_nsg_rule(r, "Inbound", priority, nsg_id))
                priority += 10
            for r in sg.get("egress") or []:
                # Skip the default allow-all egress that Azure gets for free
                if r.get("protocol") == "-1" and (r.get("sources") or []) in (["0.0.0.0/0"], []):
                    continue
                rules.append(_format_nsg_rule(r, "Outbound", priority, nsg_id))
                priority += 10
            rules_block = "\n".join(rules) if rules else ""

            main.append(f'''
# Source: AWS Security Group {sg['id']}  ({_esc((sg.get('description') or '')[:60])})
resource "azurerm_network_security_group" "{nsg_id}" {{
  name                = "{_esc(sg.get('name') or sg['id'])}-nsg"
  location            = var.location
  resource_group_name = var.resource_group_name
{rules_block}
  tags = var.tags
}}'''.rstrip())
            outputs.append(f"nsg_{nsg_id}_id")
            out_lines.append(f'''
output "nsg_{nsg_id}_id" {{
  description = "Resource ID of NSG {nsg_id}"
  value       = azurerm_network_security_group.{nsg_id}.id
}}'''.rstrip())

        # ── NAT Gateways ───────────────────────────────────
        for nat in vpc.get("nat_gateways") or []:
            nat_id = slugify(nat.get("name") or nat["id"])
            main.append(f'''
# Source: AWS NAT Gateway {nat['id']}
resource "azurerm_public_ip" "{nat_id}_pip" {{
  name                = "{nat_id}-pip"
  location            = var.location
  resource_group_name = var.resource_group_name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}}

resource "azurerm_nat_gateway" "{nat_id}" {{
  name                = "{nat_id}-nat"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku_name            = "Standard"
  tags                = var.tags
}}

resource "azurerm_nat_gateway_public_ip_association" "{nat_id}" {{
  nat_gateway_id       = azurerm_nat_gateway.{nat_id}.id
  public_ip_address_id = azurerm_public_ip.{nat_id}_pip.id
}}'''.rstrip())

    return TerraformModule(
        name="networking",
        files={
            "main.tf":      "\n".join(main).strip() + "\n",
            "outputs.tf":   "\n".join(out_lines).strip() + "\n",
            "variables.tf": _common_module_vars(),
        },
        outputs=outputs,
        inputs=["resource_group_name", "location", "tags"],
    )


# ── Compute module (EC2 → VM) ──────────────────────────────────────

def generate_compute_module(ctx: MigrationContext) -> TerraformModule:
    """EC2 instances → Azure Linux VMs.  Uses MappingAgent's chosen SKU."""
    instances = ctx.get_ec2()
    if not instances:
        return TerraformModule(
            name="compute",
            files={"main.tf": "# No EC2 instances in scope.\n", "outputs.tf": "", "variables.tf": _compute_vars()},
            inputs=["resource_group_name", "location", "tags", "subnet_ids", "nsg_ids", "admin_password"],
        )

    main: List[str] = []
    out_lines: List[str] = []
    outputs: List[str] = []

    for inst in instances:
        vm_id = slugify(inst.get("name") or inst["id"])
        mapping = ctx.get_mapping(arn=inst.get("arn"), _id=inst.get("id"))
        sku = (mapping or {}).get("azure_sku_suggestion") or "Standard_B2s"
        subnet = ctx.subnet_of(inst)
        sgs = ctx.security_groups_of(inst)
        sg_arg = ""
        if sgs:
            first_sg = slugify(sgs[0].get("name") or sgs[0]["id"])
            sg_arg = f"  network_security_group_id = var.nsg_ids[\"{first_sg}\"]\n"

        subnet_ref = ""
        if subnet:
            sname = slugify(subnet.get("name") or subnet["id"])
            subnet_ref = f'var.subnet_ids["{sname}"]'
        else:
            # No subnet info — emit a TODO that the user must wire.
            subnet_ref = '"" # TODO: subnet not detected in Discovery'

        rationale = (mapping or {}).get("rationale") or ""

        main.append(f'''
# Source: AWS EC2 {inst['id']}  (type={inst.get('instance_type','?')}, state={inst.get('state','?')})
{f"# Mapping rationale: {rationale}" if rationale else ""}
resource "azurerm_network_interface" "{vm_id}_nic" {{
  name                = "{vm_id}-nic"
  location            = var.location
  resource_group_name = var.resource_group_name
  ip_configuration {{
    name                          = "ipconfig1"
    subnet_id                     = {subnet_ref}
    private_ip_address_allocation = "Dynamic"
  }}
  tags = var.tags
}}

resource "azurerm_linux_virtual_machine" "{vm_id}" {{
  name                            = "{_esc(inst.get('name') or inst['id'])}"
  location                        = var.location
  resource_group_name             = var.resource_group_name
  size                            = "{sku}"
  admin_username                  = "azureuser"
  admin_password                  = var.admin_password
  disable_password_authentication = false
  network_interface_ids           = [azurerm_network_interface.{vm_id}_nic.id]

  os_disk {{
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }}

  source_image_reference {{
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }}

  tags = var.tags
}}'''.rstrip())
        outputs.append(f"vm_{vm_id}_id")
        out_lines.append(f'''
output "vm_{vm_id}_id" {{
  description = "Resource ID of {vm_id}"
  value       = azurerm_linux_virtual_machine.{vm_id}.id
}}'''.rstrip())

    return TerraformModule(
        name="compute",
        files={
            "main.tf":      "\n".join(main).strip() + "\n",
            "outputs.tf":   "\n".join(out_lines).strip() + "\n",
            "variables.tf": _compute_vars(),
        },
        outputs=outputs,
        inputs=["resource_group_name", "location", "tags", "subnet_ids", "nsg_ids", "admin_password"],
    )


def _compute_vars() -> str:
    return _common_module_vars() + '''
variable "subnet_ids" {
  description = "Map of subnet logical name → Azure subnet ID"
  type        = map(string)
  default     = {}
}

variable "nsg_ids" {
  description = "Map of NSG logical name → Azure NSG ID"
  type        = map(string)
  default     = {}
}

variable "admin_password" {
  description = "Initial admin password for VMs (rotate after migration)"
  type        = string
  sensitive   = true
}
'''


# ── Database module (RDS → Azure DB) ────────────────────────────────

def generate_database_module(ctx: MigrationContext) -> TerraformModule:
    """RDS instances → Azure Database for PostgreSQL/MySQL Flexible Server."""
    dbs = ctx.get_rds()
    if not dbs:
        return TerraformModule(
            name="database",
            files={"main.tf": "# No RDS instances in scope.\n", "outputs.tf": "", "variables.tf": _db_vars()},
            inputs=["resource_group_name", "location", "tags", "subnet_ids", "admin_password"],
        )

    main: List[str] = []
    out_lines: List[str] = []
    outputs: List[str] = []

    for db in dbs:
        db_name = slugify(db.get("id") or "rds")
        engine = (db.get("engine") or "postgres").lower()
        mapping = ctx.get_mapping(arn=db.get("arn"), _id=db.get("id"))
        sku = (mapping or {}).get("azure_sku_suggestion") or "B_Standard_B1ms"
        storage_gb = max(int(db.get("storage_gb") or 32), 32)
        version = (db.get("engine_version") or "").split(".")[0] or "15"

        if "mysql" in engine or "maria" in engine:
            tf_resource = "azurerm_mysql_flexible_server"
            db_kind = "MySQL"
            version = version if version in ("5.7", "8.0") else "8.0"
        else:
            tf_resource = "azurerm_postgresql_flexible_server"
            db_kind = "PostgreSQL"
            version = version if version in ("11", "12", "13", "14", "15", "16") else "15"

        # Pick the first subnet as a placeholder (Flexible Server can be either
        # public or VNet-injected — leaving public for simplicity here).
        main.append(f'''
# Source: AWS RDS {db['id']}  ({engine} {db.get('engine_version','')}, {db.get('instance_class','?')})
# Mapping target: {db_kind} Flexible Server, SKU {sku}
resource "{tf_resource}" "{db_name}" {{
  name                   = "{_esc(db['id'])}"
  resource_group_name    = var.resource_group_name
  location               = var.location
  version                = "{version}"
  administrator_login    = "azureadmin"
  administrator_password = var.admin_password
  sku_name               = "{sku}"
  storage_mb             = {storage_gb * 1024}
  zone                   = "1"
  tags                   = var.tags
}}'''.rstrip())
        outputs.append(f"db_{db_name}_fqdn")
        out_lines.append(f'''
output "db_{db_name}_fqdn" {{
  description = "Fully-qualified domain name of {db_name}"
  value       = {tf_resource}.{db_name}.fqdn
}}'''.rstrip())

    return TerraformModule(
        name="database",
        files={
            "main.tf":      "\n".join(main).strip() + "\n",
            "outputs.tf":   "\n".join(out_lines).strip() + "\n",
            "variables.tf": _db_vars(),
        },
        outputs=outputs,
        inputs=["resource_group_name", "location", "tags", "subnet_ids", "admin_password"],
    )


def _db_vars() -> str:
    return _common_module_vars() + '''
variable "subnet_ids" {
  description = "Map of subnet logical name → Azure subnet ID (for VNet injection)"
  type        = map(string)
  default     = {}
}

variable "admin_password" {
  description = "Database administrator password"
  type        = string
  sensitive   = true
}
'''


# ── Storage module (S3 → Storage Account + Blob containers) ────────

def generate_storage_module(ctx: MigrationContext) -> TerraformModule:
    """S3 buckets → Azure Storage Accounts (one per bucket — simplifies migration)."""
    buckets = ctx.get_s3()
    if not buckets:
        return TerraformModule(
            name="storage",
            files={"main.tf": "# No S3 buckets in scope.\n", "outputs.tf": "", "variables.tf": _storage_vars()},
            inputs=["resource_group_name", "location", "tags", "name_suffix"],
        )

    main: List[str] = []
    out_lines: List[str] = []
    outputs: List[str] = []

    for b in buckets:
        # Storage account names: 3-24 chars, lowercase letters and digits only.
        # Reserve 6 chars for the unique suffix → base trimmed to 18 chars.
        base = re.sub(r"[^a-z0-9]", "", (b.get("name") or "bucket").lower())[:18] or "stor"
        if len(base) < 3:
            base = (base + "stor")[:18]
        slug = slugify(b.get("name") or base)

        main.append(f'''
# Source: AWS S3 bucket {b.get('name')}  (region {b.get('region','?')})
# Storage account name = "{base}" + var.name_suffix  (globally unique, ≤ 24 chars)
resource "azurerm_storage_account" "{slug}" {{
  name                     = "{base}${{var.name_suffix}}"
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = var.tags
}}

resource "azurerm_storage_container" "{slug}_default" {{
  name                  = "data"
  storage_account_name  = azurerm_storage_account.{slug}.name
  container_access_type = "private"
}}'''.rstrip())
        outputs.append(f"storage_{slug}_name")
        out_lines.append(f'''
output "storage_{slug}_name" {{
  description = "Storage account name for bucket {b.get('name')}"
  value       = azurerm_storage_account.{slug}.name
}}'''.rstrip())

    return TerraformModule(
        name="storage",
        files={
            "main.tf":      "\n".join(main).strip() + "\n",
            "outputs.tf":   "\n".join(out_lines).strip() + "\n",
            "variables.tf": _storage_vars(),
        },
        outputs=outputs,
        inputs=["resource_group_name", "location", "tags", "name_suffix"],
    )


def _policy_summary_md(pc: Dict[str, Any]) -> str:
    """Render the policy_constraints into a README section."""
    if not pc:
        return ""
    if pc.get("error"):
        return f"## Azure Policy\n\n_정책 조회 실패: {pc.get('error')}_\n"
    parts = ["## Azure Policy 요약 (Plan 시 자동 반영)\n"]
    rt = pc.get("required_tags") or []
    td = pc.get("tag_defaults") or {}
    al = pc.get("allowed_locations") or []
    mr = pc.get("manual_review") or []
    if rt or td:
        parts.append("**필수 태그 (var.tags 기본값에 자동 포함):**")
        for t in rt:
            v = td.get(t, "TBD — terraform.tfvars.json 에서 실제 값으로 override")
            parts.append(f"- `{t}` = `{v}`")
        parts.append("")
    if al:
        parts.append(f"**허용 region**: {', '.join(f'`{x}`' for x in al)}")
        parts.append("")
    if mr:
        parts.append("**자동 변환되지 않은 정책 (수동 확인 권장):**\n")
        for p in mr[:20]:
            parts.append(f"- **{p.get('name')}** (`{p.get('effect')}`) — {p.get('rule')}")
        if len(mr) > 20:
            parts.append(f"- … 외 {len(mr) - 20}개")
        parts.append("")
    return "\n".join(parts)


# ── Root module — wires everything together ─────────────────────────

def generate_root_module(
    ctx: MigrationContext,
    modules: List[TerraformModule],
) -> TerraformModule:
    """Generate the root module with provider, RG, and module calls."""

    # Build subnet_ids / nsg_ids maps from the networking module's outputs
    networking = next((m for m in modules if m.name == "networking"), None)
    subnet_id_map: Dict[str, str] = {}
    nsg_id_map: Dict[str, str] = {}
    if networking:
        for out in networking.outputs:
            if out.startswith("subnet_") and out.endswith("_id"):
                key = out[len("subnet_"):-len("_id")]
                subnet_id_map[key] = f"module.networking.{out}"
            elif out.startswith("nsg_") and out.endswith("_id"):
                key = out[len("nsg_"):-len("_id")]
                nsg_id_map[key] = f"module.networking.{out}"

    rg_name = f"rg-{slugify(ctx.goals[:20] or 'migration')}"

    providers_tf = '''terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.117"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}
'''

    main_lines: List[str] = []
    # ── Random suffix for globally-unique resource names ────────────
    # Generated once per Terraform state; if the user wants a deterministic
    # suffix they can set var.name_suffix.
    main_lines.append(f'''
resource "random_password" "admin" {{
  length  = 20
  special = true
}}

resource "random_string" "suffix" {{
  length  = 6
  special = false
  upper   = false
  numeric = true
}}

locals {{
  # Effective suffix: user-provided or auto-generated
  suffix = var.name_suffix != "" ? var.name_suffix : random_string.suffix.result
}}

resource "azurerm_resource_group" "main" {{
  name     = "${{var.resource_group_name}}-${{local.suffix}}"
  location = var.location
  tags     = var.tags
}}'''.rstrip())

    # networking
    if networking and networking.files.get("main.tf", "").strip() and "No VPCs" not in networking.files.get("main.tf", ""):
        main_lines.append(f'''
module "networking" {{
  source              = "./modules/networking"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = var.tags
}}'''.rstrip())

    # compute
    compute = next((m for m in modules if m.name == "compute"), None)
    if compute and "No EC2" not in compute.files.get("main.tf", ""):
        # Build maps inline as HCL
        subnet_map_hcl = "{\n" + "\n".join(f'    {k} = {v}' for k, v in subnet_id_map.items()) + "\n  }" if subnet_id_map else "{}"
        nsg_map_hcl = "{\n" + "\n".join(f'    {k} = {v}' for k, v in nsg_id_map.items()) + "\n  }" if nsg_id_map else "{}"
        main_lines.append(f'''
module "compute" {{
  source              = "./modules/compute"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = var.tags
  subnet_ids          = {subnet_map_hcl}
  nsg_ids             = {nsg_map_hcl}
  admin_password      = random_password.admin.result
}}'''.rstrip())

    # database
    db = next((m for m in modules if m.name == "database"), None)
    if db and "No RDS" not in db.files.get("main.tf", ""):
        subnet_map_hcl = "{\n" + "\n".join(f'    {k} = {v}' for k, v in subnet_id_map.items()) + "\n  }" if subnet_id_map else "{}"
        main_lines.append(f'''
module "database" {{
  source              = "./modules/database"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = var.tags
  subnet_ids          = {subnet_map_hcl}
  admin_password      = random_password.admin.result
}}'''.rstrip())

    # storage  (passes the unique suffix down for globally-unique account names)
    storage = next((m for m in modules if m.name == "storage"), None)
    if storage and "No S3" not in storage.files.get("main.tf", ""):
        main_lines.append(f'''
module "storage" {{
  source              = "./modules/storage"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = var.tags
  name_suffix         = local.suffix
}}'''.rstrip())

    # ── Policy-driven defaults (sub_id 가 있을 때만) ──
    pc = ctx.policy_constraints or {}
    required_tags    = list(pc.get("required_tags") or [])
    tag_defaults     = dict(pc.get("tag_defaults") or {})
    allowed_locations = list(pc.get("allowed_locations") or [])

    # Build var.tags default map: base + policy-required (filled with placeholder
    # values when the policy doesn't mandate a specific value).
    base_tags = {
        "managed_by": "cloud-transformation-agent",
        "source":     "aws-migration",
    }
    tag_map = {**base_tags}
    for t in required_tags:
        tag_map[t] = tag_defaults.get(t, "TBD")   # user can override via tfvars
    # Override with explicit policy-mandated values (these win over placeholders)
    for k, v in tag_defaults.items():
        tag_map[k] = v

    tag_lines = "\n".join(f'    {k} = "{v}"' for k, v in tag_map.items())

    # Pick a location default that satisfies allowed_locations if possible.
    location_default = ctx.target_region
    location_warning_comment = ""
    if allowed_locations and ctx.target_region not in allowed_locations:
        # Fall back to the first allowed location, but flag clearly
        location_default = allowed_locations[0]
        location_warning_comment = (
            f"# ⚠ target region '{ctx.target_region}' 가 정책 allowed_locations 에 없어 "
            f"'{location_default}' 로 변경됨. 허용 지역: {allowed_locations}\n"
        )

    variables_tf = f'''variable "resource_group_name" {{
  description = "Base name for the Azure Resource Group (a unique suffix will be appended)"
  type        = string
  default     = "{rg_name}"
}}

{location_warning_comment}variable "location" {{
  description = "Azure region for all resources"
  type        = string
  default     = "{location_default}"
}}

variable "tags" {{
  description = "Tags applied to all resources (정책에서 요구한 tag 자동 포함)"
  type        = map(string)
  default = {{
{tag_lines}
  }}
}}

variable "name_suffix" {{
  description = "Optional suffix for globally-unique resource names. Empty = auto-generate a random 6-char suffix."
  type        = string
  default     = ""
}}
'''

    outputs_tf = '''output "resource_group_name" {
  value = azurerm_resource_group.main.name
}

output "name_suffix" {
  description = "Suffix used for globally-unique resource names"
  value       = local.suffix
}

output "admin_password" {
  description = "Generated admin password (rotate immediately)"
  value       = random_password.admin.result
  sensitive   = true
}
'''

    readme = f'''# Azure Terraform Module — AWS → Azure Migration

Generated by Cloud Transformation Agent v2.

## Source AWS context
- Account: `{ctx.get_account_id()}`
- Region:  `{ctx.get_source_region()}`
- VPCs:    `{ctx.stats()['vpcs']}`
- EC2:     `{ctx.stats()['ec2']}`
- RDS:     `{ctx.stats()['rds']}`
- S3:      `{ctx.stats()['s3']}`

## Target Azure context
- Region: `{ctx.target_region}`

## Module structure
- `main.tf` — Resource Group + module composition
- `modules/networking/` — VNet, subnets, NSGs, NAT GW
- `modules/compute/` — Linux VMs (mapped from EC2)
- `modules/database/` — Azure Database for PostgreSQL/MySQL (mapped from RDS)
- `modules/storage/` — Storage Accounts + Blob containers (mapped from S3)

## Usage
```bash
terraform init
terraform plan
terraform apply
```

## Manual steps after apply
- Rotate `admin_password` from `random_password.admin.result`
- Run data-migration scripts (provided separately)
- Update DNS records to point to new Azure endpoints

{_policy_summary_md(pc)}'''

    return TerraformModule(
        name="root",
        files={
            "providers.tf": providers_tf,
            "main.tf":      "\n".join(main_lines).strip() + "\n",
            "variables.tf": variables_tf,
            "outputs.tf":   outputs_tf,
            "README.md":    readme,
        },
        outputs=["resource_group_name"],
        inputs=[],
    )
