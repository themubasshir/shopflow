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
from app.models.inventory import (
    InvoiceBatchAllocation,
    Purchase,
    PurchaseItem,
    StockLot,
    StockMovement,
    SupplierLedger,
    SupplierProduct,
)
from app.models.loyalty import (
    LoyaltyAccount,
    LoyaltyRedemption,
    LoyaltyRule,
    LoyaltyTransaction,
)
from app.models.printing import CounterPrinter, Printer, PrintJob
from app.models.returns import (
    CustomerRefundSettlement,
    CustomerReturn,
    CustomerReturnLine,
    ReturnStockPortion,
    ReturnStockResolution,
    SupplierCreditNote,
)
from app.models.sales import Customer, CustomerLedgerEntry, Invoice, InvoiceItem, Payment
from app.models.shop import AuthSession, Counter, Role, Shop, User, UserCounter

__all__ = [
    "AuditLog",
    "AuthSession",
    "Category",
    "Counter",
    "CounterPrinter",
    "Customer",
    "CustomerLedgerEntry",
    "CustomerRefundSettlement",
    "CustomerReturn",
    "CustomerReturnLine",
    "IdempotencyRecord",
    "Invoice",
    "InvoiceBatchAllocation",
    "InvoiceCounter",
    "InvoiceItem",
    "LoyaltyAccount",
    "LoyaltyRedemption",
    "LoyaltyRule",
    "LoyaltyTransaction",
    "MedicineBatch",
    "MedicineDetail",
    "Payment",
    "PrintJob",
    "Printer",
    "Product",
    "ProductUnit",
    "Purchase",
    "PurchaseItem",
    "ReturnStockPortion",
    "ReturnStockResolution",
    "Role",
    "Shop",
    "StockLot",
    "StockMovement",
    "Supplier",
    "SupplierCreditNote",
    "SupplierLedger",
    "SupplierProduct",
    "User",
    "UserCounter",
]
