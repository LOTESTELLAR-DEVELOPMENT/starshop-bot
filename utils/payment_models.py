import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from enum import StrEnum
import httpx
from config import load_config
from mulenpay_api import Payment
import time

class PaymentStatus(StrEnum):
    PAID = "paid"
    PAID_OVER = "paid_over"
    WRONG_AMOUNT = "wrong_amount"
    PROCESS = "process"
    CONFIRM_CHECK = "confirm_check"
    WRONG_AMOUNT_WAITING = "wrong_amount_waiting"
    CHECK = "check"
    FAIL = "fail"
    CANCEL = "cancel"
    SYSTEM_FAIL = "system_fail"
    REFUND_PROCESS = "refund_process"
    REFUND_FAIL = "refund_fail"
    REFUND_PAID = "refund_paid"
    LOCKED = "locked"

@dataclass(slots=True)
class UpdateInvoice:
    type: str
    uuid: str
    order_id: str
    amount: str
    is_final: bool
    status: str

@dataclass(slots=True)
class MulenpayInvoice:
    uuid: str
    pay_url: str
    amount: float
    status: str
    user_id: int
    created_at: str

def verify_signature(raw_body: bytes, sign: str, api_key: str) -> bool:
    base64_body = base64.b64encode(raw_body).decode()
    hash_value = hashlib.md5((base64_body + api_key).encode("utf-8")).hexdigest()
    print(f"DEBUG: hash_value={hash_value}, sign={sign}, base64_body={base64_body}")
    return hmac.compare_digest(hash_value, sign)

async def create_mulenpay_invoice(user_id: int, amount: float):
    config = load_config()
    payment = Payment(api_key=config.mulenpay_api_key, secret_key=config.mulenpay_secret_key)
    response = await payment.create_payment(payment.CreatePayment(
        currency="rub",
        amount=str(amount),
        uuid=str(user_id),
        shopId=int(config.mulenpay_shop_id),
        description=f"Пополнение баланса для пользователя {user_id}",
        items=[{
            "name": "Пополнение баланса",
            "description": "Пополнение баланса пользователя",
            "price": str(amount),
            "quantity": 1,
            "vat_code": 1,
            "payment_subject": 4,
            "payment_mode": 1,
            "product_code": "00000000",
            "country_of_origin_code": "RU",
            "customs_declaration_number": "",
            "excise": "0",
            "measurement_unit": 0
        }],
        subscribe=None,
        holdTime=None
    ))
    return response

def generate_heleket_sign(payload: dict, api_key: str) -> str:
    payload_str = json.dumps(payload, separators=(',', ':'))
    payload_b64 = base64.b64encode(payload_str.encode()).decode()
    sign_str = payload_b64 + api_key
    sign = hashlib.md5(sign_str.encode()).hexdigest()
    return sign

async def create_heleket_invoice(user_id: int, amount: float, api_key: str, merchant_id: str, callback_url: str = None):
    url = "https://api.heleket.com/v1/payment"
    order_id = f"{user_id}_{int(time.time())}"
    payload = {
        "amount": str(amount),
        "currency": "USD",
        "order_id": order_id,
    }
    if callback_url:
        payload["url_callback"] = callback_url
    if merchant_id:
        payload["shop_id"] = merchant_id
    sign = generate_heleket_sign(payload, api_key)
    headers = {
        "merchant": merchant_id,
        "sign": sign,
        "Content-Type": "application/json"
    }
    print("[Heleket] PAYLOAD:", payload)
    print("[Heleket] HEADERS:", headers)
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data 