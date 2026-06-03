import os
import re
import sys
import time
import requests
import asyncio
import subprocess
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument

# Validate Environment Configuration
required_vars = ["API_ID", "API_HASH", "SESSION_STRING", "START_LINK", "END_LINK", "BUNNY_LIBRARY_ID", "BUNNY_STREAM_KEY"]
missing_vars = [var for var in required_vars if not os.environ.get(var)]
if missing_vars:
    print(f"❌ Error: Missing required secrets: {', '.join(missing_vars)}")
    sys.exit(1)

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
STRING_SESSION = os.environ["SESSION_STRING"]
START_LINK = os.environ["START_LINK"]
END_LINK = os.environ["END_LINK"]
BUNNY_LIBRARY_ID = os.environ["BUNNY_LIBRARY_ID"]
BUNNY_STREAM_KEY = os.environ["BUNNY_STREAM_KEY"]

LINK_REGEX = r"https://t\.me/c/(\d+)/(\d+)"
VIDEO_EXTENSIONS = ('.mp4', '.mkv', '.ts', '.avi', '.mov', '.flv', '.webm', '.m4v')

class TelegramProgress:
    """Calculates active data rates and updates a single Telegram tracking status message every 10 seconds."""
    def __init__(self, client, status_msg, filename, operation="Processing"):
        self.client = client
        self.status_msg = status_msg
        self.filename = filename
        self.operation = operation
        self.last_updated_time = time.time()

    def __call__(self, received, total):
        now = time.time()
        if now - self.last_updated_time >= 10 or received == total:
            self.last_updated_time = now
            percent = (received / total) * 100 if total else 0
            received_mb = received / (1024 * 1024)
            total_mb = total / (1024 * 1024) if total else 0
            
            bar_length = 15
            filled_length = int(round(bar_length * received / float(total))) if total else 0
            bar = '█' * filled_length + '░' * (bar_length - filled_length)
            
            text = (
                f"⚡ **{self.operation}:** `{self.filename}`\n"
                f"📊 `[{bar}]` **{percent:.1f}%**\n"
                f"📦 `{received_mb:.2f} / {total_mb:.2f} MB`"
            )
            # Log progress quietly to GitHub console
            print(f"-> {self.operation}: {self.filename} - {percent:.1f}% ({received_mb:.2f}/{total_mb:.2f} MB)")
            coro = self.status_msg.edit(text)
            self.client.loop.create_task(coro)

