from fastapi import FastAPI

from app.core.config import settings
from app.routers import users, businesses, menu_items, scan_sessions, recommendation_items, me, places, home, ai, chat

app = FastAPI(
    title=settings.project_name,
    version="1.0.0",
)

# Include routers
app.include_router(users.router, prefix=settings.api_v1_prefix)
app.include_router(businesses.router, prefix=settings.api_v1_prefix)
app.include_router(menu_items.router, prefix=settings.api_v1_prefix)
app.include_router(scan_sessions.router, prefix=settings.api_v1_prefix)
app.include_router(recommendation_items.router, prefix=settings.api_v1_prefix)
app.include_router(me.router, prefix=settings.api_v1_prefix)
app.include_router(places.router, prefix=settings.api_v1_prefix)
app.include_router(home.router, prefix=settings.api_v1_prefix)
app.include_router(ai.router, prefix=settings.api_v1_prefix)
app.include_router(chat.router, prefix=settings.api_v1_prefix)


@app.get("/")
def root():
    """Root endpoint."""
    return {
        "message": "Welcome to PickRight API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

