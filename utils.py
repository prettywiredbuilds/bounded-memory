"""Utility functions and constants for persistent conversation memory.

This module provides:
- local file and environment configuration
- MongoDB collection helpers
- session-id persistence helpers
- token-count and history-trimming helpers
- rolling summary merge behavior
"""

import os
from dotenv import load_dotenv
from pathlib import Path

ENV_FILE = Path(__file__).resolve().with_name(".env")
SESSION_ID_FILE = Path(__file__).resolve().with_name(".session_id")
DATABASE_NAME = "agent_conversation_memory"
SESSIONS_COLLECTION_NAME = "sessions"
LOGS_COLLECTION_NAME = "logs"
SYSTEM_PROMPT_FILE = Path(__file__).resolve().with_name("system_prompt.md")
MAX_SESSION_MESSAGE_TOKENS = 700
SUMMARY_MODEL = "claude-haiku-4-5"
SUMMARY_MAX_TOKENS = 400


def build_request_system_prompt(system_prompt, summary):
    """Return request-time system prompt with optional rolling summary appended."""
    if not summary:
        return system_prompt

    return (
        f"{system_prompt.rstrip()}\n\n"
        f"Conversation summary so far:\n{summary}"
    )


def load_session_id():
    """Load the local session id from disk, returning None when missing/empty."""
    if not SESSION_ID_FILE.exists():
        return None

    session_id = SESSION_ID_FILE.read_text(encoding="utf-8").strip()
    return session_id or None


def save_session_id(session_id):
    """Persist the active session id so future runs can resume the same chat."""
    SESSION_ID_FILE.write_text(session_id, encoding="utf-8")


def get_trimmed_messages_and_dropped_messages(messages, max_tokens):
    """Split history into kept and dropped messages using an exchange-aware budget.

    The latest user/assistant exchange is always retained. Older exchanges are
    added from newest to oldest while the cumulative token count remains within
    max_tokens.
    """
    if len(messages) <= 2:
        return messages, []

    latest_exchange = messages[-2:]
    latest_exchange_tokens = sum(message.get("token_count", 0) for message in latest_exchange)

    kept_reversed = list(reversed(latest_exchange))
    total_tokens = latest_exchange_tokens

    if len(messages) == 2:
        return latest_exchange, []

    remaining_messages = messages[:-2]

    dropped_prefix = []
    if len(remaining_messages) % 2 != 0:
        dropped_prefix = remaining_messages[:1]
        remaining_messages = remaining_messages[1:]

    exchanges = [
        remaining_messages[index:index + 2]
        for index in range(0, len(remaining_messages), 2)
    ]

    kept_exchange_count = 0

    for exchange in reversed(exchanges):
        exchange_tokens = sum(message.get("token_count", 0) for message in exchange)

        if total_tokens + exchange_tokens > max_tokens:
            break

        kept_reversed.extend(reversed(exchange))
        total_tokens += exchange_tokens
        kept_exchange_count += 1

    dropped_exchanges = exchanges[: len(exchanges) - kept_exchange_count]
    dropped_messages = dropped_prefix + [
        message
        for exchange in dropped_exchanges
        for message in exchange
    ]

    return list(reversed(kept_reversed)), dropped_messages


def trim_messages_to_token_budget(messages, max_tokens):
    """Return only the kept subset from exchange-aware token trimming."""
    trimmed_messages, _ = get_trimmed_messages_and_dropped_messages(messages, max_tokens)
    return trimmed_messages


def format_messages_for_summary(messages):
    """Format messages as plain text transcript blocks for summary merging."""
    lines = []
    for message in messages:
        role = message.get("role", "unknown").capitalize()
        content = message.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n\n".join(lines)


def merge_summary(client, existing_summary, dropped_messages):
    """Merge dropped messages into the rolling summary using a cheap model call."""
    if not dropped_messages:
        return existing_summary

    existing_summary_text = existing_summary.strip() or "None"
    dropped_messages_text = format_messages_for_summary(dropped_messages)

    response = client.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=SUMMARY_MAX_TOKENS,
        system=(
            "You maintain a rolling conversation summary. Merge the existing summary with the "
            "older messages that are being removed from active history. Preserve durable context "
            "such as user preferences, goals, constraints, decisions, facts, and unresolved questions. "
            "Write concise plain text paragraphs only. Do not use bullet points, XML, JSON, or headings."
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Existing summary:\n{existing_summary_text}\n\n"
                    f"Messages being dropped:\n{dropped_messages_text}\n\n"
                    "Return the updated rolling summary only."
                ),
            }
        ],
    )

    return response.content[0].text.strip()


def get_connection_string():
    """Load and return CONNECTION_STRING from local .env or process environment."""
    load_dotenv(dotenv_path=ENV_FILE)
    connection_string = os.getenv("CONNECTION_STRING")
    if not connection_string:
        raise ValueError(
            "Missing CONNECTION_STRING. Add it to memory/.env or set it in your environment."
        )
    return connection_string


def get_database(client):
    """Return the configured MongoDB database handle."""
    database = client[DATABASE_NAME]
    print(f"Connected to database: {database.name}")
    return database


def get_collection(client, collection_name):
    """Return a collection handle from the configured database."""
    database = get_database(client)
    collection = database[collection_name]
    print(f"Connected to collection: {collection_name}")
    return collection


def load_system_prompt():
    """Read and return the base system prompt markdown content."""
    with SYSTEM_PROMPT_FILE.open("r", encoding="utf-8") as file:
        system_prompt = file.read()
    return system_prompt


def get_token_count(client, system_prompt, history, user_message):
    """Count input tokens for system+history+message using Anthropic API."""
    response = client.messages.count_tokens(
        model="claude-opus-4-7",
        system=system_prompt,
        messages=history + [user_message],
    )
    return response.input_tokens


def upsert_responses(collection, document):
    """Replace or insert a session document keyed by session_id."""
    collection.replace_one({"session_id": document["session_id"]}, document, upsert=True)


def insert_session_log(collection, session_id, message):
    """Insert one raw message event into the append-only logs collection."""
    document = {"session_id": session_id, **message}
    collection.insert_one(document)
    print(f"Inserted session log: {document['role']}")