"""Management commands, run with: uv run python -m app.cli --help"""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import typer
from pydantic import ValidationError
from sqlalchemy import delete, or_

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.exceptions import AppError
from app.models import RefreshToken, UserRole
from app.schemas.user import UserCreate
from app.services import demo
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


@cli.command()
def seed_demo(
    days: Annotated[int, typer.Option(min=1, max=180, help="Days of past orders")] = 30,
    password: Annotated[
        str | None, typer.Option(help="Password for the demo staff, random when left out")
    ] = None,
    seed: Annotated[int | None, typer.Option(help="The same seed gives the same data")] = None,
    allow_production: Annotated[
        bool, typer.Option("--allow-production", help="Seed even with ENVIRONMENT=production")
    ] = False,
) -> None:
    """Fill an empty database with a sample menu, tables, staff with logins, and a few
    weeks of orders, payments, expenses and bookings."""
    if settings.is_production and not allow_production:
        _fail("This is production. Pass --allow-production if you really want demo data there")
    password = password or f"demo-{secrets.token_hex(4)}{secrets.randbelow(10)}"

    async def run() -> demo.DemoResult:
        try:
            async with SessionLocal() as session:
                return await demo.seed_demo(session, password=password, days=days, seed=seed)
        except AppError as exc:
            _fail(exc.message)
        finally:
            await engine.dispose()

    typer.echo("Seeding, against a remote database this takes a few minutes...")
    result = asyncio.run(run())
    typer.secho(
        f"Added {result.orders} orders, {result.reservations} bookings and "
        f"{result.expenses} expenses",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"Staff logins, all with the password {result.password}")
    for email, role in result.users:
        typer.echo(f"  {role:<8} {email}")


if __name__ == "__main__":
    cli()
