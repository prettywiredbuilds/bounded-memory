"""Interactive chat loop with rolling-summary conversation memory.

This module orchestrates the end-to-end runtime flow:
- load base system prompt and persistent session id
- load/create a session document in MongoDB
- process each user turn with Anthropic
- track per-message token usage
- trim active message history to a token budget
- merge dropped history into a rolling summary
- persist bounded session state and append raw message logs

The module is intentionally script-style (top-level execution) to keep the
reference implementation simple and easy to run from the terminal.
"""

from datetime import datetime, UTC
from uuid import uuid4
import warnings
from pymongo import MongoClient
import anthropic

from utils import (
    build_request_system_prompt,
    load_session_id,
    load_system_prompt,
    save_session_id,
    get_connection_string,
    get_collection,
    SESSIONS_COLLECTION_NAME,
    LOGS_COLLECTION_NAME,
    upsert_responses,
    insert_session_log,
    get_token_count,
    MAX_SESSION_MESSAGE_TOKENS,
    get_trimmed_messages_and_dropped_messages,
    merge_summary,
)

# Suppress all UserWarnings
warnings.filterwarnings("ignore", category=UserWarning)

system_prompt = load_system_prompt()

mongo_client = MongoClient(get_connection_string())
sessions_collection = get_collection(mongo_client, SESSIONS_COLLECTION_NAME)
logs_collection = get_collection(mongo_client, LOGS_COLLECTION_NAME)

client = anthropic.Anthropic()

session_id = load_session_id()
if not session_id:
    session_id = str(uuid4())

# Check if session already exists in DB and load it, otherwise create new
existing_session = sessions_collection.find_one({"session_id": session_id})
if existing_session:
    # Load existing session
    session_doc = existing_session
    print(f"Loaded existing session: {session_id}")
else:
    # Create new session
    session_id = str(uuid4())
    session_doc = {
        "session_id": session_id,
        "created_at": datetime.now(UTC),
        "last_active": datetime.now(UTC),
        "summary": "",
        "summary_updated_at": None,
        "messages": [],
    }
    print(f"Created new session: {session_id}")

save_session_id(session_id)

while True:
    # End the interactive loop when the operator types "quit".
    user_input = input("User: ")
    if user_input == "quit":
        break

    request_system_prompt = build_request_system_prompt(system_prompt, session_doc["summary"])

    user_message = {
        "role": "user",
        "content": user_input,
        "timestamp": datetime.now(UTC),
        "token_count": get_token_count(
            client,
            request_system_prompt,
            [{"role": m["role"], "content": m["content"]} for m in session_doc["messages"]],
            {"role": "user", "content": user_input},
        ),
    }

    history = [{"role": m["role"], "content": m["content"]} for m in session_doc["messages"]]
    history.append({"role": "user", "content": user_input})

    message = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1000,
        system=request_system_prompt,
        messages=history,
    )

    response_text = message.content[0].text
    print(f"Assistant: {response_text}")

    assistant_message = {
        "role": "assistant",
        "content": response_text,
        "timestamp": datetime.now(UTC),
        "token_count": get_token_count(
            client,
            request_system_prompt,
            history,
            {"role": "assistant", "content": response_text},
        ),
    }

    # update session doc in memory and persist
    session_doc["messages"].append(user_message)
    session_doc["messages"].append(assistant_message)

    trimmed_messages, dropped_messages = get_trimmed_messages_and_dropped_messages(
        session_doc["messages"],
        MAX_SESSION_MESSAGE_TOKENS,
    )

    if dropped_messages:
        updated_summary = merge_summary(client, session_doc["summary"], dropped_messages)
        session_doc["summary"] = updated_summary
        session_doc["summary_updated_at"] = datetime.now(UTC)

    session_doc["messages"] = trimmed_messages

    session_doc["last_active"] = datetime.now(UTC)
    upsert_responses(sessions_collection, session_doc)

    # append raw messages to logs
    insert_session_log(logs_collection, session_id, user_message)
    insert_session_log(logs_collection, session_id, assistant_message)


