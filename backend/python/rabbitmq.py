"""
rabbitmq.py  –  Simple RabbitMQ publisher helper using aio-pika

Provides a small async publisher API used by the FastAPI app to enqueue
background tasks (e.g. send_email). The repository includes a worker
(`worker.py`) that consumes these tasks.
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

import asyncio
import aio_pika
from aio_pika import Message, DeliveryMode, ExchangeType

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")

_connection = None
_channel = None
_exchange = None
_loop = None


async def init_rabbit() -> bool:
    """Initialize a robust connection, declare exchange and basic queues.

    Returns True on successful connect, False if connection failed.
    """
    global _connection, _channel, _exchange
    try:
        _connection = await aio_pika.connect_robust(RABBITMQ_URL)
        _channel = await _connection.channel()
        _exchange = await _channel.declare_exchange("insight", ExchangeType.DIRECT, durable=True)
        # capture the running loop so synchronous threads can schedule publishes
        try:
            _loop = asyncio.get_running_loop()
        except Exception:
            _loop = None

        # Ensure basic queues exist
        q = await _channel.declare_queue("email", durable=True)
        await q.bind(_exchange, routing_key="email")

        # Queue for camera ingest messages (binary JPEG payloads)
        cq = await _channel.declare_queue("camera_ingest", durable=True)
        await cq.bind(_exchange, routing_key="camera_ingest")

        print("✅ RabbitMQ connected (exchange 'insight', queue 'email')")
        return True
    except Exception as e:
        print(f"⚠️ RabbitMQ init failed: {e}")
        _connection = None
        _channel = None
        _exchange = None
        _loop = None
        return False


async def close_rabbit() -> None:
    global _connection, _channel, _exchange
    try:
        if _channel:
            await _channel.close()
        if _connection:
            await _connection.close()
    except Exception as e:
        print(f"Error closing RabbitMQ: {e}")
    finally:
        _connection = None
        _channel = None
        _exchange = None


async def publish_task(task: str, payload: dict, routing_key: str = "email") -> bool:
    """Publish a generic task to the `insight` exchange.

    Message body is JSON: {"task": <task>, "payload": <payload>}
    """
    global _exchange
    if _exchange is None:
        raise RuntimeError("RabbitMQ not initialized")

    body = json.dumps({"task": task, "payload": payload})
    msg = Message(body.encode(), delivery_mode=DeliveryMode.PERSISTENT)
    await _exchange.publish(msg, routing_key=routing_key)
    return True


async def publish_camera_ingest_async(cam_id: int, image_bytes: bytes, meta: dict | None = None, routing_key: str = "camera_ingest") -> bool:
    """Publish raw JPEG bytes for camera ingest to the `insight` exchange.

    The message body is the raw JPEG bytes. Metadata (cam_id/meta) is set
    in message headers as JSON-encoded strings.
    """
    global _exchange
    if _exchange is None:
        raise RuntimeError("RabbitMQ not initialized")

    headers = {"cam_id": int(cam_id)}
    if meta is not None:
        try:
            headers["meta"] = json.dumps(meta)
        except Exception:
            headers["meta"] = None

    msg = Message(
        image_bytes,
        delivery_mode=DeliveryMode.PERSISTENT,
        content_type="image/jpeg",
        headers=headers,
    )
    await _exchange.publish(msg, routing_key=routing_key)
    return True


def publish_camera_ingest(cam_id: int, image_bytes: bytes, meta: dict | None = None, timeout: float = 1.0) -> bool:
    """Synchronous wrapper to schedule an async publish on the RabbitMQ event loop.

    Returns True if the publish was scheduled and completed, False otherwise.
    """
    global _loop, _exchange
    if _exchange is None or _loop is None:
        return False
    try:
        fut = asyncio.run_coroutine_threadsafe(publish_camera_ingest_async(cam_id, image_bytes, meta), _loop)
        # wait briefly for result to detect immediate publish errors
        fut.result(timeout=timeout)
        return True
    except Exception as e:
        print(f"RabbitMQ publish_camera_ingest error: {e}")
        return False


async def publish_email(to_email: str, subject: str, html: str) -> bool:
    return await publish_task(
        "send_email",
        {"to_email": to_email, "subject": subject, "html": html},
        routing_key="email",
    )
