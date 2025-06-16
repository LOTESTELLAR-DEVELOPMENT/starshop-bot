import os
from dotenv import load_dotenv
from dataclasses import dataclass
from pydantic import Field

@dataclass
class Config:
    bot_token: str
    postgres_dsn: str
    redis_url: str
    news_channel_id: str
    news_channel_link: str
    welcome_image_url: str
    welcome_description: str
    profile_offer_url: str
    profile_privacy_url: str
    cryptomus_api_key: str
    cryptomus_merchant_id: str
    cryptomus_webhook_secret: str
    fragment_api_key: str
    fragment_shop_id: str
    fragment_phone_number: str
    fragment_mnemonics: str
    support_url: str
    admin_id: str
    mulenpay_api_key: str = ""
    mulenpay_secret_key: str = ""
    mulenpay_shop_id: str = ""
    mulenpay_merchant_id: str = ""
    mulenpay_webhook_secret: str = ""
    mulenpay_callback_url: str = ""
    heleket_api_key: str = ""
    heleket_merchant_id: str = ""
    heleket_callback_url: str = ""
    fragment_jwt_token: str = ""


def load_config():
    load_dotenv()
    config = Config(
        bot_token=os.getenv("BOT_TOKEN"),
        postgres_dsn=os.getenv("POSTGRES_DSN"),
        redis_url=os.getenv("REDIS_URL"),
        news_channel_id=os.getenv("NEWS_CHANNEL_ID"),
        news_channel_link=os.getenv("NEWS_CHANNEL_LINK"),
        welcome_image_url=os.getenv("WELCOME_IMAGE_URL", "https://placehold.co/400x200/png"),
        welcome_description=os.getenv(
            "WELCOME_DESCRIPTION",
            "<b>Добро пожаловать!</b>\n\nЗдесь вы можете купить звезды и премиум, пополнить баланс, воспользоваться реферальной системой и многое другое."
        ).replace("\\n", "\n"),
        profile_offer_url=os.getenv("PROFILE_OFFER_URL", "https://example.com/offer"),
        profile_privacy_url=os.getenv("PROFILE_PRIVACY_URL", "https://example.com/privacy"),
        cryptomus_api_key=os.getenv("CRYPTOMUS_API_KEY"),
        cryptomus_merchant_id=os.getenv("CRYPTOMUS_MERCHANT_ID"),
        cryptomus_webhook_secret=os.getenv("CRYPTOMUS_WEBHOOK_SECRET"),
        fragment_api_key=os.getenv("FRAGMENT_API_KEY"),
        fragment_shop_id=os.getenv("FRAGMENT_SHOP_ID"),
        fragment_phone_number=os.getenv("FRAGMENT_PHONE_NUMBER"),
        fragment_mnemonics=os.getenv("FRAGMENT_MNEMONICS"),
        fragment_jwt_token=os.getenv("FRAGMENT_JWT_TOKEN", ""),
        support_url=os.getenv("SUPPORT_URL"),
        admin_id=os.getenv("ADMIN_ID"),
        mulenpay_api_key=os.getenv("MULENPAY_API_KEY", ""),
        mulenpay_secret_key=os.getenv("MULENPAY_SECRET_KEY", ""),
        mulenpay_shop_id=os.getenv("MULENPAY_SHOP_ID", ""),
        mulenpay_merchant_id=os.getenv("MULENPAY_MERCHANT_ID", ""),
        mulenpay_webhook_secret=os.getenv("MULENPAY_WEBHOOK_SECRET", os.getenv("MULENPAY_SECRET_KEY", "")),
        mulenpay_callback_url=os.getenv("MULENPAY_CALLBACK_URL", ""),
        heleket_api_key=os.getenv("HELEKET_API_KEY", ""),
        heleket_merchant_id=os.getenv("HELEKET_MERCHANT_ID", ""),
        heleket_callback_url=os.getenv("HELEKET_CALLBACK_URL", ""),
    )
    return config 