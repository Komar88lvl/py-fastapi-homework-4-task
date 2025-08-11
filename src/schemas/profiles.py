from datetime import date

from fastapi import UploadFile, Form, File, HTTPException
from pydantic import BaseModel, field_validator, HttpUrl

from validation import (
    validate_name,
    validate_image,
    validate_gender,
    validate_birth_date
)

class ProfileSchema(BaseModel):
    first_name: str = Form(...),
    last_name: str = Form(...),
    gender: str = Form(...),
    date_of_birth: date = Form(...),
    info: str = Form(...),
    avatar: UploadFile = File(...)

    @field_validator("first_name")
    def validate_name(cls, value):
        return validate_name(value)

    @field_validator("last_name")
    def validate_name(cls, value):
        return validate_name(value)

    @field_validator("gender")
    def validate_gender(cls, value):
        return validate_gender(value)

    @field_validator("date_of_birth")
    def validate_birth_date(cls, value):
        return validate_birth_date(value)

    @field_validator("info")
    def validate_info(cls, value):
        if not value.strip():
            raise ValueError("Info cannot be empty or spaces only.")
        return value
