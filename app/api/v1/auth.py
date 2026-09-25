from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import SessionDep
from app.schemas.auth import LoginIn, OAuth2TokenOut, RefreshIn, TokenOut
from app.schemas.user import UserOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user, tokens: auth_service.TokenPair) -> TokenOut:
    return TokenOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: SessionDep, request: Request) -> TokenOut:
    user, tokens = await auth_service.login(
        session, body.email, body.password, request.headers.get("user-agent")
    )
    return _token_response(user, tokens)


@router.post("/token", response_model=OAuth2TokenOut, summary="Login form for the docs")
async def login_form(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
    request: Request,
) -> OAuth2TokenOut:
    """OAuth2 password flow, used by the Authorize button in /docs. Put the email in `username`."""
    _, tokens = await auth_service.login(
        session, form.username, form.password, request.headers.get("user-agent")
    )
    return OAuth2TokenOut(access_token=tokens.access_token)


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, session: SessionDep, request: Request) -> TokenOut:
    user, tokens = await auth_service.refresh(
        session, body.refresh_token, request.headers.get("user-agent")
    )
    return _token_response(user, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshIn, session: SessionDep) -> Response:
    await auth_service.logout(session, body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
