from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from passlib.context import CryptContext
import uuid

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


users_db = {}


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8)
    business_name: str = Field(..., min_length=2, max_length=200)
    phone: Optional[str] = None


@app.post("/api/auth/signup")
def signup(user: UserCreate):
    if user.email in users_db:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = pwd_context.hash(user.password)

    user_id = str(uuid.uuid4())

    users_db[user.email] = {
        "id": user_id,
        "email": user.email,
        "full_name": user.full_name,
        "business_name": user.business_name,
        "phone": user.phone,
        "password": hashed_password
    }

    access_token = str(uuid.uuid4())
    refresh_token = str(uuid.uuid4())

    return {
        "success": True,
        "data": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user_name": user.full_name,
            "business_name": user.business_name
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("simple_main:app", host="127.0.0.1", port=8001, reload=True)
