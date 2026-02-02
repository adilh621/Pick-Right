# PickRight Backend API

A FastAPI backend for the PickRight mobile app, built with SQLAlchemy 2.0, PostgreSQL, and Pydantic v2.

## Features

- **FastAPI** with async support
- **SQLAlchemy 2.0** with declarative models
- **PostgreSQL** database
- **Pydantic v2** for request/response validation
- **Alembic** ready for migrations
- Comprehensive CRUD APIs for all entities
- Database seeding for local development
- Test fixtures and basic test structure

## Project Structure

```
pickright-backend/
├── app/
│   ├── core/
│   │   └── config.py          # Application settings
│   ├── db/
│   │   ├── base.py            # SQLAlchemy Base
│   │   └── session.py         # Database session management
│   ├── models/                 # SQLAlchemy models
│   │   ├── user.py
│   │   ├── business.py
│   │   ├── menu_item.py
│   │   ├── scan_session.py
│   │   └── recommendation_item.py
│   ├── schemas/                # Pydantic schemas
│   │   ├── user.py
│   │   ├── business.py
│   │   ├── menu_item.py
│   │   ├── scan_session.py
│   │   └── recommendation_item.py
│   ├── routers/                # FastAPI routers
│   │   ├── users.py
│   │   ├── businesses.py
│   │   ├── menu_items.py
│   │   ├── scan_sessions.py
│   │   └── recommendation_items.py
│   ├── seed/
│   │   └── seed_data.py        # Database seeding logic
│   └── main.py                 # FastAPI application
├── tests/
│   ├── conftest.py            # Pytest fixtures
│   ├── test_users.py
│   └── test_businesses.py
├── requirements.txt
├── seed_db.py                 # Script to run seeding
└── README.md
```

```
User ──> (user_id) ──> ScanSession ──> (business_id)──> Business
                                         │
                                         └─> RecommendationItem(s) ──> MenuItem(s)
```

## Setup

### 1. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and set the required environment variables:

```env
# Database configuration (local PostgreSQL)
DATABASE_URL=postgresql://user:password@localhost:5432/pickright_dev

# Supabase authentication configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_JWT_AUDIENCE=authenticated
```

**Note**: `SUPABASE_JWKS_URL` and `SUPABASE_ISSUER` are automatically derived from `SUPABASE_URL` as:
- `SUPABASE_JWKS_URL`: `${SUPABASE_URL}/auth/v1/.well-known/jwks.json`
- `SUPABASE_ISSUER`: `${SUPABASE_URL}/auth/v1`

#### Setting Up Supabase

