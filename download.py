import os
import re
import sys
import time
import asyncio
import subprocess
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument

# Validate environment variables
required_vars = ["API_ID", "API_HASH", "SESSION_STRING", "START_LINK", "END_LINK"]
missing_vars = [var for var in required_vars if not os.environ.get(var)]
if missing_vars:
    print(f"❌ Error: Missing required environment variables: {', '.join(missing_vars)}")
    sys.exit(1)

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
STRING_SESSION = os.environ["SESSION_STRING"]
START_LINK = os.environ["START_LINK"]
END_LINK = os.environ["END_LINK"]

LINK_REGEX = r"https://t\.me/c/(\d+)/(\d+)"

class TelegramProgress:
    """Tracks download/upload progress and updates a Telegram message every 10 seconds."""
    def __init__(self, client, status_msg, filename, operation="Downloading"):
        self.client = client
        self.status_msg = status_msg
        self.filename = filename
        self.operation = operation
        self.last_updated_time = time.time()

    def __call__(self, received, total):
        now = time.time()
        # Update every 10 seconds, or at 100% completion
        if now - self.last_updated_time >= 10 or received == total:
            self.last_updated_time = now
            percent = (received / total) * 100 if total else 0
            received_mb = received / (1024 * 1024)
            total_mb = total / (1024 * 1024) if total else 0
            
            bar_length = 15
            filled_length = int(round(bar_length * received / float(total))) if total else 0
            bar = '█' * filled_length + '░' * (bar_length - filled_length)
            
            text = (
                f"⏳ **{self.operation}:** `{self.filename}`\n"
                f"📊 `[{bar}]` **{percent:.1f}%**\n"
                f"📁 `{received_mb:.2f} / {total_mb:.2f} MB`"
            )
            
            # Run the async edit inside Telethon's event loop safely
            coro = self.status_msg.edit(text)
            self.client.loop.create_task(coro)

async def main():
    start_match = re.search(LINK_REGEX, START_LINK)
    end_match = re.search(LINK_REGEX, END_LINK)
    
    if not start_match or not end_match:
        print("❌ Error: Invalid private channel links provided.")
        sys.exit(1)
        
    channel_id = int(f"-100{start_match.group(1)}")
    start_msg_id = int(start_match.group(2))
    end_msg_id = int(end_match.group(2))
    
    download_dir = "./workspace_downloads"
    extract_dir = "./extracted_material"
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs(extract_dir, exist_ok=True)
    
    async with TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH) as client:
        # Create a status tracking message in your own Saved Messages ('me')
        status_msg = await client.send_message('me', "🚀 **Initializing Userbot Downloader Queue...**")
        await status_msg.edit(f"📡 Connected. Targeting channel: `{channel_id}`\nRange: `{start_msg_id}` ➡️ `{end_msg_id}`")
        
        downloaded_files = []
        
        for msg_id in range(start_msg_id, end_msg_id + 1):
            try:
                msg = await client.get_messages(channel_id, ids=msg_id)
                if msg and msg.media and isinstance(msg.media, MessageMediaDocument):
                    filename = msg.file.name or f"file_{msg_id}"
                    file_path = os.path.join(download_dir, filename)
                    
                    progress_tracker = TelegramProgress(client, status_msg, filename, "Downloading")
                    await client.download_media(msg, file_path, progress_callback=progress_tracker)
                    downloaded_files.append(file_path)
                    await asyncio.sleep(1) # Small delay to avoid flooding
                else:
                    await client.send_message('me', f"ℹ️ Message ID `{msg_id}` skipped: No document media found.")
            except Exception as e:
                await client.send_message('me', f"⚠️ Error downloading message ID `{msg_id}`: {e}")
                
        if not downloaded_files:
            await status_msg.edit("❌ Failure: No valid files could be downloaded.")
            sys.exit(1)
            
        await status_msg.edit("✅ All parts downloaded. Sorting and combining split volumes...")
        downloaded_files.sort()
        
        main_zip = None
        for f in downloaded_files:
            if f.endswith('.zip') or '.zip.' in f or 'zip01' in f.lower():
                main_zip = f
                break
                
        if not main_zip:
            main_zip = downloaded_files[0]
            
        await status_msg.edit(f"📦 **Extracting multi-part archive starting at:** `{os.path.basename(main_zip)}`...")
        
        # Unpack via 7z
        result = subprocess.run(["7z", "x", main_zip, f"-o{extract_dir}", "-y"], capture_output=True, text=True)
        
        if result.returncode != 0:
            await status_msg.edit(f"❌ Extraction failed:\n`{result.stderr}`")
            sys.exit(1)
            
        await status_msg.edit("🚀 **Extraction successful!** Preparing folder elements for Telegram delivery queue...")
        
        # Scan extracted folder and upload everything directly back to you
        extracted_items = os.listdir(extract_dir)
        if not extracted_items:
            await status_msg.edit("⚠️ Archive extracted, but the resulting folder is empty.")
            return

        for item in extracted_items:
            item_path = os.path.join(extract_dir, item)
            if os.path.isfile(item_path):
                upload_tracker = TelegramProgress(client, status_msg, item, "Uploading Material")
                await client.send_file('me', item_path, caption=f"✅ Extracted item: `{item}`", progress_callback=upload_tracker)
                await asyncio.sleep(1)
                
        await status_msg.edit("🎉 **All operations complete!** Processed files have been added to your queue above.")

if __name__ == "__main__":
    asyncio.run(main())
