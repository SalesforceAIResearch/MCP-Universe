"""
PASETO encoding and decoding.
"""
import os
import json
import datetime
import pyseto
from pyseto import Key
from dotenv import load_dotenv
from pydantic import BaseModel, field_serializer

load_dotenv()


class UserTokenPayload(BaseModel):
    """Payload for generating tokens."""
    id: str
    email: str
    permission: str
    issued_at: datetime.datetime
    expired_at: datetime.datetime

    @field_serializer("issued_at")
    def serialize_issued_at(self, issued_at: datetime, _info):
        """Customized serialization for `issued_at`"""
        return issued_at.timestamp()

    @field_serializer("expired_at")
    def serialize_expired_at(self, expired_at: datetime, _info):
        """Customized serialization for `expired_at`"""
        return expired_at.timestamp()

    def valid(self) -> bool:
        """Check if the payload is valid, i.e., `expired_at` > `now()`"""
        return self.expired_at.timestamp() > datetime.datetime.now(datetime.timezone.utc).timestamp()


def paseto_encode(payload: dict) -> str:
    """
    Encode a given payload into a PASETO token using a symmetric key.

    Args:
        payload (dict): The data to be securely encoded into the token.

    Returns:
        str: A PASETO token.
    """
    key = os.getenv("TOKEN_SYMMETRIC_KEY")
    if not key:
        raise ValueError("PASETO_KEY not found in environment variables.")
    key = Key.new(version=4, purpose="local", key=key)
    token = pyseto.encode(key, payload, serializer=json)
    return token.decode("utf-8")


def paseto_decode(token: str) -> dict:
    """
    Decode a PASETO token into its original payload using a symmetric key.

    Args:
        token (str): The PASETO token string to decode.

    Returns:
        dict: The original payload extracted from the token.
    """
    key = os.getenv("TOKEN_SYMMETRIC_KEY")
    if not key:
        raise ValueError("PASETO_KEY not found in environment variables.")
    key = Key.new(version=4, purpose="local", key=key)
    decoded = pyseto.decode(key, token, deserializer=json)
    return decoded.payload


def generate_token(payload: UserTokenPayload):
    """
    Generate an access token given a payload.

    Args:
        payload (UserTokenPayload): The user payload to be encoded into the token.

    Returns:
        str: A PASETO token.
    """
    return paseto_encode(payload.model_dump(mode="json"))


def verify_token(token: str) -> UserTokenPayload:
    """
    Verify if the access token is valid.

    Returns:
        UserTokenPayload: The payload if the token is valid.
    """
    try:
        payload = UserTokenPayload.model_validate(paseto_decode(token))
    except Exception as e:
        raise ValueError("token is invalid") from e
    if not payload.valid():
        raise ValueError("token has expired")
    return payload
