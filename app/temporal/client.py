from temporalio.client import Client

from app.core.config import settings


async def temporal_client() -> Client:
    return await Client.connect(settings.temporal_host)
