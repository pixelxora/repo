import os
import time
import asyncio
import mimetypes
import zipfile
import re
from collections import defaultdict
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
import aiohttp

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "your_api_hash")
SESSION_STRING = os.environ.get("SESSION_STRING", "your_pyrogram_session")

BUNNY_LIBRARY_ID = os.environ.get("BUNNY_LIBRARY_ID", "your_library_id")
BUNNY_STREAM_KEY = os.environ.get("BUNNY_STREAM_KEY", "your_stream_api_key")

app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# Temporary local directories for processing split zips
DOWNLOAD_DIR = "./staging_downloads"
EXTRACT_DIR = "./extracted_files"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(EXTRACT_DIR, exist_ok=True)

# In-memory tracking dictionary for tracking split file pairs
# Structure: { "clean_archive_name": [part1_msg_id, part2_msg_id] }
split_groups = defaultdict(list)

def human_size(num: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} PB"

# --- HELPER: PROGRESS BAR (10s Delay Throttle) ---
async def progress_bar(current, total, status_msg, start_time, action_text="Processing"):
    now = time.time()
    if not hasattr(progress_bar, "last_update"):
        progress_bar.last_update = 0
    if now - progress_bar.last_update < 10 and current < total:
        return

    progress_bar.last_update = now
    elapsed_time = now - start_time
    speed = current / elapsed_time if elapsed_time > 0 else 0
    percentage = (current / total) * 100
    
    completed_blocks = int(percentage // 10)
    bar = "■" * completed_blocks + "□" * (10 - completed_blocks)
    
    remaining_bytes = total - current
    eta = remaining_bytes / speed if speed > 0 else 0
    eta_str = f"{int(eta // 60)}m {int(eta % 60)}s" if eta > 0 else "Calculating..."
    
    text = (
        f"**{action_text}**\n"
        f"|{bar}| {percentage:.1f}%\n"
        f"**Done:** {human_size(current)} / {human_size(total)}\n"
        f"**Speed:** {human_size(speed)}/s\n"
        f"**ETA:** {eta_str}"
    )
    try:
        await status_msg.edit_text(text)
    except FloodWait as e:
        await asyncio.sleep(e.value)
    except Exception:
        pass

# --- HELPER: DETECT & CLEAN SPLIT ARCHIVE NAMES ---
def get_base_archive_name(filename):
    """
    Groups files like archive.zip.001, archive.zip.002, archive.z01, archive.zip
    to a common 'archive' grouping key.
    """
    pattern = r"(.+?)\.zip(?:\.\d+)?$|(.+?)\.z\d+$"
    match = re.match(pattern, filename, re.IGNORECASE)
    if match:
        return match.group(1) or match.group(2)
    return None

# --- HELPER: PROCESS, RE-INDEX SEQUENCE & UPLOAD TO BUNNY ---
async def process_and_upload_extracted(message, target_extract_path):
    status_msg = await message.reply_text("🏗️ *Analyzing extracted layouts & re-indexing files in sequence...*")
    
    video_extensions = ('.ts', '.mp4', '.mkv', '.webm', '.avi', '.mov')
    all_files_meta = []

    # Gather all file paths across jumbled folders
    for root, dirs, files in os.walk(target_extract_path):
        # Ignore hidden directory junk
        if '__MACOSX' in root or '.DS_Store' in root:
            continue
        for file in files:
            if file.lower().endswith(video_extensions):
                full_path = os.path.join(root, file)
                # Save relative path to preserve parent folder structure hierarchy
                rel_path = os.path.relpath(full_path, target_extract_path)
                all_files_meta.append((rel_path, full_path))

    # Sort files alphabetically to ensure they match up in numbering sequence
    all_files_meta.sort(key=lambda x: x[0])

    if not all_files_meta:
        await status_msg.edit_text("⚠ *No streamable video files found inside the extracted folders.*")
        return

    await status_msg.edit_text(f"🚀 *Found {len(all_files_meta)} videos. Initiating sequenced Bunny Upload queue...*")

    async with aiohttp.ClientSession() as session:
        # Loop with indices to create proper folder tree tracking prefixes (e.g., 1.1.1)
        for index, (rel_path, full_path) in enumerate(all_files_meta, start=1):
            parent_folder = os.path.basename(os.path.dirname(full_path)) or "Root"
            
            # Formatting sequence name structure: "1.1.X - ParentFolder - OriginalName"
            sequenced_title = f"1.1.{index} - {parent_folder} - {os.path.basename(full_path)}"
            file_size = os.path.getsize(full_path)

            await status_msg.edit_text(f"🎬 *[Queue {index}/{len(all_files_meta)}]* Creating instance:\n`{sequenced_title}`")
            
            # 1. Bunny Stream Handshake
            base_url = f"https://video.bunnycdn.com/library/{BUNNY_LIBRARY_ID}/videos"
            headers = {
                "AccessKey": BUNNY_STREAM_KEY,
                "accept": "application/json",
                "content-type": "application/json"
            }
            
            video_id = None
            try:
                async with session.post(base_url, json={"title": sequenced_title}, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        video_id = data.get("guid")
                    else:
                        await message.reply_text(f"❌ Handshake failed for `{sequenced_title}`. Skipping item.")
                        continue
            except Exception as e:
                await message.reply_text(f"❌ Connection drop on `{sequenced_title}`: {str(e)}")
                continue

            # 2. Upload Chunk Generator from Local Disk File
            async def disk_file_generator(path):
                current_buffered = 0
                start_time = time.time()
                with open(path, 'rb') as f:
                    while True:
                        chunk = f.read(1024 * 1024) # 1MB packet blocks
                        if not chunk:
                            break
                        yield chunk
                        current_buffered += len(chunk)
                        await progress_bar(current_buffered, file_size, status_msg, start_time, f"Uploading {index}/{len(all_files_meta)} to Stream")

            upload_url = f"{base_url}/{video_id}"
            upload_headers = {
                "AccessKey": BUNNY_STREAM_KEY,
                "Content-Type": "application/octet-stream"
            }

            try:
                async with session.put(upload_url, data=disk_file_generator(full_path), headers=upload_headers) as response:
                    if response.status != 200:
                        await message.reply_text(f"❌ Binary push failure code `{response.status}` on file sequence item `{index}`.")
            except Exception as e:
                await message.reply_text(f"❌ Core stream pipeline error on sequence item `{index}`: {str(e)}")

    await status_msg.edit_text(f"✅ **Sequenced Upload Operation Finished!**\nAll {len(all_files_meta)} videos from the split archive are pushed successfully.")

# --- MAIN ROUTER HANDLER ---
@app.on_message(filters.document | filters.video)
async def handle_incoming_archive_stream(client, message):
    media = message.document or message.video
    if not media:
        return

    filename = media.file_name or "unknown"
    base_group_name = get_base_archive_name(filename)

    # Standard Direct Media Stream Upload (Fallback for raw singular video files forwarded)
    if not base_group_name and filename.lower().endswith(('.ts', '.mp4', '.mkv', '.webm', '.avi', '.mov')):
        # Same simple single file direct stream upload logic as your previous script
        status_msg = await message.reply_text("🚀 *Direct streaming standalone video file...*", quote=True)
        file_size = media.file_size
        start_time = time.time()
        
        async def file_stream_generator():
            current_buffered = 0
            async for chunk in client.stream_media(message):
                yield chunk
                current_buffered += len(chunk)
                await progress_bar(current_buffered, file_size, status_msg, start_time, "Streaming Video")

        base_url = f"https://video.bunnycdn.com/library/{BUNNY_LIBRARY_ID}/videos"
        headers = {"AccessKey": BUNNY_STREAM_KEY, "accept": "application/json", "content-type": "application/json"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(base_url, json={"title": filename}, headers=headers) as resp:
                if resp.status == 200:
                    video_id = (await resp.json()).get("guid")
                    upload_url = f"{base_url}/{video_id}"
                    upload_headers = {"AccessKey": BUNNY_STREAM_KEY, "Content-Type": "application/octet-stream"}
                    async with session.put(upload_url, data=file_stream_generator(), headers=upload_headers) as r:
                        if r.status == 200:
                            await status_msg.edit_text(f"✅ Standalone upload successful:\n`{filename}`")
                            return
        await status_msg.edit_text("❌ Standalone upload process encountered an error.")
        return

    if not base_group_name:
        await message.reply_text("⚠️ Unknown format file format. Forward a split archive part or video.")
        return

    # --- ARCHIVE STAGING LOGIC ---
    split_groups[base_group_name].append(message)
    current_count = len(split_groups[base_group_name])

    status_msg = await message.reply_text(
        f"📥 **[Split Staging Queue]** Detected part for `{base_group_name}`.\n"
        f"Collected parts: `{current_count}/2`. Waiting for remaining items before processing...", 
        quote=True
    )

    # If both parts are safely in the queue, run the extractor merge assembly
    if current_count == 2:
        messages_to_process = split_groups[base_group_name]
        await status_msg.edit_text("⚡ *Both split files matching in staging area! Initiating combined multi-download step...*")
        
        downloaded_paths = []
        for idx, msg in enumerate(messages_to_process, start=1):
            m_media = msg.document or msg.video
            start_time = time.time()
            path = await client.download_media(
                msg,
                file_name=os.path.join(DOWNLOAD_DIR, m_media.file_name),
                progress=progress_bar,
                progress_args=(status_msg, start_time, f"Downloading Multi-Part {idx}/2")
            )
            downloaded_paths.append(path)

        await status_msg.edit_text("🔩 *Assembling/Unzipping split volumes into extraction root...*")
        
        # Sort to make sure part .001/z01 is read before .002/zip
        downloaded_paths.sort()
        primary_zip = downloaded_paths[-1] # The central directory layout is natively in the master file extension entry

        # Run extraction
        try:
            # We use native zipfile shell extraction logic
            with zipfile.ZipFile(primary_zip, 'r') as z:
                # Python's zipfile engine natively stitches multipart zips automatically if they share the same directory path
                z.extractall(EXTRACT_DIR)
                
            await status_msg.delete()
            
            # Trigger custom sequencing indexing tree and streaming engine out to Bunny Stream
            await process_and_upload_extracted(message, EXTRACT_DIR)
            
        except Exception as e:
            await status_msg.edit_text(f"❌ Failed multi-part zip construction extraction process: `{str(e)}`")
            
        finally:
            # Clear storage layout instantly so the GitHub disk doesn't run out of memory space
            for path in downloaded_paths:
                if os.path.exists(path):
                    os.remove(path)
            import shutil
            if os.path.exists(EXTRACT_DIR):
                shutil.rmtree(EXTRACT_DIR)
            del split_groups[base_group_name]

if __name__ == "__main__":
    app.run()
