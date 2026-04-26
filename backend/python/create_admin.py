# run once from project root
from dotenv import load_dotenv
load_dotenv()

from auth import get_db, encrypt_password


db  = get_db()
cur = db.cursor()
enc = encrypt_password("YourAdminPassword123!")
cur.execute(
    "INSERT INTO users (email, password_hash, role, is_verified) VALUES (%s,%s,'admin',1)",
    ("emmanuelnabus407@gmail.com", enc)
)
cur.execute(
    "INSERT INTO user_profiles (user_id, first_name, last_name) "
    "VALUES (LAST_INSERT_ID(), 'Admin', 'User')"
)
db.commit()
print("Admin created")