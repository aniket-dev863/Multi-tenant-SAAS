import os
import psycopg2
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_connections():
    print("--- TESTING DATABASES ---")

    # 1. Test PostgreSQL Connection
    try:
        pg_conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "pharmacy_db"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD"),
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432")
        )
        pg_cur = pg_conn.cursor()
        # Just check if we can query the empty users table
        pg_cur.execute("SELECT count(*) FROM users;")
        count = pg_cur.fetchone()[0]
        print(f"✅ PostgreSQL Connected! Users found: {count}")
        pg_cur.close()
        pg_conn.close()
    except Exception as e:
        print(f"❌ PostgreSQL Error: {e}")

    # 2. Test MongoDB Connection
    try:
        mongo_client = MongoClient(os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/medicinedb"))
        mongo_db = mongo_client.get_database()
        # Insert a dummy document to force creation if it doesn't exist
        test_id = mongo_db.test_collection.insert_one({"status": "working"}).inserted_id
        print(f"✅ MongoDB Connected! Test document inserted with ID: {test_id}")
        # Clean up the test document
        mongo_db.test_collection.delete_one({"_id": test_id})
        print("✅ MongoDB test document cleaned up.")
    except Exception as e:
        print(f"❌ MongoDB Error: {e}")

    print("-------------------------")

if __name__ == "__main__":
    test_connections()