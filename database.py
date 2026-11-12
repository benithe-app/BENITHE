import os
import psycopg2

def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "benithe"),
        user=os.getenv("DB_USER", "mac"),
        host=os.getenv("DB_HOST", "/tmp"),
        port=os.getenv("DB_PORT", "5432")
    )
