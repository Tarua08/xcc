"""Telegram Bot for approving/rejecting X Content Agent drafts.

Sends pending drafts as messages with Approve/Reject inline buttons.
On Approve → posts to X via the X API, marks as approved in Firestore.
On Reject → marks as rejected in Firestore.

Run: python -m x_content_agent.services.telegram_bot
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

_root = Path(__file__).parent.parent.parent
load_dotenv(_root / ".env.local")  # secrets (local dev only, ignored in prod)
load_dotenv(_root / ".env")        # non-secret config

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from ..shared.firestore_client import FirestoreClient
from ..shared.models import DraftStatus
from ..shared.x_poster import get_poster

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

_db: FirestoreClient | None = None


def get_db() -> FirestoreClient:
    global _db
    if _db is None:
        _db = FirestoreClient(project_id=os.getenv("GOOGLE_CLOUD_PROJECT"))
    return _db


# ---------------------------------------------------------------------------
# /start command
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "Welcome to XContent Bot!\n\n"
        "Commands:\n"
        "/drafts — Review pending drafts\n"
        "/approved — View approved posts\n"
        "/stats — Pipeline statistics\n\n"
        "Tap Approve to post directly to X. Tap Reject to skip."
    )


# ---------------------------------------------------------------------------
# /drafts — send pending drafts with approve/reject buttons
# ---------------------------------------------------------------------------

async def cmd_drafts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send pending drafts with inline approve/reject buttons."""
    db = get_db()
    drafts = db.list_drafts(status=DraftStatus.PENDING, limit=20)

    if not drafts:
        await update.message.reply_text("No pending drafts. Run the pipeline to generate new ones.")
        return

    await update.message.reply_text(f"Sending {len(drafts)} pending drafts for review...")

    for draft in drafts:
        # Get the source item for context
        source_item = db.get_item(draft.item_id)
        source_info = ""
        if source_item:
            source_info = f"\nSource: {source_item.source.value} | {source_item.title[:60]}"

        char_count = len(draft.content)
        quality = f"Quality: {draft.quality_score}/100" if draft.quality_score else ""

        text = (
            f"📝 *Draft {draft.draft_id}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{draft.content}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 {char_count}/280 chars | {quality}"
            f"{source_info}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve & Post", callback_data=f"approve:{draft.draft_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{draft.draft_id}"),
            ]
        ])

        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /approved — show recently approved posts
# ---------------------------------------------------------------------------

async def cmd_approved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show recently approved/posted drafts."""
    db = get_db()
    approved = db.list_drafts(status=DraftStatus.APPROVED, limit=10)

    if not approved:
        await update.message.reply_text("No approved posts yet.")
        return

    text = f"✅ *{len(approved)} Approved Posts*\n\n"
    for d in approved[:10]:
        text += f"• {d.content[:80]}...\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /stats — pipeline statistics
# ---------------------------------------------------------------------------

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show pipeline statistics."""
    db = get_db()
    pending = len(db.list_drafts(status=DraftStatus.PENDING))
    approved = len(db.list_drafts(status=DraftStatus.APPROVED))
    rejected = len(db.list_drafts(status=DraftStatus.REJECTED))

    text = (
        "📊 *Pipeline Stats*\n\n"
        f"⏳ Pending: {pending}\n"
        f"✅ Approved: {approved}\n"
        f"❌ Rejected: {rejected}\n"
        f"📝 Total: {pending + approved + rejected}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Callback handler — approve/reject button presses
# ---------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle approve/reject button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data
    action, draft_id = data.split(":", 1)

    db = get_db()
    draft = db.get_draft(draft_id)

    if not draft:
        await query.edit_message_text(f"Draft {draft_id} not found.")
        return

    if action == "approve":
        # Post to X
        poster = get_poster()
        tweet_result = None

        if poster.is_configured:
            tweet_result = poster.post_tweet(draft.content)

        from datetime import datetime, timezone

        updates = {
            "status": DraftStatus.APPROVED.value,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }

        if tweet_result and tweet_result["success"]:
            updates["tweet_id"] = tweet_result["tweet_id"]
            updates["tweet_url"] = tweet_result["tweet_url"]

        db.update_draft(draft_id, updates)

        if tweet_result and tweet_result["success"]:
            await query.edit_message_text(
                f"✅ *Posted to X!*\n\n"
                f"{draft.content}\n\n"
                f"🔗 {tweet_result['tweet_url']}",
                parse_mode="Markdown",
            )
        elif tweet_result and not tweet_result["success"]:
            await query.edit_message_text(
                f"⚠️ Approved but X posting failed:\n{tweet_result['error']}\n\n"
                f"{draft.content}",
            )
        else:
            await query.edit_message_text(
                f"✅ *Approved* (X API not configured)\n\n{draft.content}",
                parse_mode="Markdown",
            )

    elif action == "reject":
        from datetime import datetime, timezone

        db.update_draft(draft_id, {
            "status": DraftStatus.REJECTED.value,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        })
        await query.edit_message_text(
            f"❌ *Rejected*\n\n~~{draft.content}~~",
            parse_mode="Markdown",
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the Telegram bot."""
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("drafts", cmd_drafts))
    app.add_handler(CommandHandler("approved", cmd_approved))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Telegram bot @Xai-7 starting...")
    print("Bot is running! Send /drafts to @Xai-7 to review posts.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
