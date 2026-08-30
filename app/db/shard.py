from app.db.session import session_makers
import hashlib
def get_shard(short_code: str):
    hashed_code = hash_short_code(short_code=short_code)
    return hashed_code % 3



def hash_short_code(short_code: str):
    return int.from_bytes(
    hashlib.sha256(short_code.encode()).digest(),
    byteorder="big",)