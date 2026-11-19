from __future__ import annotations

import enum


class Locale(str, enum.Enum):
    EN = "en"
    BN = "bn"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    FINALIZED = "finalized"
    VOIDED = "voided"
    REFUNDED = "refunded"


class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    BKASH = "bkash"
    NAGAD = "nagad"
    CARD = "card"
    DUE = "due"


class StockMovementType(str, enum.Enum):
    OPENING = "opening"
    PURCHASE = "purchase"
    SALE = "sale"
    RETURN = "return"
    ADJUSTMENT = "adjustment"
    DAMAGE = "damage"
    TRANSFER = "transfer"


class LoyaltyTransactionType(str, enum.Enum):
    EARN = "earn"
    REDEEM = "redeem"
    REVERSE = "reverse"
    ADJUST = "adjust"
    EXPIRE = "expire"


class PurchaseStatus(str, enum.Enum):
    DRAFT = "draft"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    VOIDED = "voided"
    REVERSED = "reversed"


class RedemptionStatus(str, enum.Enum):
    APPLIED = "applied"
    REVERSED = "reversed"


class UnitOfMeasure(str, enum.Enum):
    PIECE = "piece"
    KG = "kg"
    GRAM = "gram"
    LITRE = "litre"
    ML = "ml"
    PACK = "pack"
    STRIP = "strip"
    BOX = "box"
    BOTTLE = "bottle"
    SACHET = "sachet"


# --- Phase 2D-2: shared thermal printing -------------------------------------


class PrinterTransport(str, enum.Enum):
    """How the agent reaches the printer hardware.

    ``NETWORK`` is the only transport supported today (Wi-Fi/LAN TCP 9100).
    ``BLUETOOTH`` is declared so a dedicated host can be added later without
    changing the queue or renderer — it is not a working path yet.
    """

    NETWORK = "network"
    BLUETOOTH = "bluetooth"


class PrintJobStatus(str, enum.Enum):
    """Lifecycle of a queued print job.

    ``pending``      — waiting for an agent to claim it
    ``claimed``      — leased to an agent, rendering/streaming in progress
    ``printing``     — agent signalled it has started streaming to the device
    ``completed``    — agent confirmed the physical print finished
    ``failed``       — agent reported a recoverable error; may be retried
    ``uncertain``    — lease expired or outcome unknown; NEVER auto-reprinted
    ``cancelled``    — owner cancelled before an agent picked it up
    """

    PENDING = "pending"
    CLAIMED = "claimed"
    PRINTING = "printing"
    COMPLETED = "completed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"
