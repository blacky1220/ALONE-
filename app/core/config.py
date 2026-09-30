from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Sistema para Condominios SaaS"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "sb_secret_ydYZZuOnPtBFN2nRnCzkKw_IYSApxt3" 
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # URL de conexión a PostgreSQL en Supabase sin parámetros extra de pgbouncer
    DATABASE_URL: str = "postgresql://postgres.pihvuykvvehuvvzkxtjc:rafaelysarah1220@aws-0-us-east-2.pooler.supabase.com:6543/postgres"
    DIRECT_URL: str = "postgresql://postgres.pihvuykvvehuvvzkxtjc:rafaelysarah1220@aws-0-us-east-2.pooler.supabase.com:5432/postgres"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()