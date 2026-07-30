#!/usr/bin/env python3
"""
Production server runner: Serves static React app + FastAPI backend
"""
import os
import sys
from pathlib import Path

# Add server directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app import app
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Serve static files from React build
dist_path = Path(__file__).parent.parent / "dist"

if dist_path.exists():
    # Mount static files with index fallback for React Router
    app.mount("/", StaticFiles(directory=str(dist_path), html=True), name="static")
else:
    @app.get("/{full_path:path}")
    async def fallback(full_path: str):
        """Fallback for development when dist doesn't exist"""
        return {
            "message": "React app not built yet. Run 'npm run build' first.",
            "path": full_path,
        }

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    
    print(f"🚀 Starting server at {host}:{port}")
    print(f"📦 Serving React app from: {dist_path}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
