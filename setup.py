"""Database setup script for creating MongoDB indexes used by the agent.

Run this module once per environment to create indexes that support fast
session lookup and ordered log retrieval.
"""

from pymongo import ASCENDING, MongoClient

from utils import (
    SESSIONS_COLLECTION_NAME,
    LOGS_COLLECTION_NAME,
    get_collection,
    get_connection_string,
)

def create_sessions_indexes(collection):
    """Create indexes for session lookup and recency queries."""
    collection.create_index([("session_id", ASCENDING)])
    collection.create_index([("last_active", ASCENDING)])
    print("Indexes created on sessions: session_id, last_active")

def create_logs_indexes(collection):
    """Create compound index for per-session chronological log retrieval."""
    collection.create_index([("session_id", ASCENDING), ("timestamp", ASCENDING)])
    print("Compound index created on logs: session_id, timestamp")

def main():
    """Connect to MongoDB and create required indexes for both collections."""
    connection_string = get_connection_string()
    client = MongoClient(connection_string)
    try:
        print("Creating indexes...")
        sessions_collection = get_collection(client, SESSIONS_COLLECTION_NAME)
        create_sessions_indexes(sessions_collection)

        logs_collection = get_collection(client, LOGS_COLLECTION_NAME)
        create_logs_indexes(logs_collection)
        print("Setup complete.")
    finally:
        client.close()

if __name__ == "__main__":
    main()