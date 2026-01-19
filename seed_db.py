"""
Script to seed the database with sample data.
Run with: python seed_db.py
"""
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, init_db
from app.seed.seed_data import seed_db

# Load environment variables
load_dotenv()


def main():
    """Main function to seed the database."""
    print("Initializing database...")
    init_db()
    
    print("Seeding database...")
    db: Session = SessionLocal()
    try:
        seed_db(db)
    finally:
        db.close()
    print("Done!")


if __name__ == "__main__":
    main()

