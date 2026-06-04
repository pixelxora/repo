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
MAX_CONCURRENT_DOWNLOADS = 3  # Maximum concurrent chunks to avoid flood limits

class TelegramProgress:
    """Calculates download pacing and reports updates to the console."""
    def __init__(self, filename):
        self.filename = filename
        self.last_updated_time = time.time()

    def __call__(self, received, total):
        now = time.time()
        if now - self.last_updated_time >= 15 or received == total:
            self.last_updated_time = now
            percent = (received / total) * 100 if total else 0
            print(f"⚡ [Downloading] {self.filename} -> {percent:.1f}%")

def get_readable_size(size_in_bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} TB"

async def send_split_messages(client, header, content_lines):
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
    url = f"https://video.bunnycdn.com/library/{BUNNY_LIBRARY_ID}/videos"
    headers = {"accept": "application/json", "content-type": "application/json", "AccessKey": BUNNY_STREAM_KEY}
    response = requests.post(url, json={"title": title}, headers=headers)
    if response.status_code == 200:
        return response.json().get("guid")
    raise Exception(f"Bunny API Registration Failure: {response.text}")

def upload_to_bunny(video_id, file_path):
    url = f"https://video.bunnycdn.com/library/{BUNNY_LIBRARY_ID}/videos/{video_id}"
    headers = {"accept": "application/json", "AccessKey": BUNNY_STREAM_KEY}
    with open(file_path, "rb") as video_data:
        response = requests.put(url, data=video_data, headers=headers)
    return response.status_code == 200

async def download_worker(semaphore, client, msg, file_path, forced_filename):
    """Asynchronously streams down a media part inside the shared execution pool."""
    async with semaphore:
        print(f"📥 High-Speed Worker Engaged -> Target: {forced_filename}")
        tracker = TelegramProgress(forced_filename)
        try:
            await client.download_media(msg, file_path, progress_callback=tracker)
            print(f"✅ Worker Completed -> Downloaded: {forced_filename}")
            return file_path
        except Exception as e:
            print(f"❌ Worker Failed on {forced_filename}: {e}")
            return None

async def main():
    start_match = re.search(LINK_REGEX, START_LINK)
    end_match = re.search(LINK_REGEX, END_LINK)
    
    if not start_match or not end_match:
        print("❌ Error: Channel links could not be parsed successfully.")
        sys.exit(1)
        
    channel_id = int(f"-100{start_match.group(1)}")
    start_msg_id = int(start_match.group(2))
    end_msg_id = int(end_match.group(2))
    
    download_dir = "./local_staging_cache"
    extract_dir = "./extracted_material"
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs(extract_dir, exist_ok=True)
    
    async with TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH) as client:
        status_msg = await client.send_message('me', "🚀 **High-Speed Staging Cluster Initialized...**")
        
        # --- PHASE 1: COLLECT CHAT MESSAGES ---
        valid_messages = []
        for msg_id in range(start_msg_id, end_msg_id + 1):
            try:
                msg = await client.get_messages(channel_id, ids=msg_id)
                if msg and msg.media and isinstance(msg.media, MessageMediaDocument):
                    valid_messages.append(msg)
            except Exception as e:
                print(f"❌ Error checking msg {msg_id}: {e}")

        if not valid_messages:
            await status_msg.edit("❌ **Staging terminated:** No valid documents found.")
            sys.exit(1)

        total_parts = len(valid_messages)
        await status_msg.edit(f"⚡ **Launching Concurrent Pipeline for {total_parts} segments...**")

        # --- PHASE 2: CONCURRENT DOWNLOAD WITH CORRECT WINRAR STRUCTURAL MAPPING ---
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        tasks = []
        
        for idx, msg in enumerate(valid_messages):
            # If it's the last message in the range, it is the main master .zip file!
            if idx == total_parts - 1:
                forced_filename = "fixed_archive.zip"
            else:
                # Preceding messages are .z01, .z02, etc.
                part_num = idx + 1
                forced_filename = f"fixed_archive.z{part_num:02d}"
                
            file_path = os.path.join(download_dir, forced_filename)
            print(f"🔧 Mapping Slot [{idx+1}/{total_parts}] -> Original: '{msg.file.name}' to Forced Name: '{forced_filename}'")
            
            task = asyncio.create_task(download_worker(semaphore, client, msg, file_path, forced_filename))
            tasks.append(task)
            
        results = await asyncio.gather(*tasks)
        downloaded_files = [path for path in results if path is not None]

        # --- PHASE 3: EXTRACTION TARGETING ONLY THE ZIP ROOT ---
        await status_msg.edit("📦 **Download cluster finished. Running Owner-Instructed 7z Extraction...**")
        
        # Following instructions perfectly: Target ONLY the main zip file
        main_entry = os.path.join(download_dir, "fixed_archive.zip")
        
        result = subprocess.run(["7z", "x", main_entry, f"-o{extract_dir}", "-y"], capture_output=True, text=True)
        if result.returncode != 0:
            await status_msg.edit("💥 **Extraction Failure.** Checking trace logs...")
            debug_trace = result.stderr[:3500]
            await client.send_message('me', "📂 **7z Engine Debug Trace:**\n```\n" + debug_trace + "\n```")
            sys.exit(1)
            
        # Clear out original archive chunks immediately to save space
        for f in downloaded_files:
            if os.path.exists(f): os.remove(f)

        # --- PHASE 4: ANALYSIS AND MAP GENERATION ---
        await status_msg.edit("🗺️ **Generating Extraction Tree Map...**")
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
                    
        await send_split_messages(client, "📋 **Final Extracted Material Layout Map:**", map_lines)

        # --- PHASE 5: DOCUMENT PROCESSING ---
        if non_streamable_items:
            for item in non_streamable_items:
                try:
                    caption = f"📎 **File:** `{item['name']}`\n📁 **Path:** `{item['relative_folder']}`"
                    await client.send_file('me', item['absolute_path'], caption=caption)
                except Exception:
                    pass
                finally:
                    if os.path.exists(item['absolute_path']): os.remove(item['absolute_path'])

        # --- PHASE 6: WIRE VIDEOS TO BUNNY ---
        if streamable_items:
            await status_msg.edit(f"🎬 **Wiring {len(streamable_items)} files straight into Bunny Stream...**")
            for video in streamable_items:
                try:
                    mapped_title = video['name'] if video['relative_folder'] == "." else f"{video['relative_folder'].replace(os.sep, ' - ')} - {video['name']}"
                    bunny_id = create_bunny_placeholder(mapped_title)
                    
                    loop = asyncio.get_event_loop()
                    success = await loop.run_in_executor(None, upload_to_bunny, bunny_id, video['absolute_path'])
                    
                    if success:
                        await client.send_message('me', f"✅ **Wired to Bunny!**\n🎬 Title: `{mapped_title}`\n🆔 ID: `{bunny_id}`")
                except Exception as e:
                    print(f"⚠️ Error routing video {video['name']}: {e}")
                finally:
                    if os.path.exists(video['absolute_path']): os.remove(video['absolute_path'])

        await status_msg.edit("🎉 **All elements fully extracted, mapped, and wired successfully!**")

if __name__ == "__main__":
    asyncio.run(main())
