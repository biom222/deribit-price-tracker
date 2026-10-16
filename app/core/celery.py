from celery import Celery

from app.core.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    application = Celery(
        "deribit_price_tracker",
        broker=settings.redis_url,
        include=["app.tasks.prices"],
    )
    application.conf.update(
        beat_schedule={
            "collect-index-prices-every-minute": {
                "task": "app.tasks.prices.collect_index_prices",
                "schedule": 60.0,
                "options": {"expires": 60},
            }
        },
        broker_connection_retry_on_startup=True,
        task_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        worker_prefetch_multiplier=1,
    )
    return application


celery_app = create_celery_app()
