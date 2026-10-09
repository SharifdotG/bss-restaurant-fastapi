"""Sample data for trying the api or building a frontend: a menu, tables, staff with
logins, a few weeks of orders, payments, expenses and bookings."""

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.security import hash_password
from app.core.timeutils import business_date, restaurant_tz, utcnow
from app.models import (
    Category,
    DiningTable,
    DiscountType,
    Employee,
    Expense,
    ExpenseCategory,
    Food,
    Order,
    OrderSource,
    OrderStatus,
    OrderStatusEvent,
    OrderType,
    Payment,
    PaymentMethod,
    Reservation,
    ReservationSource,
    ReservationStatus,
    TableAssignment,
    User,
    UserRole,
)
from app.schemas.order import OrderItemIn
from app.services.orders import build_order
from app.services.restaurant import get_restaurant

# name, price, (discount type, value), featured
MENU: dict[str, list[tuple[str, str, tuple[str, int] | None, bool]]] = {
    "Starters": [
        ("Vegetable Samosa (4 pcs)", "120", None, False),
        ("Chicken Pakora", "220", None, False),
        ("Fuchka", "100", None, True),
        ("Chotpoti", "110", None, False),
    ],
    "Rice and Biryani": [
        ("Kacchi Biryani", "420", None, True),
        ("Chicken Biryani", "320", ("percentage", 10), False),
        ("Beef Tehari", "260", None, False),
        ("Plain Polao", "120", None, False),
        ("Khichuri with Egg", "180", None, False),
    ],
    "Curries": [
        ("Beef Bhuna", "350", None, True),
        ("Chicken Rezala", "300", None, False),
        ("Mutton Kala Bhuna", "480", None, False),
        ("Dal Makhani", "160", None, False),
        ("Shorshe Ilish", "550", ("flat", 50), True),
    ],
    "Grill": [
        ("Chicken Tikka Kebab", "280", None, False),
        ("Beef Seekh Kebab", "300", None, False),
        ("Naan", "40", None, False),
        ("Butter Naan", "60", None, False),
    ],
    "Drinks": [
        ("Borhani", "80", None, True),
        ("Mango Lassi", "150", None, False),
        ("Lemon Mint", "120", ("percentage", 20), False),
        ("Mineral Water", "30", None, False),
        ("Milk Tea", "40", None, False),
    ],
    "Desserts": [
        ("Mishti Doi", "90", None, False),
        ("Firni", "100", None, False),
        ("Rasmalai (2 pcs)", "140", None, False),
    ],
}

# number, seats, location
TABLES = [
    ("T1", 2, "Ground floor"),
    ("T2", 2, "Ground floor"),
    ("T3", 4, "Ground floor"),
    ("T4", 4, "Ground floor"),
    ("T5", 4, "Window"),
    ("T6", 6, "Window"),
    ("T7", 8, "Family room"),
    ("R1", 2, "Rooftop"),
    ("R2", 4, "Rooftop"),
    ("R3", 6, "Rooftop"),
]

# email name, first, last, role, designation, salary
STAFF = [
    ("manager", "Nusrat", "Jahan", UserRole.MANAGER, "Manager", 60000),
    ("cashier", "Arif", "Hossain", UserRole.CASHIER, "Cashier", 28000),
    ("waiter", "Rafiq", "Islam", UserRole.WAITER, "Waiter", 18000),
    ("waiter2", "Sumaiya", "Akter", UserRole.WAITER, "Waiter", 18000),
    ("chef", "Kamal", "Uddin", UserRole.CHEF, "Head chef", 45000),
]
EMAIL_DOMAIN = "example.com"

CUSTOMERS = ["Rahim", "Karim", "Fatema", "Tanvir", "Nadia", "Sakib", "Mitu", "Imran", "Farhana"]
CANCEL_REASONS = ["customer left", "ordered by mistake", "took too long"]


@dataclass
class DemoResult:
    password: str
    users: list[tuple[str, UserRole]] = field(default_factory=list)
    orders: int = 0
    reservations: int = 0
    expenses: int = 0


