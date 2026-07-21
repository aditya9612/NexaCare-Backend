import uvicorn

from app.core.config import settings

if __name__ == "__main__":
    print("Starting NexaCare API — open http://localhost:8000/docs in your browser")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        # Only watch app code — not venv (pip/OneDrive changes cause endless reloads)
        reload_dirs=["app"] if settings.DEBUG else None,
        reload_excludes=["venv", ".venv", "__pycache__", "*.pyc", ".env"] if settings.DEBUG else None,
    )
