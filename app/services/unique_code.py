import secrets
import string

def generate_unique_code(length=5, unique_codes=None):
    if unique_codes is None:
        unique_codes = set()
    
    alphabet = string.ascii_letters + string.digits
    
    while True:
        code = ''.join(secrets.choice(alphabet) for _ in range(length))
        if code not in unique_codes:
            unique_codes.add(code)
            return code