def _local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=restaurant_tz())


def _round_up(amount: Decimal, to: int) -> Decimal:
    return (amount / to).quantize(Decimal(1), rounding=ROUND_UP) * to


async def ensure_empty(session: AsyncSession) -> None:
    for model in (Food, Order, DiningTable):
        if await session.scalar(select(func.count()).select_from(model)):
            raise ConflictError(
                "The database already has a menu, tables or orders. Demo data only goes "
                "into an empty one",
                code="not_empty",
            )


class DemoBuilder:
    def __init__(self, session: AsyncSession, rng: random.Random, password: str) -> None:
        self.session = session
        self.rng = rng
        self.result = DemoResult(password=password)
        self.foods: list[Food] = []
        self.tables: list[DiningTable] = []
        self.staff: dict[str, User] = {}
        self.waiters: list[Employee] = []

    async def restaurant(self) -> None:
        restaurant = await get_restaurant(self.session)
        restaurant.name = "Shorshe Kitchen"
        restaurant.address = "House 12, Road 5, Dhanmondi, Dhaka"
        restaurant.phone = "+8801700000000"
        restaurant.vat_percent = Decimal("7.5")
        restaurant.service_charge_percent = Decimal(5)
        restaurant.receipt_footer = "Thank you, come again!"
        restaurant.accepts_online_orders = True
        restaurant.accepts_reservations = True

    async def menu(self) -> None:
        for position, (name, foods) in enumerate(MENU.items()):
            category = Category(name=name, sort_order=position)
            for food_name, price, discount, featured in foods:
                discount_type, value = discount or (DiscountType.NONE, 0)
                self.foods.append(
                    Food(
                        name=food_name,
                        category=category,
                        price=Decimal(price),
                        discount_type=discount_type,
                        discount_value=Decimal(value),
                        is_featured=featured,
                        preparation_minutes=self.rng.choice([5, 10, 15, 20, 25]),
                    )
                )
        self.session.add_all(self.foods)

    async def tables_and_staff(self) -> None:
        self.tables = [DiningTable(number=n, seats=s, location=loc) for n, s, loc in TABLES]
        self.session.add_all(self.tables)

        password_hash = hash_password(self.result.password)
        start = business_date() - timedelta(days=400)
        employees = []
        for key, first, last, role, designation, salary in STAFF:
            email = f"{key}@{EMAIL_DOMAIN}"
            if await self.session.scalar(select(User.id).where(func.lower(User.email) == email)):
                raise ConflictError(f"A user {email} already exists", code="not_empty")
            user = User(
                email=email,
                password_hash=password_hash,
                first_name=first,
                last_name=last,
                role=role,
            )
            employee = Employee(
                user=user,
                first_name=first,
                last_name=last,
                email=email,
                designation=designation,
                join_date=start + timedelta(days=self.rng.randint(0, 200)),
                monthly_salary=Decimal(salary),
            )
            self.staff[key] = user
            employees.append(employee)
            self.result.users.append((email, role))
        self.session.add_all(employees)
        await self.session.flush()

        self.waiters = [e for e in employees if e.user.role == UserRole.WAITER]
        downstairs, rooftop = self.waiters
        self.session.add_all(
            TableAssignment(
                table_id=table.id,
                employee_id=(rooftop if table.number.startswith("R") else downstairs).id,
            )
            for table in self.tables
        )

    def _items(self) -> list[OrderItemIn]:
        foods = self.rng.sample(self.foods, self.rng.randint(1, 4))
        return [
            OrderItemIn(food_id=food.id, quantity=self.rng.choice([1, 1, 1, 2, 2, 3]))
            for food in foods
        ]

    async def _order(self, placed_at: datetime, table: DiningTable | None = None) -> Order:
        waiter = self.rng.choice(self.waiters)
        takeaway = table is None
        online = takeaway and self.rng.random() < 0.3
        qr = not takeaway and self.rng.random() < 0.2
        order = await build_order(
            self.session,
            order_type=OrderType.TAKEAWAY if takeaway else OrderType.DINE_IN,
            source=OrderSource.ONLINE if online else OrderSource.QR if qr else OrderSource.STAFF,
            items=self._items(),
            table_id=table.id if table else None,
            waiter_id=waiter.id,
            created_by_id=None if online or qr else waiter.user_id,
            customer_name=self.rng.choice(CUSTOMERS) if takeaway else None,
            customer_phone=f"017{self.rng.randint(10000000, 99999999)}" if online else None,
            placed_at=placed_at,
        )
        self.result.orders += 1
        return order

    def _move(self, order: Order, status: OrderStatus, at: datetime, by: User, note=None) -> None:
        order.history.append(
            OrderStatusEvent(
                from_status=order.status,
                to_status=status,
                changed_by_id=by.id,
                note=note,
                created_at=at,
            )
        )
        order.status = status
        order.updated_at = at

    def _walk(self, order: Order, until: OrderStatus, start: datetime) -> datetime:
        """Moves an order through the kitchen up to `until`, a few minutes per step."""
        steps = [
            (OrderStatus.CONFIRMED, self.staff["waiter"], 2),
            (OrderStatus.PREPARING, self.staff["chef"], 4),
            (OrderStatus.READY, self.staff["chef"], 15),
            (OrderStatus.SERVED, self.staff["waiter"], 3),
        ]
        at = start
        for status, by, minutes in steps:
            at += timedelta(minutes=minutes + self.rng.randint(0, 5))
            self._move(order, status, at, by)
            if status == until:
                break
        return at

    def _pay(self, order: Order, at: datetime) -> None:
        cashier = self.staff["cashier"]
        method = self.rng.choices(list(PaymentMethod), weights=[6, 2, 3])[0]
        payment = Payment(
            method=method,
            amount=order.total,
            received_by_id=cashier.id,
            created_at=at,
        )
        if method == PaymentMethod.CASH:
            payment.tendered = _round_up(order.total, self.rng.choice([100, 500]))
        else:
            payment.reference = f"TX{self.rng.randint(10**7, 10**8 - 1)}"
        order.payments = [payment]
        order.amount_paid = order.total
        self._move(order, OrderStatus.PAID, at, cashier, "bill settled")
        order.closed_at = at

    async def past_orders(self, days: int) -> None:
        today = business_date()
        # today too, but only what would be finished by now
        latest = utcnow() - timedelta(hours=2)
        for back in range(days, -1, -1):
            day = today - timedelta(days=back)
            # busier on friday and saturday
            count = self.rng.randint(20, 30) + (10 if day.weekday() in (4, 5) else 0)
            for _ in range(count):
                placed = _local(day, self.rng.randint(12, 21), self.rng.randint(0, 59))
                if placed > latest:
                    continue
                table = self.rng.choice(self.tables) if self.rng.random() < 0.75 else None
                order = await self._order(placed, table)
                if self.rng.random() < 0.05:
                    at = placed + timedelta(minutes=10)
                    reason = self.rng.choice(CANCEL_REASONS)
                    self._move(order, OrderStatus.CANCELLED, at, self.staff["waiter"], reason)
                    order.cancel_reason = reason
                    order.closed_at = at
                    continue
                served = self._walk(order, OrderStatus.SERVED, placed)
                self._pay(order, served + timedelta(minutes=self.rng.randint(15, 50)))

    async def open_orders(self) -> None:
        """What's going on right now, so the kitchen screen and dashboard aren't empty."""
        now = utcnow()
        tables = self.rng.sample(self.tables, 5)
        for minutes_ago, status, table in [
            (2, OrderStatus.PENDING, tables[0]),
            (6, OrderStatus.CONFIRMED, tables[1]),
            (14, OrderStatus.PREPARING, tables[2]),
            (25, OrderStatus.READY, None),
            (40, OrderStatus.SERVED, tables[3]),
            (55, OrderStatus.SERVED, tables[4]),
        ]:
            placed = now - timedelta(minutes=minutes_ago)
            order = await self._order(placed, table)
            if status != OrderStatus.PENDING:
                # squeeze the steps into the time since it was placed
                self._walk(order, status, placed)
                for event in order.history[1:]:
                    event.created_at = min(event.created_at, now)
                order.updated_at = order.history[-1].created_at

    async def expenses(self, days: int) -> None:
        today = business_date()
        manager = self.staff["manager"]
        salaries = sum(salary for *_, salary in STAFF)

        def add(day: date, title: str, category: ExpenseCategory, amount, paid_to=None) -> None:
            self.session.add(
                Expense(
                    title=title,
                    category=category,
                    amount=Decimal(amount),
                    expense_date=day,
                    paid_to=paid_to,
                    created_by_id=manager.id,
                )
            )
            self.result.expenses += 1

        for back in range(days, -1, -1):
            day = today - timedelta(days=back)
            if day.day == 1:
                add(day, "Shop rent", ExpenseCategory.RENT, 60000, "Landlord")
                add(day, "Staff salaries", ExpenseCategory.SALARY, salaries)
            if day.weekday() != 4:
                amount = self.rng.randrange(5000, 9000, 50)
                add(day, "Kaptan bazar shopping", ExpenseCategory.INGREDIENTS, amount)
            if day.weekday() == 6:
                add(
                    day,
                    "Gas cylinders",
                    ExpenseCategory.UTILITIES,
                    self.rng.randrange(3000, 5000, 100),
                )
            if self.rng.random() < 0.08:
                add(
                    day,
                    "Kitchen repairs",
                    ExpenseCategory.MAINTENANCE,
                    self.rng.randrange(1500, 6000, 100),
                )

    async def reservations(self) -> None:
        today = business_date()
        bookable = [t for t in self.tables if t.seats >= 2]

        def booking(day: date, hour: int, status, table, source=ReservationSource.STAFF):
            starts = _local(day, hour)
            party = self.rng.randint(2, table.seats if table else 4)
            self.session.add(
                Reservation(
                    source=source,
                    status=status,
                    table_id=table.id if table else None,
                    party_size=party,
                    starts_at=starts,
                    ends_at=starts + timedelta(minutes=90),
                    customer_name=self.rng.choice(CUSTOMERS),
                    customer_phone=f"018{self.rng.randint(10000000, 99999999)}",
                    created_by_id=None
                    if source == ReservationSource.ONLINE
                    else self.staff["manager"].id,
                )
            )
            self.result.reservations += 1

        for back in range(1, 8):
            day = today - timedelta(days=back)
            for hour, table in zip((13, 20), self.rng.sample(bookable, 2), strict=True):
                status = (
                    ReservationStatus.NO_SHOW
                    if self.rng.random() < 0.1
                    else ReservationStatus.COMPLETED
                )
                booking(day, hour, status, table)
        for ahead in range(1, 4):
            day = today + timedelta(days=ahead)
            # different tables in the same evening, so nothing overlaps
            for hour, table in zip((19, 20, 21), self.rng.sample(bookable, 3), strict=True):
                booking(day, hour, ReservationStatus.CONFIRMED, table)
        for ahead in (1, 2):
            booking(
                today + timedelta(days=ahead),
                13,
                ReservationStatus.REQUESTED,
                None,
                ReservationSource.ONLINE,
            )


async def seed_demo(
    session: AsyncSession, *, password: str, days: int = 30, seed: int | None = None
) -> DemoResult:
    """Fills an empty database. Everything is one transaction, it's all or nothing."""
    await ensure_empty(session)
    builder = DemoBuilder(session, random.Random(seed), password)
    await builder.restaurant()
    await builder.menu()
    await builder.tables_and_staff()
    await builder.past_orders(days)
    await builder.open_orders()
    await builder.expenses(days)
    await builder.reservations()
    await session.commit()
    return builder.result
