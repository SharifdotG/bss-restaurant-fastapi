from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.pagination import apply_sort, paginate, search_filter
from app.core.security import hash_password, verify_password
from app.models import User, UserRole
from app.schemas.common import Page
from app.schemas.user import ProfileUpdate, UserCreate, UserListParams, UserOut, UserUpdate
from app.services import auth as auth_service


async def ensure_unique(
    session: AsyncSession,
    *,
    email: str | None = None,
    phone: str | None = None,
    exclude_id: int | None = None,
) -> None:
    if email is not None:
        stmt = select(User.id).where(func.lower(User.email) == email.lower())
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        if await session.scalar(stmt):
            raise ConflictError("A user with this email already exists", code="email_taken")

    if phone is not None:
        stmt = select(User.id).where(User.phone == phone)
        if exclude_id is not None:
            stmt = stmt.where(User.id != exclude_id)
        if await session.scalar(stmt):
            raise ConflictError("A user with this phone number already exists", code="phone_taken")


async def commit_or_conflict(session: AsyncSession) -> None:
    # the checks above can still lose a race with another request
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("A user with this email or phone number already exists") from None


async def update_profile(session: AsyncSession, user: User, data: ProfileUpdate) -> User:
    changes = data.model_dump(exclude_unset=True)
    if changes.get("phone"):
        await ensure_unique(session, phone=changes["phone"], exclude_id=user.id)
    for field, value in changes.items():
        if field in ("first_name", "last_name") and value is None:
            continue
        setattr(user, field, value)
    await commit_or_conflict(session)
    return user


async def change_password(
    session: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
    user_agent: str | None,
) -> auth_service.TokenPair:
    valid, _ = verify_password(current_password, user.password_hash)
    if not valid:
        raise BadRequestError("Current password is incorrect", code="wrong_password")

    user.password_hash = hash_password(new_password)
    # log out every other device, this one gets a fresh pair
    await auth_service.revoke_all_sessions(session, user.id)
    tokens = auth_service.issue_tokens(session, user, user_agent)
    await session.commit()
    return tokens


PRIVILEGED_ROLES = {UserRole.ADMIN, UserRole.MANAGER}

USER_SORTS = {
    "createdAt": User.created_at,
    "email": User.email,
    "firstName": User.first_name,
    "lastName": User.last_name,
    "role": User.role,
    "lastLoginAt": User.last_login_at,
}


def _check_can_manage(actor: User | None, role: UserRole) -> None:
    # actor is None for things like the cli
    if actor is not None and actor.role != UserRole.ADMIN and role in PRIVILEGED_ROLES:
        raise PermissionDeniedError("Only admins can manage admin and manager accounts")


async def _ensure_other_admin_exists(session: AsyncSession, user: User) -> None:
    if user.role != UserRole.ADMIN:
        return
    others = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != user.id)
    )
    if not others:
        raise ConflictError("There must be at least one active admin", code="last_admin")


async def list_users(session: AsyncSession, params: UserListParams) -> Page[UserOut]:
    stmt = select(User)
    if params.role is not None:
        stmt = stmt.where(User.role == params.role)
    if params.is_active is not None:
        stmt = stmt.where(User.is_active.is_(params.is_active))
    term = search_filter(params.search, User.email, User.first_name, User.last_name, User.phone)
    if term is not None:
        stmt = stmt.where(term)
    stmt = apply_sort(stmt, params.sort, USER_SORTS, default="-createdAt", tiebreaker=User.id)
    return await paginate(session, stmt, params, UserOut)


async def get_user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return user


async def create_user(session: AsyncSession, data: UserCreate, actor: User | None = None) -> User:
    _check_can_manage(actor, data.role)
    email = data.email.lower()
    await ensure_unique(session, email=email, phone=data.phone)

    user = User(
        email=email,
        password_hash=hash_password(data.password),
        first_name=data.first_name,
        last_name=data.last_name,
        phone=data.phone,
        role=data.role,
    )
    session.add(user)
    await commit_or_conflict(session)
    return user


async def update_user(session: AsyncSession, actor: User, user: User, data: UserUpdate) -> User:
    changes = data.model_dump(exclude_unset=True)
    _check_can_manage(actor, user.role)
    if "role" in changes and changes["role"] is not None:
        _check_can_manage(actor, changes["role"])

    role_change = changes.get("role") not in (None, user.role)
    if user.id == actor.id and (role_change or changes.get("is_active") is False):
        raise BadRequestError("You can't change your own role or deactivate yourself")

    demoting = changes.get("role") not in (None, UserRole.ADMIN)
    if demoting or changes.get("is_active") is False:
        await _ensure_other_admin_exists(session, user)

    if changes.get("phone"):
        await ensure_unique(session, phone=changes["phone"], exclude_id=user.id)

    for field, value in changes.items():
        # only phone can be cleared, the rest ignore an explicit null
        if value is None and field != "phone":
            continue
        setattr(user, field, value)

    if changes.get("is_active") is False:
        await auth_service.revoke_all_sessions(session, user.id)
    await commit_or_conflict(session)
    return user


async def reset_password(session: AsyncSession, actor: User, user: User, new_password: str) -> None:
    _check_can_manage(actor, user.role)
    user.password_hash = hash_password(new_password)
    await auth_service.revoke_all_sessions(session, user.id)
    await session.commit()


async def deactivate_user(session: AsyncSession, actor: User, user: User) -> None:
    _check_can_manage(actor, user.role)
    if user.id == actor.id:
        raise BadRequestError("You can't deactivate yourself")
    await _ensure_other_admin_exists(session, user)
    user.is_active = False
    await auth_service.revoke_all_sessions(session, user.id)
    await session.commit()
