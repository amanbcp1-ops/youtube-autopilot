import os, random, asyncio, requests, json, textwrap
from pathlib import Path

import google.generativeai as genai
import edge_tts
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips
from PIL import Image, ImageDraw, ImageFont
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ── Keys (loaded automatically from GitHub Secrets) ─────────────────
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
PEXELS_KEY = os.environ["PEXELS_API_KEY"]

# ── Voice styles (rotates randomly each video) ───────────────────────
VOICES = [
    "en-US-JennyNeural",   # Friendly & conversational
    "en-US-GuyNeural",     # Deep & storytelling
    "en-US-AriaNeural",    # Calm & professional
]

# ────────────────────────────────────────────────────────────────────
print("=" * 50)
print("🚀 YouTube Auto-Publisher starting...")
print("=" * 50)

# ── Step 1: Read your topic ──────────────────────────────────────────
print("\n📖 Reading topic from topic.txt...")
topic = Path("topic.txt").read_text().strip()
print(f"   Topic: {topic}")

# ── Step 2: Write the script using Gemini AI ─────────────────────────
print("\n✍️  Writing script with Gemini AI...")
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

script_prompt = f"""
Write a compelling 4-5 minute YouTube video script about: {topic}

Important rules:
- Open with a shocking fact or question to hook the viewer in 5 seconds
- Use short sentences — easy to listen to
- Sound like a real person talking, not a textbook
- Include 2-3 surprising or lesser-known facts
- End with: "If this blew your mind, hit subscribe — new videos every few days."
- Write ONLY the spoken words. No stage directions. No timestamps. No headings.
- Target length: 450 to 550 words
"""

script = model.generate_content(script_prompt).text.strip()
Path("script.txt").write_text(script)
print(f"   ✅ Script done ({len(script.split())} words)")

# ── Step 3: Generate voiceover ───────────────────────────────────────
print("\n🎙️  Generating voiceover...")
voice = random.choice(VOICES)
print(f"   Using voice: {voice}")

async def make_audio():
    await edge_tts.Communicate(script, voice).save("voiceover.mp3")

asyncio.run(make_audio())
print("   ✅ Voiceover saved")

# Get exact audio length
audio_clip = AudioFileClip("voiceover.mp3")
audio_duration = audio_clip.duration
audio_clip.close()
print(f"   Audio length: {audio_duration:.1f} seconds")

# ── Step 4: Fetch stock footage from Pexels ──────────────────────────
print("\n🎬  Fetching stock footage from Pexels...")
keywords = " ".join(topic.replace("Write a 5-minute YouTube script about", "").split()[:4]).strip()
print(f"   Searching for: '{keywords}'")

headers = {"Authorization": PEXELS_KEY}
resp = requests.get(
    "https://api.pexels.com/videos/search",
    headers=headers,
    params={"query": keywords, "per_page": 12, "orientation": "landscape", "size": "medium"}
)
pexels_data = resp.json()
videos_list = pexels_data.get("videos", [])

video_paths = []
total_downloaded = 0

for i, vid in enumerate(videos_list[:8]):
    files = vid.get("video_files", [])
    # Prefer HD, fallback to SD
    chosen = next((f for f in files if f.get("quality") == "hd"), None)
    if not chosen:
        chosen = next((f for f in files if f.get("quality") == "sd"), None)
    if not chosen:
        continue

    url = chosen["link"]
    path = f"clip_{i}.mp4"
    print(f"   Downloading clip {i+1}...")

    with requests.get(url, stream=True, timeout=60) as r:
        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                f.write(chunk)

    try:
        clip_check = VideoFileClip(path)
        dur = clip_check.duration
        clip_check.close()
        video_paths.append(path)
        total_downloaded += dur
        print(f"   ✅ Clip {i+1} downloaded ({dur:.1f}s)")
    except Exception:
        print(f"   ⚠️  Clip {i+1} was corrupt, skipping")
        continue

    if total_downloaded >= audio_duration + 10:
        break

print(f"   Total footage: {total_downloaded:.1f}s for a {audio_duration:.1f}s video")

# ── Step 5: Assemble the video ───────────────────────────────────────
print("\n🎞️  Assembling video...")

clips = []
for path in video_paths:
    try:
        c = VideoFileClip(path).resize((1280, 720))
        clips.append(c)
    except Exception as e:
        print(f"   ⚠️  Skipping {path}: {e}")

