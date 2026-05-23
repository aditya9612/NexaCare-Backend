import uvicorn

from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        # Only watch app code — not venv (pip/OneDrive changes cause endless reloads)
        reload_dirs=["app"] if settings.DEBUG else None,
        reload_excludes=["venv", ".venv", "__pycache__", "*.pyc"] if settings.DEBUG else None,
    )
