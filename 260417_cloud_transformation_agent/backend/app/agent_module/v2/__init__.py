"""V2 migration pipeline — deterministic generation with LLM only where needed.

Replaces the single-call MigrationAgent with a multi-step pipeline:

  1. MigrationContext     — Discovery graph + Mappings, no text flattening
  2. Strategy Agent (LLM) — waves, risks, open_questions
  3. Module Generators    — VPC/Subnet/SG/NSG/EC2/RDS/S3 (mostly deterministic)
  4. Root Wiring          — module composition, providers, resource group
  5. Validator            — terraform fmt + init + validate, optional LLM fix
  6. Data Migrations      — pg_dump / AzCopy / Redis (rule-based)
"""

from .context import MigrationContext
from .pipeline import run_migration_v2

__all__ = ["MigrationContext", "run_migration_v2"]
