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
                # Immediate Failure alert to chat
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
            await status_msg.edit("💥 **Extraction Failure:** The multi-part archive layout tracking broke down.")
            
            # Single line concatenation to prevent any multi-line copy-paste syntax errors
            debug_trace = result.stderr[:3500]
            await client.send_message('me', "📂 **7z Engine Debug Trace:**\n```\n" + debug_trace + "\n```")
            print(f"❌ 7z Error Output:\n{result.stderr}")
            sys.exit(1)
            
        # Clear original archive blocks out of workspace memory
        for f in downloaded_files:
            if os.path.exists(f): os.remove(f)

        # --- PHASE 4: GENERATE RECURSIVE MAP ---
        await status_msg.edit("🗺️ **Analyzing extracted structures...**")
        map_lines = []
        streamable_items = []
        non_streamable_items = []
        
        for root, dirs, files in os.walk(extract_dir):
            rel_path = os.path.relpath(root, extract_dir)
            depth = 0 if rel_path == "." else rel_path.count(os.sep) + 1
            indent = "  " * depth
            folder_name = os.path.basename(root) if rel_path != "." else "📦 Main Extracted Root"
            
            total_folder_size = sum(os.path.getsize(os.path.join(root, f)) for f in os.listdir(root) if os.path.isfile(os.path.join(root, f)))
            map_lines.append(f"{indent}📁 {folder_name} `[{get_readable_size(total_folder_size)}]`")
            
            for file in files:
                file_path = os.path.join(root, file)
                f_size = os.path.getsize(file_path)
                map_lines.append(f"{indent}  ├── file: `{file}` `[{get_readable_size(f_size)}]`")
                
                file_info = {"absolute_path": file_path, "relative_folder": rel_path, "name": file}
                if file.lower().endswith(VIDEO_EXTENSIONS):
                    streamable_items.append(file_info)
                else:
                    non_streamable_items.append(file_info)
                    
        # Send layout map straight to user via split messages (This is a Main Event)
        await send_split_messages(client, "📋 **Final Extracted Material Layout Map:**", map_lines)

        # --- PHASE 5: DISPATCH NON-STREAMABLE ELEMENTS ---
        if non_streamable_items:
            print(f"ℹ️ Found {len(non_streamable_items)} non-streamable elements. Uploading to Saved Messages...")
            for item in non_streamable_items:
                try:
                    caption = f"📎 **File:** `{item['name']}`\n📁 **Path:** `{item['relative_folder']}`"
                    tracker = TelegramProgress(client, status_msg, item['name'], "Uploading Document")
                    await client.send_file('me', item['absolute_path'], caption=caption, progress_callback=tracker)
                except Exception as e:
                    await client.send_message('me', f"⚠️ **File Route Failure:** Failed adding `{item['name']}` to Telegram chat queue.\n`Error: {e}`")
                finally:
                    if os.path.exists(item['absolute_path']): os.remove(item['absolute_path'])

        # --- PHASE 6: WIRE VIDEO SEGMENTS INTO BUNNY DASHBOARD ---
        if streamable_items:
            print(f"🎬 Found {len(streamable_items)} streamable elements. Delivering to Bunny Stream...")
            for video in streamable_items:
                try:
                    mapped_title = video['name'] if video['relative_folder'] == "." else f"{video['relative_folder'].replace(os.sep, ' - ')} - {video['name']}"
                    
                    print(f"🧬 Building Bunny item footprint for: {mapped_title}")
                    bunny_id = create_bunny_placeholder(mapped_title)
                    
                    tracker = TelegramProgress(client, status_msg, video['name'], "Bunny Transmitting")
                    loop = asyncio.get_event_loop()
                    success = await loop.run_in_executor(None, upload_to_bunny, bunny_id, video['absolute_path'])
                    
                    if not success:
                        await client.send_message('me', f"❌ **Bunny Stream Rejection:** Transmission handshake timed out for video object: `{mapped_title}`")
                except Exception as e:
                    await client.send_message('me', f"⚠️ **Bunny API Error:** Couldn't pipe item `{video['name']}`\n`Error: {e}`")
                finally:
                    if os.path.exists(video['absolute_path']): os.remove(video['absolute_path'])

        await status_msg.edit("🎉 **All elements fully inverted, extracted, mapped, and wired successfully!**")

if __name__ == "__main__":
    asyncio.run(main())
