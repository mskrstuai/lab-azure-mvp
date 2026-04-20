"""AWS resource inventory API.

Read-only endpoints that use the default boto3 credential chain
(env vars, shared credentials, AWS_PROFILE, or an attached role) to list a
curated set of services useful for migration planning.

This is intentionally lightweight: we call ``list_*`` / ``describe_*`` with
sensible defaults and truncate large collections so the frontend stays
responsive.  Any per-service failure is captured in the response rather
than aborting the whole scan, which matches how Ops teams iterate on a
multi-account inventory.

When an AWS Resource Group is specified, we expand the group via
``resource-groups:ListGroupResources`` to an ARN allow-list and filter each
per-service result in memory.  That keeps per-service permissions unchanged
and lets the planner focus on the exact workload scope the user cares about.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
except ImportError:  # pragma: no cover - boto3 is declared in requirements.txt
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = ClientError = NoCredentialsError = Exception  # type: ignore[assignment]
    Config = None  # type: ignore[assignment]


router = APIRouter(prefix="/aws", tags=["aws"])


MAX_ITEMS_PER_SERVICE = 100


def _require_boto3() -> None:
    if boto3 is None:
        raise HTTPException(
            status_code=503,
            detail="boto3 is not installed on the backend. Add it to requirements.txt and reinstall.",
        )


def _build_session(region: Optional[str] = None):
    """Build a boto3 Session using the default credential chain.

    Resolution order (highest wins):
      1. Static keys in env (``AWS_ACCESS_KEY_ID``/``AWS_SECRET_ACCESS_KEY``)
         — boto3 picks these up automatically from the default chain.
      2. ``AWS_PROFILE`` — only honoured when static keys are absent, because
         otherwise a misconfigured profile (e.g. SSO-only or a profile that
         isn't in ``~/.aws/credentials``) hides the working env keys.
      3. Default chain (instance metadata, SSO, config file, etc.)
    """
    _require_boto3()
    access_key = os.getenv("AWS_ACCESS_KEY_ID")
    profile = os.getenv("AWS_PROFILE")
    kwargs: Dict[str, Any] = {}
    # If the user set static keys in the env, let the default chain use them
    # and ignore AWS_PROFILE.  Mixing the two is the #1 source of
    # "No AWS credentials" errors for this backend.
    if not access_key and profile:
        kwargs["profile_name"] = profile
    if region:
        kwargs["region_name"] = region
    try:
        return boto3.session.Session(**kwargs)
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Failed to build AWS session: {e}") from e


def _client(session, service: str, region: Optional[str] = None):
    cfg = (
        Config(retries={"max_attempts": 3, "mode": "standard"}, read_timeout=20, connect_timeout=5)
        if Config
        else None
    )
    return session.client(service, region_name=region, config=cfg)


def _partition_for(region: str) -> str:
    if region.startswith("cn-"):
        return "aws-cn"
    if region.startswith("us-gov-"):
        return "aws-us-gov"
    return "aws"


def _caller_context(session, region: str) -> Dict[str, str]:
    """Resolve account id + partition once per scan so collectors can build ARNs."""
    try:
        ident = session.client("sts").get_caller_identity()
        account = ident.get("Account") or ""
    except (ClientError, BotoCoreError, NoCredentialsError):
        account = ""
    return {"account_id": account, "partition": _partition_for(region), "region": region}


# ---------------------------------------------------------------------------
# Per-service collectors. Each returns a list[dict] with the key columns the
# migration planner cares about.  Every row also includes an ``arn`` key so
# the caller can filter against an AWS Resource Group membership set.
# ---------------------------------------------------------------------------


def _list_ec2(session, ctx: Dict[str, str]) -> List[Dict[str, Any]]:
    region = ctx["region"]
    partition, account = ctx["partition"], ctx["account_id"]
    ec2 = _client(session, "ec2", region)
    rows: List[Dict[str, Any]] = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate(PaginationConfig={"MaxItems": MAX_ITEMS_PER_SERVICE}):
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", []) or []}
                iid = inst.get("InstanceId")
                rows.append({
                    "arn": f"arn:{partition}:ec2:{region}:{account}:instance/{iid}" if iid and account else "",
                    "id": iid,
                    "name": tags.get("Name", ""),
                    "state": (inst.get("State") or {}).get("Name"),
                    "type": inst.get("InstanceType"),
                    "az": (inst.get("Placement") or {}).get("AvailabilityZone"),
                    "vpc": inst.get("VpcId"),
                    "private_ip": inst.get("PrivateIpAddress"),
                    "public_ip": inst.get("PublicIpAddress"),
                    "launch_time": str(inst.get("LaunchTime") or ""),
                })
    return rows


def _list_rds(session, ctx: Dict[str, str]) -> List[Dict[str, Any]]:
    rds = _client(session, "rds", ctx["region"])
    rows: List[Dict[str, Any]] = []
    paginator = rds.get_paginator("describe_db_instances")
    for page in paginator.paginate(PaginationConfig={"MaxItems": MAX_ITEMS_PER_SERVICE}):
        for db in page.get("DBInstances", []):
            rows.append({
                "arn": db.get("DBInstanceArn", ""),
                "id": db.get("DBInstanceIdentifier"),
                "engine": db.get("Engine"),
                "engine_version": db.get("EngineVersion"),
                "class": db.get("DBInstanceClass"),
                "status": db.get("DBInstanceStatus"),
                "storage_gb": db.get("AllocatedStorage"),
                "multi_az": db.get("MultiAZ"),
                "endpoint": (db.get("Endpoint") or {}).get("Address"),
            })
    return rows


def _list_s3(session, ctx: Dict[str, str]) -> List[Dict[str, Any]]:
    partition = ctx["partition"]
    # S3 is global, but we still report the bucket's home region.
    s3 = _client(session, "s3")
    resp = s3.list_buckets()
    rows: List[Dict[str, Any]] = []
    for b in (resp.get("Buckets") or [])[:MAX_ITEMS_PER_SERVICE]:
        name = b.get("Name")
        bucket_region = ""
        try:
            loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint")
            bucket_region = loc or "us-east-1"
        except (ClientError, BotoCoreError):
            bucket_region = "?"
        rows.append({
            "arn": f"arn:{partition}:s3:::{name}" if name else "",
            "name": name,
            "region": bucket_region,
            "created": str(b.get("CreationDate") or ""),
        })
    return rows


def _list_lambda(session, ctx: Dict[str, str]) -> List[Dict[str, Any]]:
    client = _client(session, "lambda", ctx["region"])
    rows: List[Dict[str, Any]] = []
    paginator = client.get_paginator("list_functions")
    for page in paginator.paginate(PaginationConfig={"MaxItems": MAX_ITEMS_PER_SERVICE}):
        for fn in page.get("Functions", []):
            rows.append({
                "arn": fn.get("FunctionArn", ""),
                "name": fn.get("FunctionName"),
                "runtime": fn.get("Runtime"),
                "memory_mb": fn.get("MemorySize"),
                "timeout_s": fn.get("Timeout"),
                "last_modified": fn.get("LastModified"),
            })
    return rows


def _list_vpc(session, ctx: Dict[str, str]) -> List[Dict[str, Any]]:
    region = ctx["region"]
    partition, account = ctx["partition"], ctx["account_id"]
    ec2 = _client(session, "ec2", region)
    rows: List[Dict[str, Any]] = []
    resp = ec2.describe_vpcs()
    for vpc in (resp.get("Vpcs") or [])[:MAX_ITEMS_PER_SERVICE]:
        tags = {t["Key"]: t["Value"] for t in vpc.get("Tags", []) or []}
        vid = vpc.get("VpcId")
        rows.append({
            "arn": f"arn:{partition}:ec2:{region}:{account}:vpc/{vid}" if vid and account else "",
            "id": vid,
            "name": tags.get("Name", ""),
            "cidr": vpc.get("CidrBlock"),
            "is_default": vpc.get("IsDefault"),
            "state": vpc.get("State"),
        })
    return rows


def _list_elb(session, ctx: Dict[str, str]) -> List[Dict[str, Any]]:
    elbv2 = _client(session, "elbv2", ctx["region"])
    rows: List[Dict[str, Any]] = []
    paginator = elbv2.get_paginator("describe_load_balancers")
    for page in paginator.paginate(PaginationConfig={"MaxItems": MAX_ITEMS_PER_SERVICE}):
        for lb in page.get("LoadBalancers", []):
            rows.append({
                "arn": lb.get("LoadBalancerArn", ""),
                "name": lb.get("LoadBalancerName"),
                "type": lb.get("Type"),
                "scheme": lb.get("Scheme"),
                "dns": lb.get("DNSName"),
                "vpc": lb.get("VpcId"),
                "state": (lb.get("State") or {}).get("Code"),
            })
    return rows


def _list_dynamodb(session, ctx: Dict[str, str]) -> List[Dict[str, Any]]:
    region = ctx["region"]
    partition, account = ctx["partition"], ctx["account_id"]
    ddb = _client(session, "dynamodb", region)
    rows: List[Dict[str, Any]] = []
    paginator = ddb.get_paginator("list_tables")
    names: List[str] = []
    for page in paginator.paginate(PaginationConfig={"MaxItems": MAX_ITEMS_PER_SERVICE}):
        names.extend(page.get("TableNames") or [])
    for name in names[:MAX_ITEMS_PER_SERVICE]:
        arn = f"arn:{partition}:dynamodb:{region}:{account}:table/{name}" if account else ""
        try:
            desc = ddb.describe_table(TableName=name).get("Table", {})
            rows.append({
                "arn": desc.get("TableArn", arn),
                "name": name,
                "status": desc.get("TableStatus"),
                "items": desc.get("ItemCount"),
                "size_bytes": desc.get("TableSizeBytes"),
                "billing_mode": (desc.get("BillingModeSummary") or {}).get("BillingMode", "PROVISIONED"),
            })
        except (ClientError, BotoCoreError):
            rows.append({"arn": arn, "name": name, "status": "?", "items": None, "size_bytes": None, "billing_mode": "?"})
    return rows


def _list_ecs(session, ctx: Dict[str, str]) -> List[Dict[str, Any]]:
    ecs = _client(session, "ecs", ctx["region"])
    rows: List[Dict[str, Any]] = []
    clusters = ecs.list_clusters(maxResults=MAX_ITEMS_PER_SERVICE).get("clusterArns", []) or []
    if not clusters:
        return rows
    described = ecs.describe_clusters(clusters=clusters).get("clusters", [])
    for c in described:
        rows.append({
            "arn": c.get("clusterArn", ""),
            "name": c.get("clusterName"),
            "status": c.get("status"),
            "running_tasks": c.get("runningTasksCount"),
            "pending_tasks": c.get("pendingTasksCount"),
            "services": c.get("activeServicesCount"),
            "instances": c.get("registeredContainerInstancesCount"),
        })
    return rows


SERVICE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "ec2": {
        "label": "EC2 Instances",
        "columns": ["id", "name", "state", "type", "az", "vpc", "private_ip", "public_ip", "launch_time"],
        "collector": _list_ec2,
    },
    "rds": {
        "label": "RDS Instances",
        "columns": ["id", "engine", "engine_version", "class", "status", "storage_gb", "multi_az", "endpoint"],
        "collector": _list_rds,
    },
    "s3": {
        "label": "S3 Buckets",
        "columns": ["name", "region", "created"],
        "collector": _list_s3,
    },
    "lambda": {
        "label": "Lambda Functions",
        "columns": ["name", "runtime", "memory_mb", "timeout_s", "last_modified"],
        "collector": _list_lambda,
    },
    "vpc": {
        "label": "VPCs",
        "columns": ["id", "name", "cidr", "is_default", "state"],
        "collector": _list_vpc,
    },
    "elb": {
        "label": "Load Balancers (ALB/NLB)",
        "columns": ["name", "type", "scheme", "dns", "vpc", "state"],
        "collector": _list_elb,
    },
    "dynamodb": {
        "label": "DynamoDB Tables",
        "columns": ["name", "status", "items", "size_bytes", "billing_mode"],
        "collector": _list_dynamodb,
    },
    "ecs": {
        "label": "ECS Clusters",
        "columns": ["name", "status", "running_tasks", "pending_tasks", "services", "instances"],
        "collector": _list_ecs,
    },
}


# ---------------------------------------------------------------------------
# Resource Groups helpers
# ---------------------------------------------------------------------------


def _list_resource_groups(session, region: str) -> List[Dict[str, Any]]:
    """Return ``[{name, arn, description}]`` for the specified region."""
    client = _client(session, "resource-groups", region)
    groups: List[Dict[str, Any]] = []
    paginator = client.get_paginator("list_groups")
    for page in paginator.paginate():
        # API has two shapes depending on boto3 version — handle both.
        for g in page.get("GroupIdentifiers", []) or []:
            groups.append({
                "name": g.get("GroupName"),
                "arn": g.get("GroupArn"),
                "description": "",
            })
        for g in page.get("Groups", []) or []:
            groups.append({
                "name": g.get("Name") or g.get("GroupName"),
                "arn": g.get("GroupArn"),
                "description": g.get("Description", ""),
            })
    # De-duplicate while preserving order (pagination + dual-shape).
    seen: Set[str] = set()
    unique: List[Dict[str, Any]] = []
    for g in groups:
        key = g.get("arn") or g.get("name") or ""
        if key and key not in seen:
            seen.add(key)
            unique.append(g)
    unique.sort(key=lambda g: (g.get("name") or "").lower())
    return unique


def _resource_group_arns(session, region: str, group_name: str) -> Set[str]:
    """Expand a Resource Group to the set of member resource ARNs."""
    client = _client(session, "resource-groups", region)
    arns: Set[str] = set()
    paginator = client.get_paginator("list_group_resources")
    for page in paginator.paginate(Group=group_name):
        for r in page.get("ResourceIdentifiers", []) or []:
            if arn := r.get("ResourceArn"):
                arns.add(arn)
        for r in page.get("Resources", []) or []:
            ident = r.get("Identifier") or {}
            if arn := ident.get("ResourceArn"):
                arns.add(arn)
    return arns


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status")
def aws_status() -> Dict[str, Any]:
    """Report whether the backend can call AWS with the current credentials."""
    if boto3 is None:
        return {"ready": False, "reason": "boto3 not installed", "identity": None}
    has_static_keys = bool(os.getenv("AWS_ACCESS_KEY_ID"))
    env_profile = os.getenv("AWS_PROFILE")
    try:
        session = _build_session()
        # Introspect which credential provider actually fired so the UI can
        # tell the user "yes, your env keys are being used" vs "we fell back
        # to the SSO profile".
        creds = session.get_credentials()
        method = creds.method if creds else None  # e.g. "env", "shared-credentials-file", "sso"
        sts = session.client("sts")
        ident = sts.get_caller_identity()
        return {
            "ready": True,
            "identity": {
                "account": ident.get("Account"),
                "arn": ident.get("Arn"),
                "user_id": ident.get("UserId"),
            },
            "default_region": session.region_name or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
            "profile": env_profile if not has_static_keys else None,
            "credential_source": method,
        }
    except NoCredentialsError:
        reason = (
            "No AWS credentials found. Set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY "
            "in backend/.env or configure a working AWS profile."
        )
        if env_profile and not has_static_keys:
            reason += (
                f" (AWS_PROFILE='{env_profile}' is set but the profile is missing "
                "from ~/.aws/credentials — remove AWS_PROFILE from .env if you "
                "meant to use static keys.)"
            )
        return {"ready": False, "reason": reason, "identity": None}
    except (ClientError, BotoCoreError) as e:
        return {"ready": False, "reason": f"AWS call failed: {e}", "identity": None}


@router.get("/services")
def list_services() -> Dict[str, Any]:
    """Return the catalog of services + column metadata the scanner supports."""
    return {
        "services": [
            {"key": key, "label": meta["label"], "columns": meta["columns"]}
            for key, meta in SERVICE_REGISTRY.items()
        ]
    }


@router.get("/regions")
def list_regions() -> Dict[str, Any]:
    """Enumerate available regions via EC2 describe_regions."""
    _require_boto3()
    try:
        session = _build_session(region=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
        ec2 = session.client("ec2")
        resp = ec2.describe_regions(AllRegions=False)
        regions = sorted([r["RegionName"] for r in resp.get("Regions", [])])
        return {"regions": regions}
    except NoCredentialsError:
        raise HTTPException(status_code=401, detail="No AWS credentials. Configure AWS_PROFILE or keys.")
    except (ClientError, BotoCoreError) as e:
        raise HTTPException(status_code=502, detail=f"Failed to list regions: {e}")


@router.get("/resource-groups")
def list_resource_groups(region: Optional[str] = None) -> Dict[str, Any]:
    """List AWS Resource Groups in the given region."""
    _require_boto3()
    effective_region = (region or os.getenv("AWS_DEFAULT_REGION") or "us-east-1").strip()
    try:
        session = _build_session(region=effective_region)
        return {"region": effective_region, "groups": _list_resource_groups(session, effective_region)}
    except NoCredentialsError:
        raise HTTPException(status_code=401, detail="No AWS credentials. Configure AWS_PROFILE or keys.")
    except (ClientError, BotoCoreError) as e:
        raise HTTPException(status_code=502, detail=f"Failed to list resource groups: {e}")


@router.get("/resource-groups/{group_name}")
def describe_resource_group(group_name: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Return the ARNs contained in the named Resource Group, grouped by service key."""
    _require_boto3()
    effective_region = (region or os.getenv("AWS_DEFAULT_REGION") or "us-east-1").strip()
    try:
        session = _build_session(region=effective_region)
        arns = sorted(_resource_group_arns(session, effective_region, group_name))
    except NoCredentialsError:
        raise HTTPException(status_code=401, detail="No AWS credentials.")
    except (ClientError, BotoCoreError) as e:
        raise HTTPException(status_code=502, detail=f"Failed to expand resource group: {e}")

    # Best-effort bucket by service key for the UI preview.
    buckets: Dict[str, List[str]] = {k: [] for k in SERVICE_REGISTRY}
    buckets["other"] = []
    for arn in arns:
        svc_key = _classify_arn(arn)
        buckets.setdefault(svc_key, []).append(arn)
    return {
        "group": group_name,
        "region": effective_region,
        "total": len(arns),
        "by_service": buckets,
    }


def _classify_arn(arn: str) -> str:
    """Map an ARN to one of our per-service collector keys (best-effort)."""
    parsed = _parse_arn(arn)
    service = parsed["service"]
    rtype = parsed["resource_type"]
    if service == "ec2":
        if rtype == "instance":
            return "ec2"
        if rtype == "vpc":
            return "vpc"
        return "ec2"
    if service == "rds":
        return "rds"
    if service == "s3":
        return "s3"
    if service == "lambda":
        return "lambda"
    if service == "elasticloadbalancing":
        return "elb"
    if service == "dynamodb":
        return "dynamodb"
    if service == "ecs":
        return "ecs"
    return "other"


# ---------------------------------------------------------------------------
# ARN parsing + label maps for the "flat Resource Group member list" flow.
# ---------------------------------------------------------------------------


def _parse_arn(arn: str) -> Dict[str, str]:
    """Split an ARN into components.

    AWS ARN grammar: ``arn:partition:service:region:account:resource``
    where ``resource`` is either ``type/id``, ``type:id``, or just ``id``.
    """
    try:
        parts = arn.split(":", 5)
        if len(parts) < 6:
            return {
                "arn": arn,
                "partition": "",
                "service": "",
                "region": "",
                "account": "",
                "resource_type": "",
                "resource_id": arn,
                "raw_resource": arn,
            }
        _, partition, service, region, account, resource = parts
    except Exception:
        return {
            "arn": arn,
            "partition": "",
            "service": "",
            "region": "",
            "account": "",
            "resource_type": "",
            "resource_id": arn,
            "raw_resource": arn,
        }

    if "/" in resource:
        rtype, _, rid = resource.partition("/")
    elif ":" in resource:
        rtype, _, rid = resource.partition(":")
    else:
        rtype, rid = "", resource
    return {
        "arn": arn,
        "partition": partition,
        "service": service,
        "region": region,
        "account": account,
        "resource_type": rtype,
        "resource_id": rid or resource,
        "raw_resource": resource,
    }


SERVICE_DISPLAY_NAMES: Dict[str, str] = {
    "ec2": "EC2",
    "rds": "RDS",
    "s3": "S3",
    "lambda": "Lambda",
    "elasticloadbalancing": "ELB",
    "dynamodb": "DynamoDB",
    "ecs": "ECS",
    "eks": "EKS",
    "ecr": "ECR",
    "iam": "IAM",
    "cloudformation": "CloudFormation",
    "cloudwatch": "CloudWatch",
    "logs": "CloudWatch Logs",
    "events": "EventBridge",
    "sns": "SNS",
    "sqs": "SQS",
    "kms": "KMS",
    "secretsmanager": "SecretsManager",
    "ssm": "SSM",
    "states": "StepFunctions",
    "apigateway": "API Gateway",
    "route53": "Route53",
    "cloudfront": "CloudFront",
    "autoscaling": "AutoScaling",
    "elasticache": "ElastiCache",
    "efs": "EFS",
    "glacier": "S3 Glacier",
    "athena": "Athena",
    "glue": "Glue",
    "redshift": "Redshift",
    "emr": "EMR",
    "batch": "Batch",
    "sagemaker": "SageMaker",
    "codebuild": "CodeBuild",
    "codepipeline": "CodePipeline",
    "codedeploy": "CodeDeploy",
    "codecommit": "CodeCommit",
}


def _service_display(service: str) -> str:
    if not service:
        return ""
    return SERVICE_DISPLAY_NAMES.get(service, service.upper())


def _format_resource_type(resource_type: str) -> str:
    """``launch-template`` → ``LaunchTemplate``, ``db`` → ``DBInstance``, etc."""
    if not resource_type:
        return ""
    # A few AWS-specific aliases where the bare ARN type is unhelpful.
    aliases = {
        "db": "DBInstance",
        "cluster": "Cluster",
        "loadbalancer": "LoadBalancer",
        "targetgroup": "TargetGroup",
        "listener": "Listener",
        "function": "Function",
        "table": "Table",
        "role": "Role",
        "policy": "Policy",
        "stack": "Stack",
        "vpc": "VPC",
        "dhcp-options": "DHCPOptions",
        "internet-gateway": "InternetGateway",
        "nat-gateway": "NATGateway",
        "vpc-endpoint": "VPCEndpoint",
        "network-acl": "NetworkACL",
        "network-interface": "NetworkInterface",
        "elastic-ip": "ElasticIP",
    }
    if resource_type in aliases:
        return aliases[resource_type]
    return "".join(p[:1].upper() + p[1:] for p in resource_type.replace("_", "-").split("-") if p)


def _fetch_tags_for_arns(session, region: str, arns: List[str]) -> Dict[str, Dict[str, str]]:
    """Batch-fetch tags for a list of ARNs via resourcegroupstaggingapi.

    Returns ``{arn: {TagKey: TagValue}}``.  Unsupported ARNs are simply absent.
    Any API errors are swallowed per-batch so the caller still gets the
    resources without tags rather than an empty response.
    """
    if not arns:
        return {}
    client = _client(session, "resourcegroupstaggingapi", region)
    out: Dict[str, Dict[str, str]] = {}
    # get_resources accepts up to 100 ARNs per call.
    for i in range(0, len(arns), 100):
        batch = arns[i : i + 100]
        try:
            resp = client.get_resources(ResourceARNList=batch)
        except (ClientError, BotoCoreError):
            continue
        for mapping in resp.get("ResourceTagMappingList", []) or []:
            arn = mapping.get("ResourceARN")
            if not arn:
                continue
            out[arn] = {t["Key"]: t.get("Value", "") for t in mapping.get("Tags", []) or []}
    return out


def _scan_resource_group_members(
    session, region: str, group_name: str
) -> Dict[str, Any]:
    """Return every resource in the named Resource Group as a flat list.

    Uses only ``resource-groups:ListGroupResources`` (already required) plus
    ``tag:GetResources`` to enrich with Name tags.  This path surfaces *all*
    resource kinds AWS knows about — SecurityGroup, Subnet, RouteTable,
    LaunchTemplate, and so on — rather than the 8 per-service collectors.
    """
    arns = sorted(_resource_group_arns(session, region, group_name))
    tags_by_arn = _fetch_tags_for_arns(session, region, arns)

    members: List[Dict[str, Any]] = []
    for arn in arns:
        parsed = _parse_arn(arn)
        tags = tags_by_arn.get(arn, {})
        name = tags.get("Name") or ""
        # S3 ARNs (``arn:aws:s3:::<bucket>``) have no explicit resource type —
        # they collapse to id only.  Synthesize it so the UI stays consistent.
        rtype = parsed["resource_type"]
        if not rtype and parsed["service"] == "s3":
            rtype = "bucket"
        members.append({
            "arn": arn,
            "id": parsed["resource_id"],
            "name": name,
            "service": parsed["service"],
            "service_label": _service_display(parsed["service"]),
            "resource_type": rtype,
            "resource_type_label": _format_resource_type(rtype),
            "region": parsed["region"] or region,
            "account": parsed["account"],
            "tags": tags,
            "tag_count": len(tags),
        })

    members.sort(
        key=lambda m: (
            m["service_label"].lower(),
            m["resource_type_label"].lower(),
            (m["name"] or m["id"]).lower(),
        )
    )

    # Compact per-service-label bucket for the summary banner.
    buckets: Dict[str, int] = {}
    for m in members:
        key = f"{m['service_label']} {m['resource_type_label']}".strip() or m["service"] or "other"
        buckets[key] = buckets.get(key, 0) + 1

    return {
        "region": region,
        "resource_group": group_name,
        "resource_group_member_count": len(arns),
        "total": len(members),
        "members": members,
        "buckets": [
            {"label": k, "count": v}
            for k, v in sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    }


@router.post("/scan")
def scan_resources(request: dict) -> Dict[str, Any]:
    """Scan the selected services in a region and return per-service tables.

    Request body::

        {
          "region": "us-east-1",
          "services": ["ec2", "rds", "s3"],   # optional, defaults to all
          "resource_group": "my-prod-stack"   # optional; filters scan to members
        }
    """
    _require_boto3()
    region = (request.get("region") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1").strip()
    requested = request.get("services") or list(SERVICE_REGISTRY.keys())
    resource_group = (request.get("resource_group") or "").strip() or None

    unknown = [s for s in requested if s not in SERVICE_REGISTRY]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown services: {', '.join(unknown)}")

    session = _build_session(region=region)

    # quick credential sanity-check so the UI gets a single clean error
    try:
        session.client("sts").get_caller_identity()
    except NoCredentialsError:
        raise HTTPException(status_code=401, detail="No AWS credentials. Configure AWS_PROFILE or keys.")
    except (ClientError, BotoCoreError) as e:
        raise HTTPException(status_code=401, detail=f"AWS credentials rejected: {e}")

    # --- Resource Group path: show *every* member (all types) ---
    # This uses resource-groups + resourcegroupstaggingapi, so it is not
    # limited to the 8 per-service collectors and surfaces SecurityGroup,
    # Subnet, RouteTable, LaunchTemplate, etc.  The per-service path below is
    # only used when the user has not picked a group.
    if resource_group:
        try:
            return _scan_resource_group_members(session, region, resource_group)
        except (ClientError, BotoCoreError) as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to expand resource group '{resource_group}': {e}",
            )

    ctx = _caller_context(session, region)

    # Resolve Resource Group membership up front (if requested).
    rg_arns: Optional[Set[str]] = None
    rg_error: Optional[str] = None
    if resource_group:
        try:
            rg_arns = _resource_group_arns(session, region, resource_group)
        except (ClientError, BotoCoreError) as e:
            rg_error = f"Failed to expand resource group '{resource_group}': {e}"
            rg_arns = set()

    def _run(service: str) -> Dict[str, Any]:
        meta = SERVICE_REGISTRY[service]
        collector: Callable[[Any, Dict[str, str]], List[Dict[str, Any]]] = meta["collector"]
        try:
            items = collector(session, ctx)
            total_before = len(items)
            if rg_arns is not None:
                items = [it for it in items if it.get("arn") and it["arn"] in rg_arns]
            return {
                "service": service,
                "items": items,
                "count": len(items),
                "total_before_filter": total_before,
                "error": None,
            }
        except (ClientError, BotoCoreError) as e:
            return {"service": service, "items": [], "count": 0, "total_before_filter": 0, "error": str(e)}
        except Exception as e:  # pragma: no cover - defensive
            return {
                "service": service,
                "items": [],
                "count": 0,
                "total_before_filter": 0,
                "error": f"{type(e).__name__}: {e}",
            }

    results: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(requested) or 1)) as pool:
        futures = {pool.submit(_run, svc): svc for svc in requested}
        for fut in as_completed(futures):
            res = fut.result()
            results[res["service"]] = res

    response: Dict[str, Any] = {
        "region": region,
        "resource_group": resource_group,
        "resource_group_member_count": len(rg_arns) if rg_arns is not None else None,
        "resource_group_error": rg_error,
        "services": [
            {
                "key": svc,
                "label": SERVICE_REGISTRY[svc]["label"],
                "columns": SERVICE_REGISTRY[svc]["columns"],
                **results.get(
                    svc,
                    {"items": [], "count": 0, "total_before_filter": 0, "error": "no result"},
                ),
            }
            for svc in requested
        ],
    }
    return response
