"""Centralized ShopFlow permission matrix (Phase 2B).

A single source of truth for which permission string each role carries and
which endpoints require which permission. Tests in ``tests/test_rbac.py``
assert this matrix verbatim so a permission cannot silently gain or lose
scope.

Permission strings are namespaced ``<domain>:<action>``. ``:read`` covers
listing + detail GETs, ``:write`` covers create/update/state-changing ops,
``<domain>:manage`` is the administrative grant for that domain.
"""

from __future__ import annotations

# --- Domains ---------------------------------------------------------------
# billing/invoices/customers seen by a cashier at their counter
SALES_READ = "sales:read"
SALES_WRITE = "sales:write"
# product catalog
CATALOG_READ = "catalog:read"
CATALOG_WRITE = "catalog:write"
# customer records
CUSTOMERS_READ = "customers:read"
CUSTOMERS_WRITE = "customers:write"
# loyalty accounts + rules
LOYALTY_READ = "loyalty:read"
LOYALTY_WRITE = "loyalty:write"
# operational + financial reports (sensitive)
REPORTS_READ = "reports:read"
# counter activate/deactivate
COUNTERS_MANAGE = "counters:manage"
# employee add/disable/reset/assign
EMPLOYEES_MANAGE = "employees:manage"
# shop configuration, pricing, loyalty settings
SETTINGS_WRITE = "settings:write"
# audit log access
AUDIT_READ = "audit:read"

ALL_PERMISSIONS: tuple[str, ...] = (
    SALES_READ,
    SALES_WRITE,
    CATALOG_READ,
    CATALOG_WRITE,
    CUSTOMERS_READ,
    CUSTOMERS_WRITE,
    LOYALTY_READ,
    LOYALTY_WRITE,
    REPORTS_READ,
    COUNTERS_MANAGE,
    EMPLOYEES_MANAGE,
    SETTINGS_WRITE,
    AUDIT_READ,
)

# --- Role → permission set --------------------------------------------------
# The matrix is intentionally explicit (no wildcards) so a code review reads
# exactly what each role can do. `manage` implies the matching read/write.
OWNER_PERMISSIONS: tuple[str, ...] = ALL_PERMISSIONS

MANAGER_PERMISSIONS: tuple[str, ...] = (
    SALES_READ,
    SALES_WRITE,
    CATALOG_READ,
    CATALOG_WRITE,
    CUSTOMERS_READ,
    CUSTOMERS_WRITE,
    LOYALTY_READ,
    LOYALTY_WRITE,
    REPORTS_READ,
    # counters:manage, employees:manage, settings:write, audit:read are
    # owner-only by default; a manager can be granted employees:manage
    # explicitly through its role.permissions row.
)

CASHIER_PERMISSIONS: tuple[str, ...] = (
    SALES_READ,
    SALES_WRITE,
    CATALOG_READ,
    CUSTOMERS_READ,  # lookup only at the till
    LOYALTY_READ,
    # No reports:read, catalog:write, customers:write, loyalty:write,
    # or any :manage permission.
)

ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "owner": OWNER_PERMISSIONS,
    "manager": MANAGER_PERMISSIONS,
    "cashier": CASHIER_PERMISSIONS,
}

# Human-readable names for the three system roles, seeded into roles.name_*.
ROLE_NAMES: dict[str, tuple[str, str]] = {
    "owner": ("Shop Owner", "দোকান মালিক"),
    "manager": ("Shop Manager", "দোকান ম্যানেজার"),
    "cashier": ("Cashier", "ক্যাশিয়ার"),
}


def permissions_for_role(role_code: str) -> list[str]:
    """Permissions a role carries, or ``[]`` for an unknown code."""
    return sorted(set(ROLE_PERMISSIONS.get(role_code, ())))
