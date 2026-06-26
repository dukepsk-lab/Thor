import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Thor ML Trading System"
    ENVIRONMENT: str = "development"
    
    # TimescaleDB Settings
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "5432"))
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "postgres")
    DB_NAME: str = os.getenv("DB_NAME", "thor_db")
    
    # MT5 Settings
    MT5_PATH: str = os.getenv("MT5_PATH", "C:/Program Files/MetaTrader 5/terminal64.exe")
    MT5_LOGIN: int = int(os.getenv("MT5_LOGIN", "0"))
    MT5_PASSWORD: str = os.getenv("MT5_PASSWORD", "")
    MT5_SERVER: str = os.getenv("MT5_SERVER", "")

    class Config:
        env_file = ".env"

settings = Settings()
