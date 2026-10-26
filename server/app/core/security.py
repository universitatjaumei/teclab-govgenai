import bcrypt


def hash_password(password: str) -> str:
    """
    Hashea una contraseña usando bcrypt.
    """
    # bcrypt.hashpw espera bytes
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(pwd_bytes, salt)
    return hashed.decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """
    Verifica una contraseña contra un hash de bcrypt.
    """
    pwd_bytes = password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    try:
        return bcrypt.checkpw(pwd_bytes, hashed_bytes)
    except ValueError:
        # Un hash que no es de bcrypt («Invalid salt»): esa contraseña no coincide con nada.
        return False
