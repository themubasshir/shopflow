"""Import every model so Alembic autogenerate and metadata.create_all see them."""

from app.models.audit import AuditLog, IdempotencyRecord, InvoiceCounter
from app.models.catalog import (
    Category,
    MedicineBatch,
    MedicineDetail,
    Product,
    ProductUnit,
    Supplier,
)
from app.models.inventory import Purchase, PurchaseItem, StockMovement
from app.models.loyalty import (
    LoyaltyAccount,
    LoyaltyRedemption,
    LoyaltyRule,
    LoyaltyTransaction,
)
from app.models.sales import Customer, CustomerLedgerEntry, Invoice, InvoiceItem, Payment
from app.models.shop import AuthSession, Counter, Role, Shop, User, UserCounter

__all__ = [
    "AuditLog",
    "AuthSession",
    "Category",
    "Counter",
    "Customer",
    "CustomerLedgerEntry",
    "IdempotencyRecord",
    "Invoice",
    "InvoiceCounter",
    "InvoiceItem",
    "LoyaltyAccount",
    "LoyaltyRedemption",
    "LoyaltyRule",
    "LoyaltyTransaction",
    "MedicineBatch",
    "MedicineDetail",
    "Payment",
    "Product",
    "ProductUnit",
    "Purchase",
    "PurchaseItem",
    "Role",
    "Shop",
    "StockMovement",
    "Supplier",
    "User",
    "UserCounter",
]
