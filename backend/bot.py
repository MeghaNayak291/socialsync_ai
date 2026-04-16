import os
import sys
import asyncio
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler,
    ContextTypes, filters,
)

sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from database import (
    init_db, SessionLocal, get_user_by_telegram_id,
    connected_platforms, link_telegram, get_user_by_id,
)
from poster_linkedin import post_text as li_text, post_image as li_image, post_video as li_video
from poster_youtube import post_video as yt_video
from auth import decode_session_token

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

MEDIA_DIR = Path(__file__).parent / "media_temp"
MEDIA_DIR.mkdir(exist_ok=True)
BASE_URL = settings.BASE_URL


# ── Hashtag Generator (no API needed) ────────────────────────────────────────

HASHTAG_TOPICS = {
    "business":     ["#business", "#entrepreneur", "#success", "#startup", "#growth"],
    "tech":         ["#technology", "#tech", "#innovation", "#ai", "#digital"],
    "marketing":    ["#marketing", "#digitalmarketing", "#socialmedia", "#branding", "#content"],
    "motivation":   ["#motivation", "#inspiration", "#mindset", "#goals", "#success"],
    "education":    ["#education", "#learning", "#knowledge", "#skills", "#growth"],
    "health":       ["#health", "#wellness", "#fitness", "#lifestyle", "#healthy"],
    "travel":       ["#travel", "#wanderlust", "#explore", "#adventure", "#vacation"],
    "food":         ["#food", "#foodie", "#cooking", "#recipe", "#delicious"],
    "fashion":      ["#fashion", "#style", "#ootd", "#trends", "#clothing"],
    "photography":  ["#photography", "#photo", "#picoftheday", "#creative", "#art"],
    "video":        ["#video", "#reels", "#content", "#creator", "#viral"],
    "career":       ["#career", "#jobs", "#hiring", "#work", "#professional"],
    "finance":      ["#finance", "#money", "#investing", "#wealth", "#financial"],
    "coding":       ["#coding", "#programming", "#developer", "#software", "#python"],
    "ai":           ["#ai", "#artificialintelligence", "#machinelearning", "#chatgpt", "#future"],
}

GENERAL_HASHTAGS = ["#trending", "#viral", "#share", "#follow", "#like"]


def generate_hashtags(caption: str, platform: str) -> str:
    """Generate relevant hashtags based on keywords in caption."""
    caption_lower = caption.lower()
    matched = []

    for topic, tags in HASHTAG_TOPICS.items():
        if topic in caption_lower or any(t.strip("#") in caption_lower for t in tags):
            matched.extend(tags)

    # Always add some general ones
    matched.extend(GENERAL_HASHTAGS[:3])

    # Remove duplicates
    seen = set()
    unique = []
    for tag in matched:
        if tag not in seen:
            seen.add(tag)
            unique.append(tag)

    # LinkedIn: max 5 hashtags, YouTube: max 8
    limit = 5 if platform == "linkedin" else 8
    final_tags = unique[:limit] if unique else GENERAL_HASHTAGS[:limit]

    return caption + "\n\n" + " ".join(final_tags)


def generate_youtube_title(caption: str) -> str:
    """Generate YouTube title from first line of caption."""
    first_line = caption.strip().split("\n")[0]
    if len(first_line) <= 80:
        return first_line
    # Find a good cutoff point
    words = first_line[:80].split()
    return " ".join(words[:-1]) if len(words) > 1 else first_line[:80]


# ── Intent Detection (keyword based) ─────────────────────────────────────────

def detect_intent(text: str) -> dict:
    t = text.lower().strip()

    # Link token detection
    words = text.strip().split()
    for word in words:
        if len(word) > 30 and "." in word:
            return {"action": "link", "token": word}

    # Post everywhere
    if any(k in t for k in [
        "post it", "post everywhere", "post all", "share it",
        "share everywhere", "publish", "post now", "upload it",
        "post this", "share this", "go ahead", "do it"
    ]):
        return {"action": "post_all"}

    # LinkedIn only
    if any(k in t for k in [
        "linkedin", "linked in", "post linkedin",
        "only linkedin", "just linkedin"
    ]):
        return {"action": "post_linkedin"}

    # YouTube only
    if any(k in t for k in [
        "youtube", "you tube", "upload youtube",
        "only youtube", "just youtube", "yt"
    ]):
        return {"action": "post_youtube"}

    # Status check
    if any(k in t for k in [
        "status", "connected", "what platforms",
        "which platforms", "my accounts", "connections"
    ]):
        return {"action": "status"}

    # Help
    if any(k in t for k in ["help", "how", "what can you", "commands"]):
        return {"action": "help"}

    return {"action": "chat"}


