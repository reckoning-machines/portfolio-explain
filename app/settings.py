from pydantic import BaseSettings
from dotenv import load_dotenv

load_dotenv(".env")

class Settings(BaseSettings):
    DATABASE_URL: str

settings = Settings()
