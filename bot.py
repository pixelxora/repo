import os
import time
import asyncio
import mimetypes
import zipfile
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
import aiohttp

# --- CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", 12345))
API_HASH = os.environ.get("API_HASH", "your_api_hash")
SESSION_STRING = os.environ.get("SESSION_STRING", "your_pyrogram_session")
BUNNY_STORAGE_ZONE = os.environ.get("BUNNY_STORAGE_ZONE", "my-zone")
BUNNY_API_KEY = os.environ.get("BUNNY_API_KEY", "your_bunny_api_key")
BUNNY_REGION = os.environ.get("BUNNY_REGION", "storage") 

app = Client("userbot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

# --- HELPER: FORMAT SIZE ---
def human_size(num: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} PB"

# --- HELPER: PROGRESS BAR (10s Delay for User updates) ---
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

# --- HANDLER: MEDIA HANDLING ---
@app.on_message(filters.document | filters.video)
async def handle_media(client, message):
    media = message.document or message.video
    if not media:
        return

    file_name = media.file_name or "unknown_file"
    file_size = media.file_size
    status_msg = await message.reply_text("⚡ _Analyzing incoming file pipeline..._", quote=True)

    # 1. ZIP Inspection
    if file_name.lower().endswith('.zip'):
        await status_msg.edit_text("📂 *Downloading ZIP index to generate map...*")
        start_time = time.time()
        local_path = await client.download_media(
            message,
            progress=progress_bar,
            progress_args=(status_msg, start_time, "Downloading ZIP")
        )
        
        await status_msg.edit_text("🏗️ *Generating folder tree...*")
        try:
            with zipfile.ZipFile(local_path, 'r') as z:
                tree_lines = ["📁 **ZIP Contents:**\n"]
                for info in sorted(z.infolist(), key=lambda x: x.filename):
                    parts = info.filename.rstrip('/').split('/')
                    depth = len(parts) - 1
                    indent = "    " * depth
                    if info.is_dir():
                        tree_lines.append(f"{indent}└── 📁 {parts[-1]}/")
                    else:
                        tree_lines.append(f"{indent}└── 📄 {parts[-1]} *({human_size(info.file_size)})*")
                
                output_text = "\n".join(tree_lines)
                if len(output_text) > 4000:
                    with open("tree.txt", "w", encoding="utf-8") as f:
                        f.write(output_text)
                    await message.reply_document("tree.txt", caption="📂 Structure map.")
                    os.remove("tree.txt")
                else:
                    await status_msg.edit_text(output_text)
        except Exception as e:
            await status_msg.edit_text(f"❌ Failed to parse ZIP: {str(e)}")
        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

    # 2. Streamable files Upload to Bunny
    elif file_name.lower().endswith(('.ts', '.mp4', '.mkv', '.webm', '.avi', '.mov')):
        await status_msg.edit_text("🚀 *Initialising direct stream to Bunny.net...*")
        
        async def file_stream_generator():
            current_buffered = 0
            async for chunk in client.stream_media(message):
                yield chunk
                current_buffered += len(chunk)
                await progress_bar(current_buffered, file_size, status_msg, start_time, "Streaming to Bunny")

        start_time = time.time()
        endpoint = f"https://{BUNNY_REGION}.bunnystorage.com/{BUNNY_STORAGE_ZONE}/{file_name}"
        headers = {
            "AccessKey": BUNNY_API_KEY,
            "Content-Type": mimetypes.guess_type(file_name)[0] or "application/octet-stream"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.put(endpoint, data=file_stream_generator(), headers=headers) as response:
                    if response.status in [200, 201]:
                        elapsed = time.time() - start_time
                        await status_msg.edit_text(
                            f"✅ **Uploaded Successfully to Bunny.net!**\n\n"
                            f"🌐 **File:** `{file_name}`\n"
                            f"📦 **Size:** {human_size(file_size)}\n"
                            f"⏱️ **Time Taken:** {int(elapsed // 60)}m {int(elapsed % 60)}s"
                        )
                    else:
                        await status_msg.edit_text(f"❌ Bunny Error Code: `{response.status}`")
        except Exception as e:
            await status_msg.edit_text(f"❌ Stream Error: `{str(e)}`")
    else:
        await status_msg.edit_text("⚠️ Please forward a `.zip` or a streamable video format.")

if __name__ == "__main__":
    app.run()