def chat_response(text: str, is_linked: bool, platforms: list) -> str:
    """Simple rule-based chat responses."""
    t = text.lower()

    if any(k in t for k in ["hello", "hi", "hey", "hii", "helo"]):
        if is_linked:
            p = ", ".join(platforms) if platforms else "none yet"
            return f"Hey! 👋 I'm SocialSync. Your connected platforms: {p}\n\nJust send me content and say 'post it'!"
        return "Hey! 👋 I'm SocialSync. Sign up at the website to get started!"

    if any(k in t for k in ["thanks", "thank you", "thx", "ty"]):
        return "You're welcome! 😊 Send me more content anytime!"

    if any(k in t for k in ["good", "great", "awesome", "nice", "cool"]):
        return "Glad to hear that! 🎉 Ready to post more content?"

    if any(k in t for k in ["bye", "goodbye", "see you", "cya"]):
        return "Bye! 👋 Come back anytime to post content!"

    if any(k in t for k in ["what can you do", "features", "capabilities"]):
        return (
            "Here's what I can do! 🚀\n\n"
            "📸 Post photos → LinkedIn\n"
            "🎬 Post videos → LinkedIn + YouTube\n"
            "📝 Post text → LinkedIn\n"
            "#️⃣ Auto-generate hashtags\n"
            "🎬 Auto-generate YouTube titles\n\n"
            "Just send content and tell me where to post!"
        )

    # Default
    return (
        "I'm your social media posting assistant! 🤖\n\n"
        "Send me a photo or video and say:\n"
        "• *'post it'* — post everywhere\n"
        "• *'post on linkedin'* — LinkedIn only\n"
        "• *'upload to youtube'* — YouTube only\n\n"
        "I'll auto-add hashtags too! #️⃣"
    )


# ── Post Handler ──────────────────────────────────────────────────────────────

async def do_post(update, context, media_type: str, path: str,
                  caption: str, action: str, platforms: list, user_id: int):

    status = await update.message.reply_text("✨ Adding hashtags and posting...")
    results = []

    with SessionLocal() as db:

        # LinkedIn
        if action in ("post_all", "post_linkedin") and "linkedin" in platforms:
            enhanced = generate_hashtags(caption, "linkedin")
            await status.edit_text("📤 Posting to LinkedIn...")

            if media_type == "photo":
                r = li_image(db, user_id, path, enhanced)
            elif media_type == "video":
                r = li_video(db, user_id, path, enhanced)
            else:
                r = li_text(db, user_id, enhanced)

            if r["ok"]:
                results.append(
                    "✅ LinkedIn: Posted!\n"
                    "📝 Caption:\n" + enhanced[:200] +
                    ("..." if len(enhanced) > 200 else "")
                )
            else:
                results.append(f"❌ LinkedIn: {r.get('error', 'Failed')}")

        # YouTube
        if action in ("post_all", "post_youtube") and "youtube" in platforms and media_type == "video":
            enhanced_yt = generate_hashtags(caption, "youtube")
            title = generate_youtube_title(caption)
            await status.edit_text("📤 Uploading to YouTube...")

            r = yt_video(db, user_id, path, title=title, description=enhanced_yt)

            if r["ok"]:
                results.append(
                    f"✅ YouTube: Uploaded!\n"
                    f"🎬 Title: {title}\n"
                    f"🔗 {r.get('url', '')}"
                )
            else:
                results.append(f"❌ YouTube: {r.get('error', 'Failed')}")

    if not results:
        results = ["⚠️ No matching platforms for this content type."]

    await status.edit_text("🎉 Done!\n\n" + "\n\n".join(results))

    await asyncio.sleep(300)
    Path(path).unlink(missing_ok=True)