1. **Create a Supabase Project:**
   - Go to [https://supabase.com](https://supabase.com)
   - Sign up or log in
   - Click "New Project"
   - Fill in project details (name, database password, region)
   - Wait for the project to be created (usually takes 1-2 minutes)

2. **Get Your Supabase URL:**
   - In your Supabase project dashboard, go to **Settings** → **API**
   - Copy the **Project URL** (e.g., `https://xxxxxxxxxxxxx.supabase.co`)
   - This is your `SUPABASE_URL`

3. **Configure Authentication:**
   - Go to **Authentication** → **Providers** in your Supabase dashboard
   - Enable the authentication providers you want to use (Email, OAuth, etc.)
   - The JWT audience is typically `"authenticated"` (default)

4. **Get Access Tokens for Testing:**
   - Use the Supabase client libraries in your frontend/mobile app to sign in users
   - Access tokens will be automatically included in API requests
   - For manual testing, you can get tokens from your app's authentication flow

### 4. Create Database

Make sure PostgreSQL is running and create the database:

```bash
createdb pickright_dev
# Or using psql:
# psql -U postgres
# CREATE DATABASE pickright_dev;
```

### 5. Initialize Database Tables

The application will create tables automatically on first run, or you can use:

```python
from app.db.session import init_db
init_db()
```

Or run the seed script which also initializes tables:

```bash
python seed_db.py
```

### 6. Seed Database (Optional)

To populate the database with sample data:

```bash
python seed_db.py
```

This will create:
- 2 sample users
- 2 sample businesses (a pizza restaurant and a hair salon)
- 6 menu items
- 3 scan sessions
- 5 recommendation items

### 7. Run the Application

```bash
uvicorn app.main:app --reload
```

The API will be available at:
- **API**: http://localhost:8000
- **Interactive Docs**: http://localhost:8000/docs
- **Alternative Docs**: http://localhost:8000/redoc

## Authentication

The API uses **Supabase JWT authentication** with Bearer tokens. All protected endpoints require a valid Supabase access token in the Authorization header.

### How It Works

1. **Token Verification**: The API verifies JWT tokens using Supabase's JWKS (JSON Web Key Set)
   - JWKS is fetched from `${SUPABASE_URL}/auth/v1/.well-known/jwks.json`
   - Tokens are cached in-memory with a 10-minute TTL for performance
   - Token signature, issuer, audience, and expiration are all validated

2. **User Lookup/Creation**: 
   - On successful token verification, the system extracts the user ID (`sub` claim) and email
   - The user is looked up in the local PostgreSQL database by `external_auth_uid`
   - If not found, a new user is automatically created with the extracted information
   - Provider information is extracted from token claims (defaults to "supabase")

3. **Error Handling**:
   - Missing token → `401 Unauthorized`
   - Invalid/expired token → `401 Unauthorized` with error details
   - Wrong issuer/audience → `401 Unauthorized`

### Using Authentication

Include the Supabase access token in the Authorization header:

```bash
curl -H "Authorization: Bearer YOUR_SUPABASE_ACCESS_TOKEN" http://localhost:8000/api/v1/me
```

**Note**: Access tokens are obtained from your Supabase-authenticated client (web/mobile app). For testing, you can get tokens from your app's authentication flow or use Supabase's authentication API directly.

### Google OAuth Authentication

The backend supports Google OAuth via Supabase. When a user authenticates with Google through Supabase, the JWT token will contain:
- `sub`: User ID (UUID string)
- `email`: User's email address
- `app_metadata.provider`: "google"

The backend automatically:
1. Verifies the Supabase JWT token (signature, issuer, audience, expiration)
2. Extracts the provider from `app_metadata.provider` (defaults to "email" if not present)
3. Creates a local user record if it doesn't exist (using `external_auth_uid` = `sub`)
4. Updates the user's email if available

**Example with Google OAuth token:**

```bash
# Get your profile (creates user if first time)
curl -H "Authorization: Bearer YOUR_GOOGLE_OAUTH_SUPABASE_TOKEN" \
     http://localhost:8000/api/v1/me

# Update onboarding preferences
curl -X PUT \
  -H "Authorization: Bearer YOUR_GOOGLE_OAUTH_SUPABASE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "onboarding_preferences": {
      "dietary_restrictions": ["vegetarian"],
      "preferred_cuisines": ["italian", "mexican"]
    }
  }' \
  http://localhost:8000/api/v1/me/preferences
```

**Getting a Google OAuth token for testing:**

1. In your iOS app, use Supabase Auth to sign in with Google
2. Extract the `access_token` from the session
3. Use that token in the `Authorization: Bearer <token>` header

## API Endpoints

### Authentication & User Profile (`/me`)

- `GET /api/v1/me` - Get authenticated user's profile (requires Bearer token)
- `PUT /api/v1/me/preferences` - Update user's onboarding preferences (requires Bearer token)
- `POST /api/v1/me/upgrade-guest` - Migrate guest scan sessions to authenticated user (requires Bearer token)

#### Examples

**Get user profile:**
```bash
curl -H "Authorization: Bearer YOUR_SUPABASE_ACCESS_TOKEN" http://localhost:8000/api/v1/me
```

**Update preferences (nested format):**
```bash
curl -X PUT \
  -H "Authorization: Bearer YOUR_SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "onboarding_preferences": {
      "dietary_restrictions": ["vegetarian"],
      "allergies": ["peanuts"],
      "preferred_cuisines": ["italian"]
    },
    "onboarding_completed_at": "2024-01-15T10:30:00Z"
  }' \
  http://localhost:8000/api/v1/me/preferences
```

**Update preferences (flattened format for backward compatibility):**
```bash
curl -X PUT \
  -H "Authorization: Bearer YOUR_SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "place_interests": ["restaurants", "cafes"],
    "intent_selections": ["dining", "takeout"],
    "dietary_restrictions": ["vegetarian"]
  }' \
  http://localhost:8000/api/v1/me/preferences
```

**Update preferences (onboarding_completed_at omitted - will be set to now):**
```bash
curl -X PUT \
  -H "Authorization: Bearer YOUR_SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "onboarding_preferences": {
      "dietary_restrictions": ["vegetarian"],
      "preferred_cuisines": ["italian"]
    }
  }' \
  http://localhost:8000/api/v1/me/preferences
```

**Partial update (only onboarding_preferences, onboarding_completed_at unchanged):**
```bash
curl -X PUT \
  -H "Authorization: Bearer YOUR_SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "onboarding_preferences": {
      "dietary_restrictions": ["vegan"]
    }
  }' \
  http://localhost:8000/api/v1/me/preferences
```

**Note**: Both `onboarding_preferences` and `onboarding_completed_at` are optional for partial updates. However, if `onboarding_completed_at` is provided, `onboarding_preferences` must also be provided.

**Upgrade guest sessions:**
```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_SUPABASE_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "device-uuid-here"}' \
  http://localhost:8000/api/v1/me/upgrade-guest
```

### Testing Authentication

To test authentication with a real Supabase token:

1. **Get a test token from your Supabase project:**
   - Use the Supabase client library in your app to sign in a user
   - Extract the access token from the session
   - Or use Supabase's REST API to sign in and get a token

2. **Test with curl:**
   ```bash
   # Replace YOUR_SUPABASE_ACCESS_TOKEN with an actual token
   curl -H "Authorization: Bearer YOUR_SUPABASE_ACCESS_TOKEN" \
        http://localhost:8000/api/v1/me
   ```

3. **Expected responses:**
   - Valid token: `200 OK` with user data
   - Invalid/missing token: `401 Unauthorized`
   - Expired token: `401 Unauthorized` with error message

### Users
- `POST /api/v1/users` - Create user
- `GET /api/v1/users/{user_id}` - Get user by ID

### Businesses
- `POST /api/v1/businesses` - Create business
- `GET /api/v1/businesses` - List businesses (with optional `name` query parameter)
- `GET /api/v1/businesses/{business_id}` - Get business by ID

### Menu Items
- `POST /api/v1/businesses/{business_id}/menu-items` - Create menu item
- `GET /api/v1/businesses/{business_id}/menu-items` - List menu items for a business
- `GET /api/v1/menu-items/{menu_item_id}` - Get menu item by ID

### Scan Sessions
- `POST /api/v1/scan-sessions` - Create scan session (requires either `user_id` or `device_id`)
- `GET /api/v1/scan-sessions/{scan_session_id}` - Get scan session with recommendations
- `GET /api/v1/users/{user_id}/scan-sessions` - List scan sessions for a user

**Note**: Scan sessions can be created for authenticated users (`user_id`) or guest users (`device_id`). Guest sessions can later be migrated to a user account using the `/me/upgrade-guest` endpoint.

### Recommendation Items
- `POST /api/v1/scan-sessions/{scan_session_id}/recommendations` - Create recommendation items (bulk)
- `GET /api/v1/scan-sessions/{scan_session_id}/recommendations` - Get recommendations for a scan session

### Places (Discover / nearby businesses)

- **`GET /api/v1/places/nearby`** – Nearby places for the **Discover/home feed** (requires Bearer token and completed onboarding).
  - **Query params:** `lat` (required), `lng` (required), optional `radius` (meters), `type` (e.g. `restaurant`).
  - **Location is generic:** The endpoint accepts **any valid coordinates** (lat in [-90, 90], lng in [-180, 180]). It is not tied to a “user home location.”
  - **Change location:** When the user chooses a custom location (e.g. “Change location” in the iOS app), the client must call this endpoint with the **new** `lat` and `lng`. The server will return businesses near that point; no server-side geocoding is used.
  - **No geocoding on the backend:** Place name → coordinates (geocoding) must be done on the client (e.g. Apple APIs or another geocoding service). The backend expects already-derived coordinates.
- **`GET /api/v1/places/search`** – Text search for places. Optional `lat`/`lng` bias results near that location; same coordinate validation and client responsibility as above.
- **`GET /api/v1/places/details`** – Place details by Google Place ID (auth and onboarding required).

**AI chat and location:** For **`POST /api/v1/ai/chat`**, optional `latitude` and `longitude` in the request body are used to compute distance-to-business for answers like “how far is it?”. The iOS app should pass the **same active location** used for the Discover feed (device location or user-chosen “Change location” coordinates). Invalid coordinates (lat outside [-90, 90] or lng outside [-180, 180]) return 422.

### Chat (business-specific AI conversation)
- `POST /api/v1/chat/business/{business_id}` - Conversational chat about a specific business (requires Bearer token)
  - Request body: `user_message` (required), optional `chat_session_id` (for client use; history is by user + business)
  - Response: `assistant_message`, optional `chat_session_id`, `metadata` (e.g. `model`, `created_at`, `business_id`)
  - Context is built from the authenticated user's onboarding preferences, the business (name, category, address, `ai_context`, `ai_notes`), and conversation history from the DB. On quota/overload (429), returns 503 with `error: "model_overloaded"` and a friendly message.
  - **Uses a separate Gemini key:** this route uses `GEMINI_API_KEY2`; ai_context and ai_notes generation use `GEMINI_API_KEY`.

## Running Tests

```bash
pytest
```

Run with verbose output:

```bash
pytest -v
```

Run specific test file:

```bash
pytest tests/test_users.py
```

## Data Model

The application includes 5 main entities:

1. **User** - App users with auth provider integration
2. **Business** - Businesses (restaurants, salons, etc.)
3. **MenuItem** - Menu items, services, or people associated with businesses
4. **ScanSession** - OCR scan sessions from users
5. **RecommendationItem** - Recommendations generated from scan sessions

See the model files in `app/models/` for detailed field definitions and relationships.

#### Row-Level Security (RLS) on `businesses`

RLS is enabled on `public.businesses`. The migration `*_businesses_rls_policies` defines policies so that **authenticated** users (e.g. mobile app using the anon key with a signed-in user session) can:

- **SELECT** all rows
- **INSERT** new rows (e.g. Google Places upserts from the iOS app)
- **UPDATE** existing rows (e.g. refreshing rating, photo_url, price_level)

There is no owner/creator column on `businesses`; the current policies allow any authenticated user to insert and update. If you later add a creator column, you can tighten UPDATE (and optionally INSERT) to that column.

**Verification:** After applying the migration to your Supabase project, run the iOS app and confirm that upserts to `businesses` succeed and that fields such as `price_level`, `photo_url`, and `rating` persist.

## Development

### Database Migrations (Alembic)

To set up Alembic for migrations:

```bash
alembic init alembic
```

Then configure `alembic/env.py` to use your database URL and models.

#### Recent Model Changes (Requires Migration)

The following changes were made to the database schema and require a migration:

**User Model:**
- Added `external_auth_provider` (String, nullable)
- Added `external_auth_uid` (String, unique, nullable, indexed)
- Added `onboarding_preferences` (JSONB, nullable)
- Added `onboarding_completed_at` (DateTime with timezone, nullable)
- Added `updated_at` (DateTime with timezone, server_default=now(), onupdate=now())
- Made `auth_provider_id` and `email` nullable (for backward compatibility)

**ScanSession Model:**
- Added `device_id` (String, nullable, indexed)

**SQLAlchemy Migration (if Alembic not set up):**

```sql
-- Users table changes
ALTER TABLE users 
  ADD COLUMN external_auth_provider VARCHAR,
  ADD COLUMN external_auth_uid VARCHAR UNIQUE,
  ADD COLUMN onboarding_preferences JSONB,
  ADD COLUMN onboarding_completed_at TIMESTAMP WITH TIME ZONE,
  ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS ix_users_external_auth_uid ON users(external_auth_uid);

-- Make existing columns nullable (if needed)
ALTER TABLE users 
  ALTER COLUMN auth_provider_id DROP NOT NULL,
  ALTER COLUMN email DROP NOT NULL;

-- ScanSessions table changes
ALTER TABLE scan_sessions 
  ADD COLUMN device_id VARCHAR;

CREATE INDEX IF NOT EXISTS ix_scan_sessions_device_id ON scan_sessions(device_id);
```

### Code Style

The project follows PEP 8. Consider using:
- `black` for code formatting
- `flake8` or `ruff` for linting
- `mypy` for type checking

## Environment Variables

Required environment variables (set in `.env` file):

- `DATABASE_URL` - PostgreSQL connection string (required)
  - Example: `postgresql://user:password@localhost:5432/pickright_dev`

- `SUPABASE_URL` - Your Supabase project URL (required)
  - Example: `https://xxxxxxxxxxxxx.supabase.co`
  - Found in: Supabase Dashboard → Settings → API → Project URL

- `SUPABASE_JWT_AUDIENCE` - JWT audience claim (optional, default: `"authenticated"`)
  - Typically `"authenticated"` for Supabase access tokens

Optional Gemini AI environment variables:

- `GEMINI_API_KEY` - Used for ai_context and ai_notes generation (places details, business context). If unset, those features are skipped.
- `GEMINI_API_KEY2` - Used only for the conversational chat endpoint (`POST /api/v1/chat/business/{business_id}`). If unset, the chat endpoint will return 500.

Derived environment variables (automatically set from `SUPABASE_URL`):

- `SUPABASE_JWKS_URL` - JWKS endpoint URL
  - Automatically derived as: `${SUPABASE_URL}/auth/v1/.well-known/jwks.json`

- `SUPABASE_ISSUER` - JWT issuer claim
  - Automatically derived as: `${SUPABASE_URL}/auth/v1`

## License

[Your License Here]

