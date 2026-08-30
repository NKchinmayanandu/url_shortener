from fastapi import FastApi
from app.services.url_service import shorten_url
app = FastApi()

@app.post("/shorten")
async def shorten(url:str):
    return shorten_url(url=url)


@app.get("/{short_code}")
async def redirect(short_code: str):
    return {"short_code": short_code}