# ── Message Handlers ──────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg   = update.effective_user
    text = update.message.text or ""

    with SessionLocal() as db:
        user = get_user_by_telegram_id(db, str(tg.id))

    # ── Not linked ────────────────────────────────────────────────────────────
    if not user:
        intent = detect_intent(text)

        if intent.get("action") == "link":
            token_str = intent.get("token", "").strip()
            if not token_str:
                parts = text.strip().split()
                token_str = parts[-1] if parts else ""

            with SessionLocal() as db:
                user_id = decode_session_token(token_str)
                if not user_id:
                    await update.message.reply_text(
                        "❌ Invalid or expired token.\nGet a fresh one from the dashboard."
                    )
                    return
                linked_user = get_user_by_id(db, user_id)
                if not linked_user:
                    await update.message.reply_text("❌ User not found.")
                    return
                link_telegram(db, user_id, str(tg.id), tg.username)

            await update.message.reply_text(
                f"✅ Linked! Welcome, *{linked_user.username}*!\n\n"
                "Now just send me content!\n\n"
                "📸 Photo → say *'post it'*\n"
                "🎬 Video → say *'post it'* or *'upload to youtube'*\n"
                "📝 Text → say *'post on linkedin'*",
                parse_mode="Markdown",
            )
            return

        await update.message.reply_text(
            "👋 Hey! I'm *SocialSync*!\n\n"
            "To get started:\n"
            f"1️⃣ Sign up → {BASE_URL}/signup\n"
            "2️⃣ Connect LinkedIn & YouTube\n"
            "3️⃣ Copy the link token from dashboard\n"
            "4️⃣ Paste it here\n\n"
            "Then just send content and I'll post it everywhere! 🚀",
            parse_mode="Markdown",
        )
        return

    # ── Linked user ───────────────────────────────────────────────────────────
    with SessionLocal() as db:
        platforms = connected_platforms(db, user.id)

    intent = detect_intent(text)
    action = intent.get("action", "chat")

    # Re-link
    if action == "link":
        token_str = intent.get("token", "").strip()
        with SessionLocal() as db:
            user_id = decode_session_token(token_str)
            if user_id:
                link_telegram(db, user_id, str(tg.id), tg.username)
                await update.message.reply_text("✅ Account re-linked!")
            else:
                await update.message.reply_text("❌ Invalid token.")
        return

    # Status
    if action == "status":
        lines = [
            f"💼 LinkedIn: {'✅ Connected' if 'linkedin' in platforms else '❌ Not connected'}",
            f"📺 YouTube: {'✅ Connected' if 'youtube' in platforms else '❌ Not connected'}",
        ]
        await update.message.reply_text(
            "📊 Your platforms:\n\n" + "\n".join(lines) +
            f"\n\n🌐 Manage: {BASE_URL}/dashboard"
        )
        return

    # Help
    if action == "help":
        await update.message.reply_text(
            "🤖 *SocialSync Help*\n\n"
            "📸 Send photo → say *'post it'*\n"
            "🎬 Send video → say *'post it'* or *'upload to youtube'*\n"
            "📝 Send text → say *'post on linkedin'*\n\n"
            "#️⃣ Hashtags are added automatically!\n"
            "🎬 YouTube titles are generated automatically!\n\n"
            f"🌐 Dashboard: {BASE_URL}/dashboard",
            parse_mode="Markdown",
        )
        return

    # Chat
    if action == "chat":
        reply = chat_response(text, True, platforms)
        await update.message.reply_text(reply, parse_mode="Markdown")
        return

    # Post
    if action in ("post_all", "post_linkedin", "post_youtube"):
        pending = context.user_data.get("pending_media")
        if pending:
            await do_post(update, context, pending["type"], pending["path"],
                         pending["caption"] or text, action, platforms, user.id)
            context.user_data.pop("pending_media", None)
        else:
            if not platforms:
                await update.message.reply_text(
                    f"⚠️ No platforms connected!\n👉 {BASE_URL}/dashboard"
                )
                return
            if action in ("post_all", "post_linkedin") and "linkedin" in platforms:
                await do_post(update, context, "text", "", text,
                             "post_linkedin", platforms, user.id)
            else:
                await update.message.reply_text(
                    "📸 Send me a photo or video first, then tell me where to post!"
                )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg      = update.effective_user
    caption = update.message.caption or ""

    with SessionLocal() as db:
        user = get_user_by_telegram_id(db, str(tg.id))

    if not user:
        await update.message.reply_text(
            f"👋 Sign up first: {BASE_URL}/signup"
        )
        return

    with SessionLocal() as db:
        platforms = connected_platforms(db, user.id)

    photo     = update.message.photo[-1]
    photo_obj = await context.bot.get_file(photo.file_id)
    local     = MEDIA_DIR / f"{photo.file_id}.jpg"
    await photo_obj.download_to_drive(str(local))

    context.user_data["pending_media"] = {
        "type": "photo", "path": str(local), "caption": caption
    }

    if caption:
        intent = detect_intent(caption)
        if intent.get("action") in ("post_all", "post_linkedin"):
            await do_post(update, context, "photo", str(local),
                         caption, intent["action"], platforms, user.id)
            context.user_data.pop("pending_media", None)
            return

    await update.message.reply_text(
        "📸 Got your photo!\n\n"
        "Where should I post it?\n"
        "Say *'post it'* or *'post on linkedin'*",
        parse_mode="Markdown",
    )


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg      = update.effective_user
    caption = update.message.caption or ""

    with SessionLocal() as db:
        user = get_user_by_telegram_id(db, str(tg.id))

    if not user:
        await update.message.reply_text(
            f"👋 Sign up first: {BASE_URL}/signup"
        )
        return

    with SessionLocal() as db:
        platforms = connected_platforms(db, user.id)

    status = await update.message.reply_text("⬇️ Downloading your video...")
    video     = update.message.video or update.message.document
    video_obj = await context.bot.get_file(video.file_id)
    local     = MEDIA_DIR / f"{video.file_id}.mp4"
    await video_obj.download_to_drive(str(local))
    await status.delete()

    context.user_data["pending_media"] = {
        "type": "video", "path": str(local), "caption": caption
    }

    if caption:
        intent = detect_intent(caption)
        if intent.get("action") in ("post_all", "post_linkedin", "post_youtube"):
            await do_post(update, context, "video", str(local),
                         caption, intent["action"], platforms, user.id)
            context.user_data.pop("pending_media", None)
            return

    await update.message.reply_text(
        "🎬 Got your video!\n\n"
        "Where should I post it?\n"
        "Say *'post it'* or *'post on linkedin'* or *'upload to youtube'*",
        parse_mode="Markdown",
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_db()
    if not settings.TELEGRAM_BOT_TOKEN:
        log.error("❌ TELEGRAM_BOT_TOKEN not set!")
        return

    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    log.info("🤖 SocialSync Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()