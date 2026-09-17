from fastapi import FastApi
from app.services.url_service import shorten_url
from app.services.redirect_service import redirect_url
import os
app = FastApi()

@app.post("/shorten")
async def shorten(url:str):
    return shorten_url(url=url)


@app.get("/{short_code}")
async def redirect(short_code: str):
    return redirect_url(short_code=short_code)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "instance": os.getenv("INSTANCE_ID")
    }