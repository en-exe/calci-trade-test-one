"""Quick auth test against Kalshi demo API."""

import asyncio
import base64
import time
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import config


def load_key():
    with open(config.KALSHI_PRIVATE_KEY_PATH, "rb") as f:
        raw = f.read()
    print(f"Key file size: {len(raw)} bytes")
    print(f"First 40 chars: {raw[:40]}")
    key = serialization.load_pem_private_key(raw, password=None)
    print(f"Key type: {type(key).__name__}")
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TypeError("Not RSA")
    print(f"Key size: {key.key_size} bits")
    return key


def sign(private_key, timestamp_str, method, path):
    msg = timestamp_str + method + path
    print(f"Signing message: {msg!r}")
    signature = private_key.sign(
        msg.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


async def test():
    key = load_key()
    base = config.KALSHI_BASE_URL.rstrip("/")
    endpoint = "/portfolio/balance"
    url = f"{base}{endpoint}"
    path = urlparse(url).path

    print(f"\nAPI Key: {config.KALSHI_API_KEY}")
    print(f"Base URL: {base}")
    print(f"Full URL: {url}")
    print(f"Parsed path: {path}")

    ts = str(int(time.time() * 1000))
    sig = sign(key, ts, "GET", path)

    headers = {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": config.KALSHI_API_KEY,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }
    print(f"\nHeaders: { {k: v[:30]+'...' if len(v)>30 else v for k,v in headers.items()} }")

    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=headers)
        print(f"\nResponse: {r.status_code}")
        print(f"Body: {r.text[:500]}")


asyncio.run(test())
