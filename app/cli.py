"""Management commands, run with: uv run python -m app.cli --help"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer
from pydantic import ValidationError
from sqlalchemy import delete, or_

from app.core.database import SessionLocal, engine
from app.core.exceptions import AppError
from app.models import RefreshToken, UserRole
from app.schemas.user import UserCreate
from app.services import users as user_service

cli = typer.Typer(help="BSS Restaurant API management commands", no_args_is_help=True)


def _fail(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(1)


@cli.command()
def create_admin(
    email: Annotated[str, typer.Option(prompt=True)],
    first_name: Annotated[str, typer.Option(prompt=True)],
    last_name: Annotated[str, typer.Option(prompt=True)],
    password: Annotated[str, typer.Option(prompt=True, hide_input=True, confirmation_prompt=True)],
) -> None:
    """Create an admin account. Needed once on a fresh database since there's no sign up."""
    try:
        data = UserCreate(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=UserRole.ADMIN,
        )
    except ValidationError as exc:
        _fail("\n".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()))

    async def run() -> None:
        try:
            async with SessionLocal() as session:
                user = await user_service.create_user(session, data)
                typer.secho(f"Created admin {user.email} (id {user.id})", fg=typer.colors.GREEN)
        except AppError as exc:
            _fail(exc.message)
        finally:
            await engine.dispose()

    asyncio.run(run())


@cli.command()
def prune_tokens(
    days: Annotated[int, typer.Option(help="Keep revoked tokens for this many days")] = 30,
) -> None:
    """Delete expired refresh tokens and old revoked ones."""

    async def run() -> int:
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            result = await session.execute(
                delete(RefreshToken).where(
                    or_(
                        RefreshToken.expires_at < now,
                        RefreshToken.revoked_at < now - timedelta(days=days),
                    )
                )
            )
            await session.commit()
        await engine.dispose()
        return result.rowcount

    typer.echo(f"Deleted {asyncio.run(run())} refresh tokens")


if __name__ == "__main__":
    cli()