if not clips:
    raise RuntimeError("No usable video clips found. Check Pexels API key.")

video = concatenate_videoclips(clips, method="compose")
video = video.subclip(0, min(audio_duration, video.duration))
audio = AudioFileClip("voiceover.mp3")
final_video = video.set_audio(audio)

print("   Rendering... (this takes 3-5 mins on GitHub Actions)")
final_video.write_videofile(
    "output.mp4",
    fps=24,
    codec="libx264",
    audio_codec="aac",
    logger=None
)
print("   ✅ Video rendered!")

# ── Step 6: Create thumbnail ─────────────────────────────────────────
print("\n🖼️  Creating thumbnail...")

img = Image.new("RGB", (1280, 720))
draw = ImageDraw.Draw(img)

# Dark gradient background
for y in range(720):
    shade = int(10 + (y / 720) * 35)
    draw.line([(0, y), (1280, y)], fill=(shade, shade + 5, shade + 25))

# Accent bar at top
draw.rectangle([(0, 0), (1280, 8)], fill=(255, 80, 50))

# Try to load a bold font, fall back gracefully
try:
    font_big = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 78)
    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 38)
except Exception:
    font_big = ImageFont.load_default()
    font_small = font_big

# Main title (wrapped)
clean_topic = topic.replace("Write a 5-minute YouTube script about", "").strip().title()
lines = textwrap.wrap(clean_topic, width=18)

y_pos = 220
for line in lines[:3]:
    bbox = draw.textbbox((0, 0), line, font=font_big)
    w = bbox[2] - bbox[0]
    x = (1280 - w) // 2
    draw.text((x + 3, y_pos + 3), line, font=font_big, fill=(0, 0, 0))   # shadow
    draw.text((x, y_pos), line, font=font_big, fill=(255, 255, 255))
    y_pos += 95

img.save("thumbnail.jpg", quality=95)
print("   ✅ Thumbnail created!")

# ── Step 7: Generate title, description & tags ───────────────────────
print("\n📝  Generating video metadata...")

meta_prompt = f"""
Create YouTube metadata for a video about: {topic}

Return ONLY a valid JSON object. No markdown. No explanation. No code fences.

{{
  "title": "catchy title under 65 characters with a number or question",
  "description": "2 paragraphs, 120-150 words total, includes keywords naturally, ends with: Subscribe for more every few days!",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10"]
}}
"""

meta_raw = model.generate_content(meta_prompt).text.strip()
# Clean up any accidental markdown fences
if "```" in meta_raw:
    meta_raw = meta_raw.split("```")[1]
    if meta_raw.startswith("json"):
        meta_raw = meta_raw[4:].strip()

meta = json.loads(meta_raw)
print(f"   Title: {meta['title']}")

# ── Step 8: Upload to YouTube ────────────────────────────────────────
print("\n📤  Uploading to YouTube...")

token_data = json.loads(Path("token.json").read_text())
creds = Credentials(
    token=token_data["token"],
    refresh_token=token_data["refresh_token"],
    token_uri="https://oauth2.googleapis.com/token",
    client_id=token_data["client_id"],
    client_secret=token_data["client_secret"],
    scopes=["https://www.googleapis.com/auth/youtube.upload"]
)

youtube = build("youtube", "v3", credentials=creds)

video_body = {
    "snippet": {
        "title": meta["title"],
        "description": meta["description"],
        "tags": meta["tags"],
        "categoryId": "22"
    },
    "status": {"privacyStatus": "public"}
}

media_file = MediaFileUpload("output.mp4", chunksize=-1, resumable=True)
upload = youtube.videos().insert(
    part="snippet,status",
    body=video_body,
    media_body=media_file
)

response = None
while response is None:
    status, response = upload.next_chunk()
    if status:
        print(f"   Uploading... {int(status.progress() * 100)}%")

video_id = response["id"]
print(f"   ✅ Video uploaded!")

# Set thumbnail
youtube.thumbnails().set(
    videoId=video_id,
    media_body=MediaFileUpload("thumbnail.jpg")
).execute()

print("\n" + "=" * 50)
print(f"🎉 ALL DONE!")
print(f"   Your video is live at:")
print(f"   https://youtube.com/watch?v={video_id}")
print("=" * 50)
