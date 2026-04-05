import psycopg2
import os
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from dotenv import load_dotenv

# Load credentials from your .env file
load_dotenv()

db_user = os.getenv("DB_USER", "postgres")
db_password = 
db_host = os.getenv("DB_HOST", "localhost")

# 1. Connect to default postgres DB to create the new one
try:
    conn = psycopg2.connect(dbname='postgres', user=db_user, password=db_password, host=db_host)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute('CREATE DATABASE pharmacy_saas_db;')
    print("Database pharmacy_saas_db created successfully!")
    cur.close()
    conn.close()
except Exception as e:
    print(f"Note: {e}") # It will say it already exists, which is fine!

# 2. Connect to the NEW database and run the schema file
try:
    conn = psycopg2.connect(dbname='pharmacy_saas_db', user=db_user, password=db_password, host=db_host)
    cur = conn.cursor()
    
    with open('schema.sql', 'r') as file:
        schema_sql = file.read()
        
    cur.execute(schema_sql)
    conn.commit()
    print("schema.sql executed successfully! Tables are ready.")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"Error running schema: {e}")