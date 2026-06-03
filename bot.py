import os
import time
import asyncio
import mimetypes
import zipfile
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
import aiohttp

# --- STREAM-SPECIFIC CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "your_api_hash")
SESSION_STRING = os.environ.get("SESSION_STRING", "your_pyrogram_session")

BUNNY_LIBRARY_ID = os.environ.get("BUNNY_LIBRARY_ID", "your_library_id")
BUNNY_STREAM_KEY = os.environ.get("BUNNY_STREAM_KEY", "your_stream_api_key")

app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

def human_size(num: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} PB"

# --- HELPER: PROGRESS BAR (10-Second Delay Throttle) ---
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

# --- HELPER: BUILD A REAL TREE MAP ---
def build_zip_tree(zip_file_path):
    def empty_node():
        return {"_files": {}}

    tree = empty_node()

    with zipfile.ZipFile(zip_file_path, 'r') as z:
        for info in z.infolist():
            if info.filename.startswith('__MACOSX') or info.filename.endswith('.DS_Store'):
                continue # Ignore system garbage files
            
            parts = [p for p in info.filename.split('/') if p]
            if not parts:
                continue
                
            current_node = tree
            for part in parts[:-1]:
                if part not in current_node:
                    current_node[part] = empty_node()
                current_node = current_node[part]
            
            if not info.is_dir():
                current_node["_files"][parts[-1]] = human_size(info.file_size)
            else:
                if parts[-1] not in current_node:
                    current_node[parts[-1]] = empty_node()

    lines = []
    
    def render_node(node, prefix=""):
        dirs = sorted([k for k in node.keys() if k != "_files"])
        files = sorted(node["_files"].keys())
        total_items = len(dirs) + len(files)
        
        for i, d in enumerate(dirs):
            is_last = (i == total_items - 1 and not files)
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}📁 {d}/")
            new_prefix = prefix + ("    " if is_last else "│   ")
            render_node(node[d], new_prefix)
            
        for i, f in enumerate(files):
            is_last = (i == len(files) - 1)
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}📄 {f} ({node['_files'][f]})")

    render_node(tree)
    return lines

# --- HELPER: SEND SPLIT MESSAGES SAFE FROM CHARACTER LIMITS ---
async def send_large_tree(message, lines):
    header = "📁 **ZIP Directory Structural Map:**\n"
    current_chunk = "```text\n"
    max_chars = 3900 # Absolute threshold protection limit per bubble block
    
    first_message = True

    for line in lines:
        # Check if adding this line goes past the bubble text limit
        if len(current_chunk) + len(line) + 10 > max_chars:
            current_chunk += "```"
            if first_message:
                await message.reply_text(f"{header}{current_chunk}", quote=True)
                first_message = False
            else:
                await message.reply_text(current_chunk)
            await asyncio.sleep(1) # Prevent flooding Telegram API
            current_chunk = "```text\n"
        
        current_chunk += line + "\n"
    
    # Send remaining lines chunk
    if current_chunk != "```text\n":
        current_chunk += "```"
        if first_message:
            await message.reply_text(f"{header}{current_chunk}", quote=True)
        else:
            await message.reply_text(current_chunk)

# --- HANDLER: MEDIA HANDLING ---
@app.on_message(filters.document | filters.video)
async def handle_media(client, message):
    media = message.document or message.video
    if not media:
        return

    file_name = media.file_name or "unknown_file"
    file_size = media.file_size
    status_msg = await message.reply_text("⚡ _Analyzing incoming file pipeline..._", quote=True)

    # --- ZIP FILE LOGIC ---
    if file_name.lower().endswith('.zip'):
        await status_msg.edit_text("📂 *Downloading ZIP index to generate map...*")
        start_time = time.time()
        local_path = await client.download_media(
            message,
            progress=progress_bar,
            progress_args=(status_msg, start_time, "Downloading ZIP")
        )
        
        await status_msg.edit_text("🏗️ *Generating nested tree map...*")
        try:
            tree_lines = build_zip_tree(local_path)
            await status_msg.delete() # Clear the layout processing status message
            
            if not tree_lines:
                await message.reply_text("⚠ The ZIP file looks empty.", quote=True)
            else:
                await send_large_tree(message, tree_lines)
                
        except Exception as e:
            await message.reply_text(f"❌ Failed to map ZIP layout: `{str(e)}`", quote=True)
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

    # --- BUNNY STREAM LOGIC (.ts, .mp4, .mkv, etc.) ---
    elif file_name.lower().endswith(('.ts', '.mp4', '.mkv', '.webm', '.avi', '.mov')):
        await status_msg.edit_text("🎬 *Step 1: Creating Video instance in Bunny Stream...*")
        
        base_url = f"[https://video.bunnycdn.com/library/](https://video.bunnycdn.com/library/){BUNNY_LIBRARY_ID}/videos"
        headers = {
            "AccessKey": BUNNY_STREAM_KEY,
            "accept": "application/json",
            "content-type": "application/json"
        }
        
        async with aiohttp.ClientSession() as session:
            video_id = None
            try:
                async with session.post(base_url, json={"title": file_name}, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        video_id = data.get("guid")
                    else:
                        err_text = await resp.text()
                        await status_msg.edit_text(f"❌ Failed creating video instance: `{resp.status}`\n`{err_text}`")
                        return
            except Exception as e:
                await status_msg.edit_text(f"❌ Connection error during allocation: `{str(e)}`")
                return

            await status_msg.edit_text("🚀 *Step 2: Pumping raw binary data to Stream...*")
            start_time = time.time()
            
            async def file_stream_generator():
                current_buffered = 0
                async for chunk in client.stream_media(message):
                    yield chunk
                    current_buffered += len(chunk)
                    await progress_bar(current_buffered, file_size, status_msg, start_time, "Streaming to Bunny Video")

            upload_url = f"{base_url}/{video_id}"
            upload_headers = {
                "AccessKey": BUNNY_STREAM_KEY,
                "Content-Type": "application/octet-stream"
            }
            
            try:
                async with session.put(upload_url, data=file_stream_generator(), headers=upload_headers) as response:
                    if response.status == 200:
                        elapsed = time.time() - start_time
                        await status_msg.edit_text(
                            f"✅ **Video Direct Stream Completed!**\n\n"
                            f"🌐 **Title:** `{file_name}`\n"
                            f"🆔 **Video ID:** `{video_id}`\n"
                            f"📦 **Size:** {human_size(file_size)}\n"
                            f"⏱️ **Time:** {int(elapsed // 60)}m {int(elapsed % 60)}s\n\n"
                            f"⚙️ _Bunny is now processing resolutions/transcoding._"
                        )
                    else:
                        await status_msg.edit_text(f"❌ Binary delivery failed. Code: `{response.status}`")
            except Exception as e:
                await status_msg.edit_text(f"❌ Stream delivery broken: `{str(e)}`")
    else:
        await status_msg.edit_text("⚠️ Unsupported format. Use a `.zip` or a streamable video.")

if __name__ == "__main__":
    app.run()
