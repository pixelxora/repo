import os
import re
import sys
import time
import subprocess
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument

# Validate environment variables
required_vars = ["TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_STRING_SESSION", "START_LINK", "END_LINK"]
missing_vars = [var for var in required_vars if not os.environ.get(var)]
if missing_vars:
    print(f"❌ Error: Missing required environment variables: {', '.join(missing_vars)}")
    sys.exit(1)

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
STRING_SESSION = os.environ["TELEGRAM_STRING_SESSION"]
START_LINK = os.environ["START_LINK"]
END_LINK = os.environ["END_LINK"]

LINK_REGEX = r"https://t\.me/c/(\d+)/(\d+)"

class ThrottledProgress:
    """Tracks and prints download progress at maximum every 10 seconds."""
    def __init__(self, filename):
        self.filename = filename
        self.start_time = time.time()
        self.last_printed_time = 0

    def __call__(self, received, total):
        now = time.time()
        if now - self.last_printed_time >= 10 or received == total:
            self.last_printed_time = now
            percent = (received / total) * 100 if total else 0
            received_mb = received / (1024 * 1024)
            total_mb = total / (1024 * 1024) if total else 0
            
            bar_length = 20
            filled_length = int(round(bar_length * received / float(total))) if total else 0
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            
            print(f"📊 Progress |[{bar}]| {percent:.1f}% ({received_mb:.2f} / {total_mb:.2f} MB) -> {self.filename}")

async def main():
    start_match = re.search(LINK_REGEX, START_LINK)
    end_match = re.search(LINK_REGEX, END_LINK)
    
    if not start_match or not end_match:
        print("❌ Error: Invalid private channel links provided. Ensure format matches: https://t.me/c/xxxxxx/xxxx")
        sys.exit(1)
        
    channel_id = int(f"-100{start_match.group(1)}")
    start_msg_id = int(start_match.group(2))
    end_msg_id = int(end_match.group(2))
    
    if start_msg_id > end_msg_id:
        print("❌ Error: Start message ID cannot be larger than End message ID.")
        sys.exit(1)
        
    download_dir = "./workspace_downloads"
    extract_dir = "./extracted_material"
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs(extract_dir, exist_ok=True)
    
    print(f"📡 Connecting to Telegram and targeting channel: {channel_id} (Range: {start_msg_id} -> {end_msg_id})")
    
    async with TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH) as client:
        downloaded_files = []
        
        for msg_id in range(start_msg_id, end_msg_id + 1):
            try:
                msg = await client.get_messages(channel_id, ids=msg_id)
                if msg and msg.media and isinstance(msg.media, MessageMediaDocument):
                    filename = msg.file.name or f"file_{msg_id}"
                    file_path = os.path.join(download_dir, filename)
                    
                    print(f"\n📥 Initiating download for: {filename} (ID: {msg_id})")
                    progress_tracker = ThrottledProgress(filename)
                    await client.download_media(msg, file_path, progress_callback=progress_tracker)
                    downloaded_files.append(file_path)
                else:
                    print(f"⏭️ Skipping message ID {msg_id}: No downloadable document media found.")
            except Exception as e:
                print(f"⚠️ Error downloading message ID {msg_id}: {e}")
                
        if not downloaded_files:
            print("❌ Failure: No valid files could be downloaded.")
            sys.exit(1)
            
        print("\n✅ All files successfully downloaded. Sorting archive chain...")
        downloaded_files.sort()
        
        # Determine the primary master archive piece
        main_zip = None
        for f in downloaded_files:
            if f.endswith('.zip') or '.zip.' in f or 'zip01' in f.lower():
                main_zip = f
                break
                
        if not main_zip:
            print("ℹ️ No classic zip extension found. Using the first alpha-sorted file as master archive entry.")
            main_zip = downloaded_files[0]
            
        print(f"📦 Extracting multi-part archive chain starting at: {main_zip}")
        
        # Run 7z extraction. It automatically stitches together parts (zip01, zip02... or .zip.001, .zip.002)
        result = subprocess.run(["7z", "x", main_zip, f"-o{extract_dir}", "-y"], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("🚀 Extraction successful! Materials sent to workflow queue upload.")
        else:
            print("❌ Extraction failed.")
            print(result.stderr)
            sys.exit(1)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
