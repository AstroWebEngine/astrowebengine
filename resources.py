"""
Resource Abstraction Layer for the AstroWebEngine.

Handles both single-resource (e.g., credits only) and multi-resource
(e.g., metal/crystal/deuterium) economies through a unified interface.

Resource costs can be:
- Scalar (int/float): treated as the primary resource (single-resource mode)
- Dict: {"metal": 100, "crystal": 50, "deuterium": 25} (multi-resource mode)

All functions gracefully handle both formats so game systems don't need
to know which resource model is active.
"""

import json
from game_definition import get_game_definition


def get_resource_model() -> str:
    """Get the active resource model: 'single' or 'multi'."""
    defn = get_game_definition()
    return defn.get("engine", {}).get("resource_model", "single")


def get_resource_types() -> list:
    """Get the list of resource types for the active game definition."""
    defn = get_game_definition()
    return defn.get("engine", {}).get("resource_types", ["credits"])


def get_primary_resource() -> str:
    """Get the primary (or only) resource type."""
    types = get_resource_types()
    return types[0] if types else "credits"


# ---------------------------------------------------------------------------
# Cost normalization — convert between scalar and dict cost formats
# ---------------------------------------------------------------------------

def normalize_cost(cost) -> dict:
    """Convert any cost format to a resource dict.

    - int/float → {primary_resource: amount}
    - dict → returned as-is
    - None/0 → {primary_resource: 0}
    """
    if cost is None:
        return {get_primary_resource(): 0}
    if isinstance(cost, (int, float)):
        return {get_primary_resource(): cost}
    if isinstance(cost, dict):
        return dict(cost)
    return {get_primary_resource(): 0}


def denormalize_cost(cost_dict: dict):
    """Convert a resource dict back to scalar if in single-resource mode.

    Single-resource mode: returns the scalar value (int or float)
    Multi-resource mode: returns the dict as-is
    """
    if get_resource_model() == "single":
        primary = get_primary_resource()
        return cost_dict.get(primary, 0)
    return cost_dict


def scale_cost(cost, multiplier: float):
    """Scale a cost (scalar or dict) by a multiplier."""
    if isinstance(cost, (int, float)):
        return cost * multiplier
    if isinstance(cost, dict):
        return {k: v * multiplier for k, v in cost.items()}
    return cost


def add_costs(a, b):
    """Add two costs together (scalar or dict)."""
    a_dict = normalize_cost(a)
    b_dict = normalize_cost(b)
    result = dict(a_dict)
    for k, v in b_dict.items():
        result[k] = result.get(k, 0) + v
    return denormalize_cost(result)


def multiply_cost(cost, count: int):
    """Multiply a cost by count (for batch ship production etc.)."""
    return scale_cost(cost, count)


def total_cost_value(cost) -> float:
    """Get the total value of a cost (sum of all resources). Used for time calculations."""
    if isinstance(cost, (int, float)):
        return float(cost)
    if isinstance(cost, dict):
        return sum(cost.values())
    return 0.0


# ---------------------------------------------------------------------------
# User resource management — abstraction over User.credits / resources_json
# ---------------------------------------------------------------------------

def get_user_resources(user) -> dict:
    """Get all resources for a user as a dict.

    Single-resource mode: {"credits": user.credits}
    Multi-resource mode: reads from user.resources_json with credits fallback
    """
    if get_resource_model() == "single":
        primary = get_primary_resource()
        return {primary: getattr(user, 'credits', 0) or 0}

    # Multi-resource: read from JSON column if available
    if hasattr(user, 'resources_json') and user.resources_json:
        try:
            resources = json.loads(user.resources_json)
        except (json.JSONDecodeError, TypeError):
            resources = {}
    else:
        resources = {}

    # Ensure all resource types exist
    for rt in get_resource_types():
        if rt not in resources:
            resources[rt] = getattr(user, 'credits', 0) if rt == "credits" else 0

    return resources


def set_user_resources(user, resources: dict):
    """Set all resources for a user.

    Single-resource mode: sets user.credits
    Multi-resource mode: writes to user.resources_json
    """
    if get_resource_model() == "single":
        primary = get_primary_resource()
        user.credits = resources.get(primary, 0)
        return

    # Multi-resource: store in JSON column
    if hasattr(user, 'resources_json'):
        user.resources_json = json.dumps(resources)
    # Also sync credits column for backward compat
    if "credits" in resources:
        user.credits = resources["credits"]


def seed_starting_resources(user):
    """Give a brand-new user a starting balance in multi-resource economies.

    Single-resource mode is a no-op (the User.credits default covers it). In
    multi-resource mode a fresh user otherwise has 0 of every resource (credits
    isn't a resource type), so they — and bots — can't build anything until
    hourly income trickles in. The amount comes from engine.starting_resources
    (a dict {metal: N, ...} or a scalar applied to each type), else a default."""
    if get_resource_model() != "multi":
        return
    from game_definition import get_game_definition
    configured = get_game_definition().get("engine", {}).get("starting_resources")
    types = get_resource_types()
    if isinstance(configured, dict):
        res = {rt: configured.get(rt, 0) for rt in types}
    elif isinstance(configured, (int, float)):
        res = {rt: configured for rt in types}
    else:
        # Default: a modest stash, weighted toward the primary resource.
        res = {rt: (2000 if i == 0 else 1000) for i, rt in enumerate(types)}
    set_user_resources(user, res)


def can_afford(user, cost) -> bool:
    """Check if a user can afford a cost (scalar or dict)."""
    cost_dict = normalize_cost(cost)
    resources = get_user_resources(user)
    for resource_type, amount in cost_dict.items():
        if amount > 0 and resources.get(resource_type, 0) < amount:
            return False
    return True


def deduct_cost(user, cost):
    """Deduct a cost from a user's resources. Returns the deducted amount (normalized)."""
    cost_dict = normalize_cost(cost)
    resources = get_user_resources(user)
    for resource_type, amount in cost_dict.items():
        resources[resource_type] = resources.get(resource_type, 0) - amount
    set_user_resources(user, resources)
    return denormalize_cost(cost_dict)


def add_resources(user, income):
    """Add resources to a user (income, refund, loot, etc.)."""
    income_dict = normalize_cost(income)
    resources = get_user_resources(user)
    for resource_type, amount in income_dict.items():
        resources[resource_type] = resources.get(resource_type, 0) + amount
    set_user_resources(user, resources)


def format_cost(cost) -> str:
    """Format a cost for display. Single-resource: '500'. Multi: 'Metal: 100 | Crystal: 50'."""
    if isinstance(cost, (int, float)):
        return f"{int(cost):,}"
    if isinstance(cost, dict):
        if len(cost) == 1:
            return f"{int(list(cost.values())[0]):,}"
        parts = [f"{k.title()}: {int(v):,}" for k, v in cost.items() if v > 0]
        return " | ".join(parts)
    return "0"


def round_cost(cost, ndigits=0):
    """Round a cost (scalar or dict) for API serialization."""
    if isinstance(cost, (int, float)):
        return round(cost, ndigits) if ndigits else round(cost)
    if isinstance(cost, dict):
        return {k: (round(v, ndigits) if ndigits else round(v)) for k, v in cost.items()}
    return cost


def cost_to_json(cost) -> str:
    """Serialize a cost to JSON for database storage."""
    return json.dumps(normalize_cost(cost))


def cost_from_json(json_str: str):
    """Deserialize a cost from JSON database storage."""
    if not json_str:
        return 0
    try:
        data = json.loads(json_str)
        return denormalize_cost(data)
    except (json.JSONDecodeError, TypeError):
        return 0