def get_readable_size(size_in_bytes):
    """Converts raw bytes into human-readable text strings."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} TB"

async def send_split_messages(client, header, content_lines):
    """Assembles and pushes multi-message text blocks safely respecting Telegram character limits."""
    current_message = header + "\n"
    for line in content_lines:
        if len(current_message) + len(line) + 2 > 4000:
            await client.send_message('me', current_message)
            current_message = "🔄 **Folder Map (Continued):**\n\n" + line + "\n"
        else:
            current_message += line + "\n"
    if current_message.strip():
        await client.send_message('me', current_message)

def create_bunny_placeholder(title):
    """Registers a clean metadata collection reference inside Bunny Stream network layers."""
    url = f"https://video.bunnycdn.com/library/{BUNNY_LIBRARY_ID}/videos"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "AccessKey": BUNNY_STREAM_KEY
    }
    response = requests.post(url, json={"title": title}, headers=headers)
    if response.status_code == 200:
        return response.json().get("guid")
    raise Exception(f"Bunny API Registration Failure: {response.text}")

def upload_to_bunny(video_id, file_path):
    """Transmits structural binary streams directly to the targeted execution target endpoint."""
    url = f"https://video.bunnycdn.com/library/{BUNNY_LIBRARY_ID}/videos/{video_id}"
    headers = {
        "accept": "application/json",
        "AccessKey": BUNNY_STREAM_KEY
    }
    with open(file_path, "rb") as video_data:
        response = requests.put(url, data=video_data, headers=headers)
    return response.status_code == 200

async def main():
    start_match = re.search(LINK_REGEX, START_LINK)
    end_match = re.search(LINK_REGEX, END_LINK)
    
    if not start_match or not end_match:
        print("❌ Error: Invalid target channel message range links context parsing failed.")
        sys.exit(1)
        
    channel_id = int(f"-100{start_match.group(1)}")
    start_msg_id = int(start_match.group(2))
    end_msg_id = int(end_match.group(2))
    
    download_dir = "./local_staging_cache"
    extract_dir = "./extracted_material"
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs(extract_dir, exist_ok=True)
    
    async with TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH) as client:
        # Single pin status message that rewrites itself to prevent alert fatigue
        status_msg = await client.send_message('me', "🚀 **Staging Environment Initialized...**")
        print(f"📡 Targeting Channel: {channel_id} | Range: {start_msg_id} -> {end_msg_id}")
        
        # --- PHASE 1: COLLECT ALL VALID MEDIA MESSAGES IN THE RANGE ---
        valid_messages = []
        for msg_id in range(start_msg_id, end_msg_id + 1):
            try:
                msg = await client.get_messages(channel_id, ids=msg_id)
                if msg and msg.media and isinstance(msg.media, MessageMediaDocument):
                    valid_messages.append(msg)
                else:
                    print(f"ℹ️ Skipped msg {msg_id}: Not a valid file document attachment.")
            except Exception as e:
                # Immediate Failure Tweet alert to chat
                await client.send_message('me', f"⚠️ **Scraping Error:** Critical access fault checking link ID `{msg_id}`\n`Error: {e}`")
                print(f"❌ Error checking msg {msg_id}: {e}")

        if not valid_messages:
            await status_msg.edit("❌ **Staging terminated:** No valid document files discovered in requested link scope.")
            sys.exit(1)

        total_parts = len(valid_messages)
        downloaded_files = []
        
        # Notify once that downloading is underway instead of sending a text for every single part
        await status_msg.edit(f"📥 **Downloading multi-part archive chain ({total_parts} segments identified)...**")

        # --- PHASE 2: DOWNLOAD WITH REVERSE RE-NAMING SYSTEM ---
        for idx, msg in enumerate(valid_messages):
            original_name = msg.file.name or f"unknown_{msg.id}"
            position_from_end = total_parts - 1 - idx
            
            if position_from_end == 0:
                forced_filename = "fixed_archive.zip"
            else:
                forced_filename = f"fixed_archive.z{position_from_end:02d}"
                
            file_path = os.path.join(download_dir, forced_filename)
            
            # Print sequence tweaks silently to GitHub actions for tracing adjustments
            print(f"🔧 File Match Index [{idx+1}/{total_parts}] -> Original: '{original_name}' mapped to Forced Output: '{forced_filename}'")
            
            try:
                tracker = TelegramProgress(client, status_msg, forced_filename, f"Downloading Part ({idx+1}/{total_parts})")
                await client.download_media(msg, file_path, progress_callback=tracker)
                downloaded_files.append(file_path)
                await asyncio.sleep(0.2)
            except Exception as e:
                await client.send_message('me', f"🚨 **Download Interruption:** Failed downloading segment sequence for link ID `{msg.id}`\n`Error: {e}`")
                print(f"❌ Error downloading file on msg {msg.id}: {e}")
            
        # --- PHASE 3: RUN TARGETED EXTRACTION ON THE TAIL HEAD ---
        await status_msg.edit("📦 **All volumes successfully cached. Extracting core structure...**")
        main_entry = os.path.join(download_dir, "fixed_archive.zip")
        
        result = subprocess.run(["7z", "x", main_entry, f"-o{extract_dir}", "-y"], capture_output=True, text=True)
        if result.returncode != 0:
            # Send immediate comprehensive debugging block inside chat if the 7z pipeline crashes
            await status_msg.edit(f"💥 **Extraction Failure:** The multi-part archive layout tracking broke down.")
            await client.send_message('me', f"📂 **7z Engine Debug Trace:**\n
http://googleusercontent.com/immersive_entry_chip/0

### 🧠 Log Strategy Configuration:

| Scenario / Event | Where it Logs | Visual Impact in Your Chat |
| :--- | :--- | :--- |
| **Progress Bars** (Downloading/Uploading) | **Telegram + GitHub** | Keeps editing **one single text block** live so your notifications don't ring repeatedly. |
| **Filename Tweaks / Extension Fixes** | **GitHub Logs Only** | None. It cleanly maps `original_name` $\rightarrow$ `fixed_archive.z01` in the background console. |
| **Final Directory Map Tree** | **Telegram Chat** | Drops a clear file directory structure directly in your chat once extraction finishes. |
| **API / Extraction / 7z Crashes** | **Telegram Chat** | Immediately fires a diagnostic alert block containing the raw terminal engine trace so you can fix it right away. |
