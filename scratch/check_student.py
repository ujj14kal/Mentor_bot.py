import asyncio
from telethon import TelegramClient
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, SESSION_NAME
import sys

async def main():
    client = TelegramClient(SESSION_NAME, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()
    cid = -1003827430242 # Dhvani Parmar
    print(f"Checking {cid}")
    async for msg in client.iter_messages(cid, limit=5):
        print(f"Msg from {msg.sender_id} at {msg.date}: {msg.text[:20] if msg.text else 'Photo'}")
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
