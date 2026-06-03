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
    """Calculates active data rates and pushes updates to Telegram every 10 seconds."""
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
        status_msg = await client.send_message('me', "🚀 **Staging Environment Initialized...**")
        
        # --- PHASE 1: DOWNLOAD ALL ZIP BUNDLES SEQUENTIALLY ---
        downloaded_files = []
        for msg_id in range(start_msg_id, end_msg_id + 1):
            try:
                msg = await client.get_messages(channel_id, ids=msg_id)
                if msg and msg.media and isinstance(msg.media, MessageMediaDocument):
                    filename = msg.file.name or f"part_{msg_id}.zip"
                    file_path = os.path.join(download_dir, filename)
                    
                    tracker = TelegramProgress(client, status_msg, filename, "Downloading Part")
                    await client.download_media(msg, file_path, progress_callback=tracker)
                    downloaded_files.append(file_path)
                    await asyncio.sleep(0.5)
            except Exception as e:
                await client.send_message('me', f"⚠️ Download Error on Message ID `{msg_id}`: {e}")
                
        if not downloaded_files:
            await status_msg.edit("❌ Staging failure: No valid multipart archives could be scraped.")
            sys.exit(1)
            
        # --- PHASE 2: EXTRACT USING SYSTEM 7Z ---
        await status_msg.edit("📦 **All segments cached. Launching extraction pipeline...**")
        downloaded_files.sort()
        
        main_entry = next((f for f in downloaded_files if f.endswith('.zip') or '.zip.' in f or 'zip01' in f.lower()), downloaded_files[0])
        
        result = subprocess.run(["7z", "x", main_entry, f"-o{extract_dir}", "-y"], capture_output=True, text=True)
        if result.returncode != 0:
            await status_msg.edit(f"❌ Core Archive Extraction Failure:\n`{result.stderr}`")
            sys.exit(1)
            
        # Wipe the raw zip cache instantly to maximize disk breathing room
        for f in downloaded_files:
            if os.path.exists(f): os.remove(f)

        # --- PHASE 3: GENERATE RECURSIVE MAP & STRUCTURAL SIZE ARRAY ---
        await status_msg.edit("🗺️ **Analyzing extracted directory layout and file structures...**")
        map_lines = []
        streamable_items = []
        non_streamable_items = []
        
        for root, dirs, files in os.walk(extract_dir):
            rel_path = os.path.relpath(root, extract_dir)
            depth = 0 if rel_path == "." else rel_path.count(os.sep) + 1
            indent = "  " * depth
            folder_name = os.path.basename(root) if rel_path != "." else "📦 Main Extracted root"
            
            # Calculate folder size
            total_folder_size = sum(os.path.getsize(os.path.join(root, f)) for f in os.listdir(root) if os.path.isfile(os.path.join(root, f)))
            map_lines.append(f"{indent}📁 {folder_name} `[{get_readable_size(total_folder_size)}]`")
            
            for file in files:
                file_path = os.path.join(root, file)
                f_size = os.path.getsize(file_path)
                map_lines.append(f"{indent}  ├── file: `{file}` `[{get_readable_size(f_size)}]`")
                
                # Segregate item by type
                file_info = {"absolute_path": file_path, "relative_folder": rel_path, "name": file}
                if file.lower().endswith(VIDEO_EXTENSIONS):
                    streamable_items.append(file_info)
                else:
                    non_streamable_items.append(file_info)
                    
        # Send layout map straight to user via split messages
        await send_split_messages(client, "📋 **Final Extracted Material Layout Map:**", map_lines)

        # --- PHASE 4: DISPATCH NON-STREAMABLE ELEMENTS TO SAVED MESSAGES ---
        if non_streamable_items:
            await client.send_message('me', f"📄 **Found {len(non_streamable_items)} non-streamable files. Sending to chat...**")
            for item in non_streamable_items:
                try:
                    caption = f"📎 **File:** `{item['name']}`\n📁 **Path:** `{item['relative_folder']}`"
                    tracker = TelegramProgress(client, status_msg, item['name'], "Uploading Document")
                    await client.send_file('me', item['absolute_path'], caption=caption, progress_callback=tracker)
                except Exception as e:
                    await client.send_message('me', f"⚠️ Error uploading document `{item['name']}`: {e}")
                finally:
                    if os.path.exists(item['absolute_path']): os.remove(item['absolute_path'])

        # --- PHASE 5: WIRE PREVENTATIVE STREAM CHANNELS INTO BUNNY PLATFORM ---
        if streamable_items:
            await client.send_message('me', f"🎬 **Found {len(streamable_items)} streameable files. Commencing high-speed Bunny execution...**")
            for video in streamable_items:
                try:
                    # Construct structural name mapping to mimic the physical map on flat Bunny structures
                    mapped_title = video['name'] if video['relative_folder'] == "." else f"{video['relative_folder'].replace(os.sep, ' - ')} - {video['name']}"
                    
                    await status_msg.edit(f"🧬 Creating placeholder link on Bunny platform:\n`{mapped_title}`...")
                    bunny_id = create_bunny_placeholder(mapped_title)
                    
                    # Run file transmission inside thread executor pool
                    tracker = TelegramProgress(client, status_msg, video['name'], "Bunny Transmitting")
                    loop = asyncio.get_event_loop()
                    success = await loop.run_in_executor(None, upload_to_bunny, bunny_id, video['absolute_path'])
                    
                    if success:
                        await client.send_message('me', f"✅ **Wired Successfully to Bunny Stream!**\n🎬 Title: `{mapped_title}`\n🆔 ID: `{bunny_id}`")
                    else:
                        await client.send_message('me', f"❌ Transmission failure targeting: `{mapped_title}`")
                except Exception as e:
                    await client.send_message('me', f"⚠️ Critical Error on routing video item `{video['name']}`: {e}")
                finally:
                    if os.path.exists(video['absolute_path']): os.remove(video['absolute_path'])

        await status_msg.edit("🎉 **All elements fully processed, mapped, segregated, and wired across platform endpoints!**")

if __name__ == "__main__":
    asyncio.run(main())
