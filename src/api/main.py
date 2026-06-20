from fastapi import FastAPI
from src.core.config import settings

app = FastAPI(title=settings.APP_NAME)

@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.APP_NAME} API"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "environment": settings.ENVIRONMENT}

# TODO: Include routers for inference, execution, and monitoring
