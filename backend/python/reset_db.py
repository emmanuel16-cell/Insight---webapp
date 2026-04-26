#!/usr/bin/env python3
"""
Reset the development database by dropping and recreating the database
named in the project's .env (DB_NAME). Use only for development.
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

if not all([DB_HOST, DB_USER, DB_PASS, DB_NAME]):
    print("Missing DB environment variables in .env. Aborting.")
    sys.exit(1)

try:
    import mysql.connector
except Exception as e:
    print("mysql.connector not available:", e)
    sys.exit(1)

try:
    conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASS)
    conn.autocommit = True
    cur = conn.cursor()
    print(f"Dropping database `{DB_NAME}` if it exists...")
    cur.execute(f"DROP DATABASE IF EXISTS `{DB_NAME}`")
    print(f"Creating database `{DB_NAME}`...")
    cur.execute(f"CREATE DATABASE `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    print("Database reset complete.")
    cur.close()
    conn.close()
    sys.exit(0)
except Exception as e:
    print("Error resetting database:", e)
    sys.exit(2)
