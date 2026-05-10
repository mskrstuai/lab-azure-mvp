"""Phase 1: AWS architecture discovery — full relationship graph.

Collects VPCs, subnets, security-group rules, EC2/RDS/Lambda/ELB/ECS
and cross-references them so the frontend can render a dependency tree
and the migration planner can generate accurate Terraform.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

_CFG = Config(
    retries={"max_attempts": 2, "mode": "standard"},
    connect_timeout=8,
    read_timeout=20,
)


def _client(session: boto3.Session, service: str, region: str):
    return session.client(service, region_name=region, config=_CFG)


def _name(tags: List[Dict]) -> str:
    for t in tags or []:
        if t.get("Key") == "Name":
            return t.get("Value", "")
    return ""


def _fmt_rules(perms: List[Dict]) -> List[Dict]:
    out = []
    for p in perms or []:
        sources = (
            [r["CidrIp"] for r in p.get("IpRanges", [])]
            + [r["CidrIpv6"] for r in p.get("Ipv6Ranges", [])]
            + [r["GroupId"] for r in p.get("UserIdGroupPairs", [])]
        )
        out.append({
            "protocol": p.get("IpProtocol", "-1"),
            "from_port": p.get("FromPort"),
            "to_port": p.get("ToPort"),
            "sources": sources,
        })
    return out


# ── Networking (VPC / Subnet / SG / IGW / NAT) ───────────────────

def _collect_networking(session: boto3.Session, region: str) -> List[Dict]:
    ec2 = _client(session, "ec2", region)
    vpcs: Dict[str, Dict] = {}

    for v in ec2.describe_vpcs().get("Vpcs", []):
        vid = v["VpcId"]
        vpcs[vid] = {
            "id": vid,
            "name": _name(v.get("Tags")),
            "cidr": v.get("CidrBlock"),
            "is_default": v.get("IsDefault", False),
            "subnets": [],
            "security_groups": [],
            "internet_gateways": [],
            "nat_gateways": [],
        }

    pager = ec2.get_paginator("describe_subnets")
    for page in pager.paginate():
        for s in page.get("Subnets", []):
            vid = s.get("VpcId")
            if vid not in vpcs:
                continue
            vpcs[vid]["subnets"].append({
                "id": s["SubnetId"],
                "name": _name(s.get("Tags")),
                "cidr": s.get("CidrBlock"),
                "az": s.get("AvailabilityZone"),
                "public": s.get("MapPublicIpOnLaunch", False),
                "available_ips": s.get("AvailableIpAddressCount"),
                "resources": [],          # filled by cross_reference()
            })

    pager = ec2.get_paginator("describe_security_groups")
    for page in pager.paginate():
        for sg in page.get("SecurityGroups", []):
            vid = sg.get("VpcId")
            if vid not in vpcs:
                continue
            vpcs[vid]["security_groups"].append({
                "id": sg["GroupId"],
                "name": sg.get("GroupName"),
                "description": sg.get("Description"),
                "ingress": _fmt_rules(sg.get("IpPermissions")),
                "egress": _fmt_rules(sg.get("IpPermissionsEgress")),
            })

    for igw in ec2.describe_internet_gateways().get("InternetGateways", []):
        for att in igw.get("Attachments", []):
            vid = att.get("VpcId")
            if vid in vpcs:
                vpcs[vid]["internet_gateways"].append({
                    "id": igw["InternetGatewayId"],
                    "name": _name(igw.get("Tags")),
                })

    pager = ec2.get_paginator("describe_nat_gateways")
    for page in pager.paginate(Filter=[{"Name": "state", "Values": ["available", "pending"]}]):
        for nat in page.get("NatGateways", []):
            vid = nat.get("VpcId")
            if vid in vpcs:
                addr = (nat.get("NatGatewayAddresses") or [{}])[0]
                vpcs[vid]["nat_gateways"].append({
                    "id": nat["NatGatewayId"],
                    "name": _name(nat.get("Tags")),
                    "subnet_id": nat.get("SubnetId"),
                    "public_ip": addr.get("PublicIp"),
                })

    return list(vpcs.values())


# ── EC2 ──────────────────────────────────────────────────────────

def _collect_ec2(session: boto3.Session, region: str, account_id: str = "") -> List[Dict]:
    ec2 = _client(session, "ec2", region)
    out = []
    pager = ec2.get_paginator("describe_instances")
    for page in pager.paginate():
        for res in page.get("Reservations", []):
            for inst in res.get("Instances", []):
                tags = inst.get("Tags") or []
                profile = inst.get("IamInstanceProfile") or {}
                arn_parts = profile.get("Arn", "").split("/")
                role = arn_parts[-1] if len(arn_parts) > 1 else ""
                vols = [
                    {
                        "device": bdm.get("DeviceName"),
                        "volume_id": (bdm.get("Ebs") or {}).get("VolumeId"),
                    }
                    for bdm in inst.get("BlockDeviceMappings", [])
                ]
                iid = inst.get("InstanceId")
                out.append({
                    "_type": "ec2",
                    "id": iid,
                    "arn": f"arn:aws:ec2:{region}:{account_id}:instance/{iid}",
                    "name": _name(tags),
                    "instance_type": inst.get("InstanceType"),
                    "state": (inst.get("State") or {}).get("Name"),
                    "subnet_id": inst.get("SubnetId"),
                    "vpc_id": inst.get("VpcId"),
                    "az": (inst.get("Placement") or {}).get("AvailabilityZone"),
                    "security_group_ids": [sg["GroupId"] for sg in inst.get("SecurityGroups", [])],
                    "private_ip": inst.get("PrivateIpAddress"),
                    "public_ip": inst.get("PublicIpAddress"),
                    "iam_role": role,
                    "ebs_volumes": vols,
                    "launch_time": str(inst.get("LaunchTime") or ""),
                    "tags": {t["Key"]: t["Value"] for t in tags},
                })
    return out


# ── ELB (ALB / NLB) ──────────────────────────────────────────────

def _collect_elb(session: boto3.Session, region: str) -> List[Dict]:
    elb = _client(session, "elbv2", region)
    out = []
    pager = elb.get_paginator("describe_load_balancers")
    for page in pager.paginate():
        for lb in page.get("LoadBalancers", []):
            arn = lb["LoadBalancerArn"]
            listeners = []
            try:
                for listener in elb.describe_listeners(LoadBalancerArn=arn).get("Listeners", []):
                    l_arn = listener["ListenerArn"]
                    tgs = []
                    try:
                        for rule in elb.describe_rules(ListenerArn=l_arn).get("Rules", []):
                            for action in rule.get("Actions", []):
                                tg_arn = action.get("TargetGroupArn")
                                if not tg_arn:
                                    continue
                                try:
                                    tg_info = elb.describe_target_groups(TargetGroupArns=[tg_arn])
                                    tg_name = (tg_info.get("TargetGroups") or [{}])[0].get("TargetGroupName", "")
                                except Exception:
                                    tg_name = ""
                                try:
                                    health = elb.describe_target_health(TargetGroupArn=tg_arn)
                                    targets = [
                                        th["Target"]["Id"]
                                        for th in health.get("TargetHealthDescriptions", [])
                                    ]
                                except Exception:
                                    targets = []
                                tgs.append({"arn": tg_arn, "name": tg_name, "targets": targets})
                    except Exception:
                        pass
                    listeners.append({
                        "port": listener.get("Port"),
                        "protocol": listener.get("Protocol"),
                        "target_groups": tgs,
                    })
            except Exception:
                pass
            out.append({
                "_type": "elb",
                "arn": arn,
                "name": lb.get("LoadBalancerName"),
                "type": lb.get("Type"),
                "scheme": lb.get("Scheme"),
                "vpc_id": lb.get("VpcId"),
                "dns": lb.get("DNSName"),
                "state": (lb.get("State") or {}).get("Code"),
                "listeners": listeners,
            })
    return out


# ── RDS ──────────────────────────────────────────────────────────

def _collect_rds(session: boto3.Session, region: str) -> List[Dict]:
    rds = _client(session, "rds", region)
    out = []
    pager = rds.get_paginator("describe_db_instances")
    for page in pager.paginate():
        for db in page.get("DBInstances", []):
            sg = db.get("DBSubnetGroup") or {}
            out.append({
                "_type": "rds",
                "id": db.get("DBInstanceIdentifier"),
                "arn": db.get("DBInstanceArn"),
                "engine": db.get("Engine"),
                "engine_version": db.get("EngineVersion"),
                "instance_class": db.get("DBInstanceClass"),
                "status": db.get("DBInstanceStatus"),
                "storage_gb": db.get("AllocatedStorage"),
                "storage_type": db.get("StorageType"),
                "multi_az": db.get("MultiAZ"),
                "endpoint": (db.get("Endpoint") or {}).get("Address"),
                "port": (db.get("Endpoint") or {}).get("Port"),
                "vpc_id": sg.get("VpcId"),
                "subnet_group_name": sg.get("DBSubnetGroupName"),
                "subnet_ids": [s["SubnetIdentifier"] for s in sg.get("Subnets", [])],
                "security_group_ids": [
                    g["VpcSecurityGroupId"]
                    for g in db.get("VpcSecurityGroups", [])
                    if g.get("Status") == "active"
                ],
                "encrypted": db.get("StorageEncrypted"),
                "backup_retention_days": db.get("BackupRetentionPeriod"),
            })
    return out


# ── Lambda ───────────────────────────────────────────────────────

def _collect_lambda(session: boto3.Session, region: str) -> List[Dict]:
    lmb = _client(session, "lambda", region)
    out = []
    pager = lmb.get_paginator("list_functions")
    for page in pager.paginate():
        for fn in page.get("Functions", []):
            vpc = fn.get("VpcConfig") or {}
            out.append({
                "_type": "lambda",
                "name": fn.get("FunctionName"),
                "arn": fn.get("FunctionArn"),
                "runtime": fn.get("Runtime"),
                "memory_mb": fn.get("MemorySize"),
                "timeout_s": fn.get("Timeout"),
                "iam_role": fn.get("Role", "").split("/")[-1],
                "vpc_id": vpc.get("VpcId"),
                "subnet_ids": vpc.get("SubnetIds") or [],
                "security_group_ids": vpc.get("SecurityGroupIds") or [],
                "in_vpc": bool(vpc.get("VpcId")),
            })
    return out


# ── S3 ───────────────────────────────────────────────────────────

def _collect_s3(session: boto3.Session) -> List[Dict]:
    s3 = session.client("s3", config=_CFG)
    out = []
    for b in (s3.list_buckets().get("Buckets") or [])[:100]:
        name = b.get("Name", "")
        try:
            loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint") or "us-east-1"
        except Exception:
            loc = "?"
        out.append({
            "_type": "s3",
            "name": name,
            "arn": f"arn:aws:s3:::{name}",
            "region": loc,
            "created": str(b.get("CreationDate") or ""),
        })
    return out


# ── ECS ──────────────────────────────────────────────────────────

def _collect_ecs(session: boto3.Session, region: str) -> List[Dict]:
    ecs = _client(session, "ecs", region)
    cluster_arns = ecs.list_clusters(maxResults=100).get("clusterArns") or []
    if not cluster_arns:
        return []
    out = []
    for c in ecs.describe_clusters(clusters=cluster_arns).get("clusters", []):
        c_arn = c.get("clusterArn", "")
        services = []
        try:
            svc_arns = ecs.list_services(cluster=c_arn, maxResults=100).get("serviceArns") or []
            if svc_arns:
                for s in ecs.describe_services(cluster=c_arn, services=svc_arns[:20]).get("services", []):
                    services.append({
                        "name": s.get("serviceName"),
                        "desired": s.get("desiredCount"),
                        "running": s.get("runningCount"),
                        "task_definition": s.get("taskDefinition", "").split("/")[-1],
                        "launch_type": s.get("launchType"),
                    })
        except Exception:
            pass
        out.append({
            "_type": "ecs",
            "arn": c_arn,
            "name": c.get("clusterName"),
            "status": c.get("status"),
            "running_tasks": c.get("runningTasksCount"),
            "services": services,
        })
    return out


# ── ARN allowlist helpers (Resource Group / Tag) ──────────────────

from typing import Optional, Set  # noqa: E402 – already imported via __future__

def _rg_arns(session: boto3.Session, region: str, group_name: str) -> Set[str]:
    """Expand an AWS Resource Group to its member ARNs."""
    client = _client(session, "resource-groups", region)
    arns: Set[str] = set()
    try:
        pager = client.get_paginator("list_group_resources")
        for page in pager.paginate(Group=group_name):
            for r in page.get("ResourceIdentifiers") or []:
                if a := r.get("ResourceArn"):
                    arns.add(a)
            for r in page.get("Resources") or []:
                if a := (r.get("Identifier") or {}).get("ResourceArn"):
                    arns.add(a)
    except (ClientError, BotoCoreError) as e:
        logger.warning("Resource Group expansion failed: %s", e)
    return arns


def _tag_arns(session: boto3.Session, region: str, tag_filters: List[Dict]) -> Set[str]:
    """Return ARNs of all resources matching the given tag filters.

    tag_filters = [{"key": "Project", "values": ["myapp", "shared"]}]
    """
    client = _client(session, "resourcegroupstaggingapi", region)
    tf = [{"Key": f["key"], "Values": f.get("values") or []} for f in tag_filters if f.get("key")]
    if not tf:
        return set()
    arns: Set[str] = set()
    try:
        pager = client.get_paginator("get_resources")
        for page in pager.paginate(TagFilters=tf):
            for mapping in page.get("ResourceTagMappingList") or []:
                if a := mapping.get("ResourceARN"):
                    arns.add(a)
    except (ClientError, BotoCoreError) as e:
        logger.warning("Tag-based ARN filter failed: %s", e)
    return arns


def list_resource_groups(session: boto3.Session, region: str) -> List[Dict]:
    """Return [{name, arn, description}] for the region."""
    client = _client(session, "resource-groups", region)
    groups: List[Dict] = []
    try:
        pager = client.get_paginator("list_groups")
        for page in pager.paginate():
            for g in page.get("GroupIdentifiers") or []:
                groups.append({"name": g.get("GroupName"), "arn": g.get("GroupArn"), "description": ""})
            for g in page.get("Groups") or []:
                groups.append({"name": g.get("Name") or g.get("GroupName"), "arn": g.get("GroupArn"), "description": g.get("Description", "")})
    except (ClientError, BotoCoreError) as e:
        logger.warning("list_resource_groups failed: %s", e)
    # De-duplicate by ARN
    seen: Set[str] = set()
    out = []
    for g in groups:
        key = g.get("arn") or g.get("name") or ""
        if key and key not in seen:
            seen.add(key)
            out.append(g)
    return sorted(out, key=lambda g: (g.get("name") or "").lower())


def list_tag_keys(session: boto3.Session, region: str) -> List[str]:
    """Return the tag keys present in the account (region-scoped)."""
    client = _client(session, "resourcegroupstaggingapi", region)
    keys: List[str] = []
    try:
        pager = client.get_paginator("get_tag_keys")
        for page in pager.paginate():
            keys.extend(page.get("TagKeys") or [])
    except (ClientError, BotoCoreError) as e:
        logger.warning("list_tag_keys failed: %s", e)
    return sorted(set(keys))


def _apply_allowlist(items: List[Dict], allow_arns: Optional[Set[str]]) -> List[Dict]:
    """Keep only items whose ARN is in allow_arns (None = keep all)."""
    if allow_arns is None:
        return items
    return [it for it in items if it.get("arn") in allow_arns]


def _parse_arn(arn: str) -> Dict[str, str]:
    """Split ARN into components: partition/service/region/account/resource_type/resource_id."""
    try:
        parts = arn.split(":", 5)
        if len(parts) < 6:
            return {"service": "", "resource_type": "", "resource_id": arn}
        _, partition, service, region, account, resource = parts
        if "/" in resource:
            rtype, _, rid = resource.partition("/")
        elif ":" in resource:
            rtype, _, rid = resource.partition(":")
        else:
            rtype, rid = "", resource
        return {
            "partition": partition, "service": service,
            "region": region, "account": account,
            "resource_type": rtype, "resource_id": rid or resource,
        }
    except Exception:
        return {"service": "", "resource_type": "", "resource_id": arn}


def _fetch_tags_batch(session: boto3.Session, region: str, arns: List[str]) -> Dict[str, Dict[str, str]]:
    """Batch-fetch Name tags for a list of ARNs via resourcegroupstaggingapi."""
    if not arns:
        return {}
    client = _client(session, "resourcegroupstaggingapi", region)
    out: Dict[str, Dict[str, str]] = {}
    for i in range(0, len(arns), 100):
        batch = arns[i : i + 100]
        try:
            resp = client.get_resources(ResourceARNList=batch)
            for m in resp.get("ResourceTagMappingList") or []:
                a = m.get("ResourceARN")
                if a:
                    out[a] = {t["Key"]: t.get("Value", "") for t in m.get("Tags") or []}
        except (ClientError, BotoCoreError):
            pass
    return out


# Human-readable service name map (best-effort)
_SERVICE_LABEL: Dict[str, str] = {
    "ec2": "EC2", "rds": "RDS", "s3": "S3", "lambda": "Lambda",
    "elasticloadbalancing": "ELB", "ecs": "ECS", "eks": "EKS",
    "dynamodb": "DynamoDB", "elasticache": "ElastiCache",
    "kinesis": "Kinesis", "sqs": "SQS", "sns": "SNS",
    "iam": "IAM", "kms": "KMS", "secretsmanager": "SecretsManager",
    "cloudfront": "CloudFront", "route53": "Route53",
    "autoscaling": "AutoScaling", "efs": "EFS", "backup": "Backup",
    "codecommit": "CodeCommit", "codebuild": "CodeBuild",
    "codepipeline": "CodePipeline", "cloudwatch": "CloudWatch",
    "logs": "CloudWatch Logs", "events": "EventBridge",
    "states": "StepFunctions", "apigateway": "API Gateway",
}


def _generic_from_arns(
    session: boto3.Session,
    region: str,
    arns: Set[str],
) -> List[Dict]:
    """Create generic resource entries for ARNs not covered by typed collectors.

    Uses ARN parsing for service/type and resourcegroupstaggingapi for Name tags.
    """
    if not arns:
        return []
    tags_by_arn = _fetch_tags_batch(session, region, list(arns))
    resources = []
    for arn in sorted(arns):
        parsed = _parse_arn(arn)
        service = parsed.get("service", "")
        rtype   = parsed.get("resource_type", "")
        rid     = parsed.get("resource_id", "")
        tags    = tags_by_arn.get(arn, {})
        name    = tags.get("Name", "")

        # Build a _type key matching typeMeta() in the frontend
        # e.g. "autoscaling/autoScalingGroup" → frontend shows 📦 AUTOSCALING/AUTOSCALINGGROUP
        type_key = f"{service}/{rtype}".strip("/").lower() if service else "unknown"

        resources.append({
            "_type":         type_key,
            "_generic":      True,   # flag so frontend can style differently if needed
            "arn":           arn,
            "id":            rid,
            "name":          name,
            "service":       service,
            "service_label": _SERVICE_LABEL.get(service, service.upper()),
            "resource_type": rtype,
            "region":        parsed.get("region") or region,
            "account":       parsed.get("account", ""),
            "tags":          tags,
        })
    return resources


# ── Cross-reference ───────────────────────────────────────────────

def _cross_reference(data: Dict[str, Any]) -> None:
    """Attach resources to subnet or VPC nodes.

    Placement rules (avoids double-listing):
      - EC2 / Lambda  → specific subnet_id
      - RDS / ELB     → VPC level (spans multiple subnets or has no single subnet)
      - Unknown types → VPC level if vpc_id exists, else unplaced
    """
    subnet_map: Dict[str, List[Dict]] = {}   # subnet_id → resources
    vpc_map: Dict[str, List[Dict]] = {}      # vpc_id   → resources

    def _place(item: Dict) -> None:
        t = item.get("_type", "")
        sid = item.get("subnet_id") or ""
        sids = item.get("subnet_ids") or []
        vid = item.get("vpc_id") or ""

        if t in ("ec2",):
            # EC2 has one specific subnet
            if sid:
                subnet_map.setdefault(sid, []).append(item)
            elif vid:
                vpc_map.setdefault(vid, []).append(item)

        elif t in ("lambda",):
            # Lambda: in-VPC lambdas use first subnet, public lambdas unplaced
            if sids:
                subnet_map.setdefault(sids[0], []).append(item)
            elif vid:
                vpc_map.setdefault(vid, []).append(item)

        elif t in ("rds", "elb"):
            # RDS spans a subnet group; ELB is cross-AZ → both at VPC level
            if vid:
                vpc_map.setdefault(vid, []).append(item)

        else:
            # Generic fallback: subnet > VPC
            if sid:
                subnet_map.setdefault(sid, []).append(item)
            elif vid:
                vpc_map.setdefault(vid, []).append(item)

    all_resources = (
        (data.get("ec2") or [])
        + (data.get("rds") or [])
        + (data.get("elb") or [])
        + (data.get("lambda") or [])
    )
    for item in all_resources:
        _place(item)

    for vpc in data.get("networking") or []:
        vid = vpc["id"]
        for subnet in vpc.get("subnets", []):
            subnet["resources"] = subnet_map.get(subnet["id"], [])
        vpc["direct_resources"] = vpc_map.get(vid, [])


# ── Public entry point ────────────────────────────────────────────

def scan(
    session: boto3.Session,
    region: str,
    resource_group: Optional[str] = None,
    tag_filters: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """Return a full architecture graph for the given region.

    Pass resource_group (name) OR tag_filters to narrow the scope.
    tag_filters = [{"key": "Project", "values": ["myapp"]}]
    """
    from app.services.aws_auth import verify_identity
    try:
        account_id = verify_identity(session)["account_id"]
    except Exception:
        account_id = ""

    # Resolve ARN allowlist up-front (runs fast, serial)
    allow_arns: Optional[Set[str]] = None
    filter_desc = "전체 계정"
    if resource_group:
        allow_arns = _rg_arns(session, region, resource_group)
        filter_desc = f"Resource Group: {resource_group} ({len(allow_arns)} ARNs)"
        logger.info("Architecture scan scoped to %s", filter_desc)
    elif tag_filters:
        allow_arns = _tag_arns(session, region, tag_filters)
        filter_desc = f"Tag filter ({len(allow_arns)} ARNs)"
        logger.info("Architecture scan scoped to %s", filter_desc)

    collectors = {
        "networking": lambda: _collect_networking(session, region),
        "ec2":        lambda: _apply_allowlist(_collect_ec2(session, region, account_id), allow_arns),
        "elb":        lambda: _apply_allowlist(_collect_elb(session, region), allow_arns),
        "rds":        lambda: _apply_allowlist(_collect_rds(session, region), allow_arns),
        "lambda":     lambda: _apply_allowlist(_collect_lambda(session, region), allow_arns),
        "s3":         lambda: _apply_allowlist(_collect_s3(session), allow_arns),
        "ecs":        lambda: _apply_allowlist(_collect_ecs(session, region), allow_arns),
    }

    data: Dict[str, Any] = {
        "region": region,
        "account_id": account_id,
        "filter": filter_desc,
        "resource_group": resource_group,
        "tag_filters": tag_filters,
        "errors": {},
    }

    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {pool.submit(fn): key for key, fn in collectors.items()}
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                data[key] = fut.result()
            except (ClientError, BotoCoreError) as e:
                logger.warning("Architecture collector '%s' failed: %s", key, e)
                data["errors"][key] = str(e)
                data[key] = []
            except Exception as e:
                logger.exception("Unexpected error in collector '%s'", key)
                data["errors"][key] = str(e)
                data[key] = []

    _cross_reference(data)

    # ── Uncovered ARNs (filter mode only) ──────────────────────────
    # When a Resource Group or Tag filter was applied, find ARNs that were
    # NOT returned by any typed collector and create generic entries for them.
    # This ensures ALL members of the Resource Group are visible.
    other_resources: List[Dict] = []
    if allow_arns is not None:
        typed_arns: Set[str] = set()
        for key in ("ec2", "rds", "elb", "lambda", "s3", "ecs"):
            for item in data.get(key) or []:
                if a := item.get("arn"):
                    typed_arns.add(a)

        uncovered = allow_arns - typed_arns
        if uncovered:
            logger.info(
                "%d ARN(s) not covered by typed collectors — fetching generically",
                len(uncovered),
            )
            try:
                other_resources = _generic_from_arns(session, region, uncovered)
            except Exception as e:
                logger.warning("_generic_from_arns failed: %s", e)
                data["errors"]["other"] = str(e)

    data["other_resources"] = other_resources

    # ── Summary ────────────────────────────────────────────────────
    in_subnets = sum(
        len(s.get("resources", []))
        for v in (data.get("networking") or [])
        for s in v.get("subnets", [])
    )
    in_vpcs = sum(len(v.get("direct_resources", [])) for v in (data.get("networking") or []))

    data["summary"] = {
        "vpcs":    len(data.get("networking") or []),
        "subnets": sum(len(v.get("subnets", [])) for v in (data.get("networking") or [])),
        "ec2":     len(data.get("ec2") or []),
        "rds":     len(data.get("rds") or []),
        "elb":     len(data.get("elb") or []),
        "lambda":  len(data.get("lambda") or []),
        "s3":      len(data.get("s3") or []),
        "ecs":     len(data.get("ecs") or []),
        "other":   len(other_resources),
        "total_in_tree": (
            in_subnets + in_vpcs
            + len(data.get("s3") or [])
            + len(data.get("ecs") or [])
            + len(other_resources)
        ),
    }
    return data
