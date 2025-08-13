from datetime import datetime, timezone

from fastapi import APIRouter, status, UploadFile, Form, File, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from security.interfaces import JWTAuthManagerInterface

from database import get_db

from schemas.profiles import ProfileResponseSchema, ProfileSchema

from config.dependencies import get_s3_storage_client, get_jwt_auth_manager

from storages.interfaces import S3StorageInterface

from database.models.accounts import UserModel, UserProfileModel

from validation.profile import validate_name, validate_gender, validate_birth_date, validate_image

from exceptions.security import TokenExpiredError

router = APIRouter()


async def validate_token(
        authorization: str = Header(None),
        jwt_manager: JWTAuthManagerInterface = Depends(get_jwt_auth_manager),
):
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is missing"
        )

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Authorization header format. Expected 'Bearer <token>'"
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected 'Bearer <token>'"
        )

    try:
        payload = jwt_manager.decode_access_token(token)
        user_id = payload.get("user_id")
        exp = payload.get("exp")

        if exp and datetime.now(timezone.utc).timestamp() > exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired."
            )
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired."
        )
    return user_id


@router.post("/users/{user_id}/profile/", response_model=ProfileResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_profile(
        user_id: int,
        first_name: str = Form(...),
        last_name: str = Form(...),
        gender: str = Form(...),
        date_of_birth: str = Form(...),
        info: str = Form(...),
        avatar: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        s3_client: S3StorageInterface = Depends(get_s3_storage_client),
        current_user_id: int = Depends(validate_token)
):
    try:
        validate_name(first_name)
        validate_name(last_name)
        first_name = first_name.lower()
        last_name = last_name.lower()
        validate_gender(gender)

        birth_date = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
        validate_birth_date(birth_date)

        if not info or info.strip() == "":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Info field cannot be empty or contain only spaces."
            )

        validate_image(avatar)

        avatar_data = await avatar.read()

    except ValueError as e:
        if "time data" in str(e):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[{
                    "type": "value_error",
                    "loc": ["body", "date_of_birth"],
                    "msg": "Invalid date format. Expected YYYY-MM-DD",
                    "input": date_of_birth
                }]
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{
                "type": "value_error",
                "loc": ["body"],
                "msg": str(e),
                "input": None
            }]
        )

    if current_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to edit this profile."
        )

    user_query = select(UserModel).where(UserModel.id == user_id, UserModel.is_active == True)
    result = await db.execute(user_query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active."
        )

    profile_query = select(UserProfileModel).where(UserProfileModel.user_id == user_id)
    result = await db.execute(profile_query)
    existing_profile = result.scalar_one_or_none()

    if existing_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has a profile."
        )

    try:
        avatar_filename = f"{user_id}_avatar.jpg"
        avatar_url = await s3_client.upload_file(
            file_data=avatar_data,
            filename=avatar_filename,
            bucket="avatars"
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload avatar. Please try again later."
        )

    try:
        new_profile = UserProfileModel(
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            date_of_birth=birth_date,
            info=info,
            avatar=avatar_url
        )

        db.add(new_profile)
        await db.commit()
        await db.refresh(new_profile)

        return ProfileResponseSchema.model_validate(new_profile)

    except SQLAlchemyError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create profile. Please try again later."
        )
