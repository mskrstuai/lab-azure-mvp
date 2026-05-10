"""Migration context — Discovery graph + Mappings shared across pipeline steps.

Avoids text flattening so all topology relationships (subnet→VPC, EC2→SG,
ELB→target group, RDS→subnet group) flow through every step intact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MigrationContext:
    """Shared state across the v2 pipeline.

    All generators, the strategy agent, and the validator read from this.
    Treated as effectively read-only by everything except the pipeline driver.
    """

    architecture: Dict[str, Any]              # Phase 1 result (full graph)
    mappings: List[Dict[str, Any]]            # Phase 2-mapping result
    target_region: str                         # Azure target region
    goals: str = ""                           # Migration goals (free text)
    target_subscription_id: str = ""          # 대상 sub (정책 조회용 — 비어있으면 정책 단계 스킵)
    policy_constraints: Optional[Dict[str, Any]] = None   # extract_constraints() 결과
    extras: Dict[str, Any] = field(default_factory=dict)

    # ── Architecture accessors ──────────────────────────────────────

    def get_vpcs(self) -> List[Dict[str, Any]]:
        return self.architecture.get("networking") or []

    def get_ec2(self) -> List[Dict[str, Any]]:
        return self.architecture.get("ec2") or []

    def get_rds(self) -> List[Dict[str, Any]]:
        return self.architecture.get("rds") or []

    def get_s3(self) -> List[Dict[str, Any]]:
        return self.architecture.get("s3") or []

    def get_lambda(self) -> List[Dict[str, Any]]:
        return self.architecture.get("lambda") or []

    def get_elbs(self) -> List[Dict[str, Any]]:
        return self.architecture.get("elb") or []

    def get_account_id(self) -> str:
        return str(self.architecture.get("account_id") or "")

    def get_source_region(self) -> str:
        return str(self.architecture.get("region") or "")

    # ── Mapping lookup ──────────────────────────────────────────────

    def get_mapping(self, *, arn: Optional[str] = None, _id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Find an AzureTargetMapping by ARN or id (aws_key fallback)."""
        if not (arn or _id):
            return None
        for m in self.mappings:
            keys = (m.get("aws_key"), m.get("arn"))
            if arn and arn in keys:
                return m
            if _id and _id in keys:
                return m
        return None

    # ── Topology walks ──────────────────────────────────────────────

    def vpc_of(self, resource: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        vid = resource.get("vpc_id")
        if not vid:
            return None
        for vpc in self.get_vpcs():
            if vpc.get("id") == vid:
                return vpc
        return None

    def subnet_of(self, resource: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        sid = resource.get("subnet_id")
        if not sid:
            return None
        for vpc in self.get_vpcs():
            for subnet in vpc.get("subnets", []) or []:
                if subnet.get("id") == sid:
                    return subnet
        return None

    def security_groups_of(self, resource: Dict[str, Any]) -> List[Dict[str, Any]]:
        sg_ids = resource.get("security_group_ids") or []
        if not sg_ids:
            return []
        out = []
        vpc = self.vpc_of(resource)
        if not vpc:
            return []
        for sg in vpc.get("security_groups", []) or []:
            if sg.get("id") in sg_ids:
                out.append(sg)
        return out

    # ── Stats ───────────────────────────────────────────────────────

    def has_compute(self) -> bool:
        return bool(self.get_ec2())

    def has_database(self) -> bool:
        return bool(self.get_rds())

    def has_storage(self) -> bool:
        return bool(self.get_s3())

    def has_networking(self) -> bool:
        return bool(self.get_vpcs())

    def stats(self) -> Dict[str, int]:
        vpcs = self.get_vpcs()
        return {
            "vpcs":    len(vpcs),
            "subnets": sum(len(v.get("subnets") or []) for v in vpcs),
            "sgs":     sum(len(v.get("security_groups") or []) for v in vpcs),
            "ec2":     len(self.get_ec2()),
            "rds":     len(self.get_rds()),
            "s3":      len(self.get_s3()),
            "lambda":  len(self.get_lambda()),
            "elb":     len(self.get_elbs()),
        }
