import uuid
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.business import Business
from app.models.menu_item import MenuItem
from app.models.scan_session import ScanSession
from app.models.recommendation_item import RecommendationItem


def seed_db(db: Session) -> None:
    """Seed the database with sample data."""
    
    # Clear existing data (optional - comment out if you want to preserve data)
    db.query(RecommendationItem).delete()
    db.query(ScanSession).delete()
    db.query(MenuItem).delete()
    db.query(Business).delete()
    db.query(User).delete()
    db.commit()
    
    # Create Users (external_auth_uid required; 1:1 with Supabase auth)
    user1 = User(
        id=uuid.uuid4(),
        external_auth_uid="11111111-1111-1111-1111-111111111111",
        auth_provider_id="supabase_user_1",
        email="alice@example.com",
    )
    user2 = User(
        id=uuid.uuid4(),
        external_auth_uid="22222222-2222-2222-2222-222222222222",
        auth_provider_id="supabase_user_2",
        email="bob@example.com",
    )
    db.add(user1)
    db.add(user2)
    db.commit()
    db.refresh(user1)
    db.refresh(user2)
    
    # Create Businesses
    business1 = Business(
        id=uuid.uuid4(),
        name="Tony's Pizza",
        external_id_yelp="tonys-pizza-nyc",
        external_id_google="ChIJ123456789",
        address_full="123 Main St, New York, NY 10001",
        lat=40.7128,
        lng=-74.0060,
        category="restaurant"
    )
    business2 = Business(
        id=uuid.uuid4(),
        name="Elite Hair Salon",
        external_id_yelp="elite-hair-salon",
        external_id_google="ChIJ987654321",
        address_full="456 Broadway, New York, NY 10013",
        lat=40.7209,
        lng=-74.0007,
        category="salon"
    )
    db.add(business1)
    db.add(business2)
    db.commit()
    db.refresh(business1)
    db.refresh(business2)
    
    # Create Menu Items for Business 1 (Pizza)
    menu_item1 = MenuItem(
        id=uuid.uuid4(),
        business_id=business1.id,
        name="Pepperoni Pizza",
        item_type="FOOD",
        total_mentions=45,
        positive_mentions=38,
        negative_mentions=7,
        avg_rating=4.5,
        top_positive_snippet="Best pepperoni pizza in the city!",
        top_negative_snippet="Too greasy for my taste"
    )
    menu_item2 = MenuItem(
        id=uuid.uuid4(),
        business_id=business1.id,
        name="Margherita Pizza",
        item_type="FOOD",
        total_mentions=32,
        positive_mentions=28,
        negative_mentions=4,
        avg_rating=4.3,
        top_positive_snippet="Fresh mozzarella and basil",
        top_negative_snippet="Could use more cheese"
    )
    menu_item3 = MenuItem(
        id=uuid.uuid4(),
        business_id=business1.id,
        name="Coca Cola",
        item_type="DRINK",
        total_mentions=15,
        positive_mentions=12,
        negative_mentions=3,
        avg_rating=3.8,
        top_positive_snippet="Always cold and refreshing",
        top_negative_snippet="Pricey for a soda"
    )
    
    # Create Menu Items for Business 2 (Salon)
    menu_item4 = MenuItem(
        id=uuid.uuid4(),
        business_id=business2.id,
        name="Sarah (Stylist)",
        item_type="PERSON",
        total_mentions=28,
        positive_mentions=25,
        negative_mentions=3,
        avg_rating=4.7,
        top_positive_snippet="Sarah is amazing! She really listens to what you want",
        top_negative_snippet="Sometimes runs a bit late"
    )
    menu_item5 = MenuItem(
        id=uuid.uuid4(),
        business_id=business2.id,
        name="Haircut",
        item_type="SERVICE",
        total_mentions=52,
        positive_mentions=45,
        negative_mentions=7,
        avg_rating=4.4,
        top_positive_snippet="Great cuts, very professional",
        top_negative_snippet="Wait time can be long"
    )
    menu_item6 = MenuItem(
        id=uuid.uuid4(),
        business_id=business2.id,
        name="Hair Color",
        item_type="SERVICE",
        total_mentions=18,
        positive_mentions=15,
        negative_mentions=3,
        avg_rating=4.2,
        top_positive_snippet="Beautiful color work",
        top_negative_snippet="Expensive but worth it"
    )
    
    db.add(menu_item1)
    db.add(menu_item2)
    db.add(menu_item3)
    db.add(menu_item4)
    db.add(menu_item5)
    db.add(menu_item6)
    db.commit()
    db.refresh(menu_item1)
    db.refresh(menu_item2)
    db.refresh(menu_item3)
    db.refresh(menu_item4)
    db.refresh(menu_item5)
    db.refresh(menu_item6)
    
    # Create Scan Sessions
    scan1 = ScanSession(
        id=uuid.uuid4(),
        user_id=user1.id,
        business_id=business1.id,
        image_url="https://example.com/images/scan1.jpg",
        detected_text_raw="TONY'S PIZZA\nPepperoni Pizza $18\nMargherita Pizza $16\nCoca Cola $3",
        status="COMPLETED",
        completed_at=None  # Could set to a datetime if needed
    )
    scan2 = ScanSession(
        id=uuid.uuid4(),
        user_id=user1.id,
        business_id=business2.id,
        image_url="https://example.com/images/scan2.jpg",
        detected_text_raw="ELITE HAIR SALON\nSarah - Senior Stylist\nHaircut $50\nHair Color $120",
        status="COMPLETED"
    )
    scan3 = ScanSession(
        id=uuid.uuid4(),
        user_id=user2.id,
        business_id=business1.id,
        image_url="https://example.com/images/scan3.jpg",
        detected_text_raw="TONY'S PIZZA\nPepperoni Pizza $18\nMargherita Pizza $16",
        status="PROCESSING"
    )
    
    db.add(scan1)
    db.add(scan2)
    db.add(scan3)
    db.commit()
    db.refresh(scan1)
    db.refresh(scan2)
    db.refresh(scan3)
    
    # Create Recommendation Items for Scan 1
    rec1 = RecommendationItem(
        id=uuid.uuid4(),
        scan_session_id=scan1.id,
        menu_item_id=menu_item1.id,
        rank=1,
        is_recommended=True,
        recommendation_label="HIGHLY_RECOMMENDED",
        display_mention_count=45,
        display_avg_rating=4.5,
        display_positive_snippet="Best pepperoni pizza in the city!",
        display_negative_snippet="Too greasy for my taste"
    )
    rec2 = RecommendationItem(
        id=uuid.uuid4(),
        scan_session_id=scan1.id,
        menu_item_id=menu_item2.id,
        rank=2,
        is_recommended=True,
        recommendation_label="RECOMMENDED",
        display_mention_count=32,
        display_avg_rating=4.3,
        display_positive_snippet="Fresh mozzarella and basil",
        display_negative_snippet="Could use more cheese"
    )
    rec3 = RecommendationItem(
        id=uuid.uuid4(),
        scan_session_id=scan1.id,
        menu_item_id=menu_item3.id,
        rank=3,
        is_recommended=False,
        recommendation_label="NOT_RECOMMENDED",
        display_mention_count=15,
        display_avg_rating=3.8,
        display_positive_snippet="Always cold and refreshing",
        display_negative_snippet="Pricey for a soda"
    )
    
    # Create Recommendation Items for Scan 2
    rec4 = RecommendationItem(
        id=uuid.uuid4(),
        scan_session_id=scan2.id,
        menu_item_id=menu_item4.id,
        rank=1,
        is_recommended=True,
        recommendation_label="HIGHLY_RECOMMENDED",
        display_mention_count=28,
        display_avg_rating=4.7,
        display_positive_snippet="Sarah is amazing! She really listens to what you want",
        display_negative_snippet="Sometimes runs a bit late"
    )
    rec5 = RecommendationItem(
        id=uuid.uuid4(),
        scan_session_id=scan2.id,
        menu_item_id=menu_item5.id,
        rank=2,
        is_recommended=True,
        recommendation_label="RECOMMENDED",
        display_mention_count=52,
        display_avg_rating=4.4,
        display_positive_snippet="Great cuts, very professional",
        display_negative_snippet="Wait time can be long"
    )
    
    db.add(rec1)
    db.add(rec2)
    db.add(rec3)
    db.add(rec4)
    db.add(rec5)
    db.commit()
    
    print("Database seeded successfully!")
    print(f"Created: 2 users, 2 businesses, 6 menu items, 3 scan sessions, 5 recommendation items")

