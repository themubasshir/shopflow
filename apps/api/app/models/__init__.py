"""Import every model so Alembic autogenerate and metadata.create_all see them."""

from app.models.audit import AuditLog, IdempotencyRecord
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
from app.models.sales import Customer, Invoice, InvoiceItem, Payment
from app.models.shop import Counter, Role, Shop, User

__all__ = [
    "AuditLog",
    "Category",
    "Counter",
    "Customer",
    "IdempotencyRecord",
    "Invoice",
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
]
