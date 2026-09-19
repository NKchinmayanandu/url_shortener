from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from app.services.url_service import shorten_url
from app.services.redirect_service import redirect_url
import os
app = FastAPI()

@app.post("/shorten")
async def shorten(url:str):
    return await shorten_url(url=url)

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "instance": os.getenv("INSTANCE_ID")
    }


@app.get("/{short_code}")
async def redirect(short_code: str):
    url = await redirect_url(short_code=short_code)
    return RedirectResponse(url=url)

