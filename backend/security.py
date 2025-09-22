--- a/backend/security.py
+++ b/backend/security.py
@@
-from .db import engine
+from .db import get_engine
@@
 def verify_user(email: str, password: str) -> bool:
-    with engine.begin() as conn:
+    with get_engine().begin() as conn:
         row = conn.execute(text("SELECT password_hash FROM users WHERE email=:e"), {"e": email}).first()
         if not row:
             return False
         ph = row[0].encode()
     return bcrypt.checkpw(password.encode(), ph)
