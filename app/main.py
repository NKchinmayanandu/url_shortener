from fastapi import FastApi

app = FastApi()

@app.post("/shorten")
async def shorten():
    return {"message": "shorten endpoint"}


@app.get("/{short_code}")
async def redirect(short_code: str):
    return {"short_code": short_code}