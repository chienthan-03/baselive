from src.db.database import Database

def get_db():
    db = Database()
    try:
        yield db
    finally:
        db.close()
