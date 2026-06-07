from pymongo import MongoClient
import os
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

_client = None
_db = None

def connect_db():
    """Initialize the MongoDB connection once at app startup."""
    global _client, _db
    uri = os.getenv('MONGO_URI', 'mongodb://localhost:27017/gavran_magic')
    _client = MongoClient(
        uri,
        serverSelectionTimeoutMS=30000,
        connectTimeoutMS=30000,
        socketTimeoutMS=30000
    )
    # Extract DB name from URI (e.g. /gavran_magic?...) or default
    try:
        path_part = uri.split('/')[-1].split('?')[0].strip()
        db_name = path_part if path_part else 'gavran_magic'
    except Exception:
        db_name = 'gavran_magic'
    _db = _client[db_name]
    print(f"[DB] Connected to MongoDB database: '{db_name}'")

def get_db():
    """Return the database instance."""
    if _db is None:
        connect_db()
    return _db

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
