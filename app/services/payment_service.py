"""
Payment Service abstraction. Two payment paths exist per the spec:
  - "cash"   : no gateway call, marked pending settlement at the facility
  - "online" : goes through Paytm PG (pending approval as of build time)

RULE: raw card/payment data must NEVER be stored. We only ever persist the
gateway's transaction reference/tokenized id.

NOTE FOR REVIEWER: the PaytmPaymentService class is a stub with the correct
shape (checksum generation, initiate/verify calls) but must go through a real
security review and Paytm's staging sandbox before going live. Do not deploy
`online` payments to production off this stub as-is.
"""
import hashlib
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger("payment_service")


@dataclass
class PaymentInitResult:
    provider: str
    status: str  # "pending_cash" | "redirect_required" | "failed"
    transaction_ref: str
    redirect_url: str | None = None


@dataclass
class PaymentVerifyResult:
    success: bool
    transaction_ref: str
    raw_status: str


class PaymentService(ABC):
    @abstractmethod
    async def initiate_cash_payment(self, booking_id: str, amount: float) -> PaymentInitResult:
        ...

    @abstractmethod
    async def initiate_online_payment(self, booking_id: str, amount: float, customer_id: str) -> PaymentInitResult:
        ...

    @abstractmethod
    async def verify_payment(self, transaction_ref: str, gateway_response: dict) -> PaymentVerifyResult:
        ...


class DefaultPaymentService(PaymentService):
    """Cash-first implementation. Online path raises until Paytm approval +
    security review are done; wire up PaytmPaymentService below at that point."""

    async def initiate_cash_payment(self, booking_id: str, amount: float) -> PaymentInitResult:
        ref = f"CASH-{uuid.uuid4().hex[:12].upper()}"
        return PaymentInitResult(provider="cash", status="pending_cash", transaction_ref=ref)

    async def initiate_online_payment(self, booking_id: str, amount: float, customer_id: str) -> PaymentInitResult:
        if settings.payment_provider != "paytm":
            return PaymentInitResult(
                provider="cash_only",
                status="failed",
                transaction_ref="",
                redirect_url=None,
            )
        return await PaytmPaymentService().initiate_online_payment(booking_id, amount, customer_id)

    async def verify_payment(self, transaction_ref: str, gateway_response: dict) -> PaymentVerifyResult:
        if transaction_ref.startswith("CASH-"):
            return PaymentVerifyResult(success=True, transaction_ref=transaction_ref, raw_status="cash_collected")
        return await PaytmPaymentService().verify_payment(transaction_ref, gateway_response)


class PaytmPaymentService(PaymentService):
    """STUB — shape only. Do not use in production before:
    1) Paytm merchant approval is complete
    2) A real checksum/signature verification implementation using Paytm's
       official checksum SDK is swapped in
    3) A dedicated security review of this file
    """

    async def initiate_cash_payment(self, booking_id: str, amount: float) -> PaymentInitResult:
        raise NotImplementedError("Cash path is handled by DefaultPaymentService")

    async def initiate_online_payment(self, booking_id: str, amount: float, customer_id: str) -> PaymentInitResult:
        # Placeholder txn ref generation; real integration must call Paytm's
        # initiateTransaction API and use their returned txnToken.
        ref = f"PAYTM-{uuid.uuid4().hex[:12].upper()}"
        logger.warning("PaytmPaymentService.initiate_online_payment is a stub — not wired to real API")
        return PaymentInitResult(
            provider="paytm",
            status="redirect_required",
            transaction_ref=ref,
            redirect_url=settings.paytm_callback_url or None,
        )

    async def verify_payment(self, transaction_ref: str, gateway_response: dict) -> PaymentVerifyResult:
        logger.warning("PaytmPaymentService.verify_payment is a stub — checksum NOT verified")
        return PaymentVerifyResult(success=False, transaction_ref=transaction_ref, raw_status="stub_not_verified")

    @staticmethod
    def _placeholder_checksum(payload: str, key: str) -> str:
        # NOT Paytm's real checksum algorithm — replace with their official
        # checksum utility before any real money flows through this.
        return hashlib.sha256((payload + key).encode()).hexdigest()


payment_service = DefaultPaymentService()
