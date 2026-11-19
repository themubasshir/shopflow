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
