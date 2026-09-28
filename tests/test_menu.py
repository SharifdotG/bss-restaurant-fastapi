import pytest
from httpx import AsyncClient

from app.models import User, UserRole
from tests.conftest import UserFactory, auth_header
from tests.test_uploads import make_image

pytestmark = pytest.mark.anyio


@pytest.fixture
async def manager(make_user: UserFactory) -> User:
    return await make_user(UserRole.MANAGER)


async def create_category(client: AsyncClient, manager: User, name: str = "Burgers", **extra):
    response = await client.post(
        "/categories", headers=auth_header(manager), json={"name": name, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def create_food(client: AsyncClient, manager: User, **overrides):
    payload = {"name": "Beef Burger", "price": 350} | overrides
    return await client.post("/foods", headers=auth_header(manager), json=payload)


# categories


async def test_categories_are_ordered_and_counted(client: AsyncClient, manager: User) -> None:
    drinks = await create_category(client, manager, "Drinks", sortOrder=2)
    burgers = await create_category(client, manager, "Burgers", sortOrder=1)
    await create_category(client, manager, "Old stuff", isActive=False)
    await create_food(client, manager, categoryId=burgers["id"])

    listed = (await client.get("/categories", headers=auth_header(manager))).json()

    assert [c["name"] for c in listed] == ["Burgers", "Drinks"]
    assert listed[0]["foodCount"] == 1
    assert listed[1]["id"] == drinks["id"] and listed[1]["foodCount"] == 0

    everything = await client.get("/categories?includeInactive=true", headers=auth_header(manager))
    assert len(everything.json()) == 3


async def test_category_names_are_unique(client: AsyncClient, manager: User) -> None:
    await create_category(client, manager, "Burgers")

    response = await client.post(
        "/categories", headers=auth_header(manager), json={"name": "BURGERS"}
    )

    assert response.status_code == 409


async def test_category_with_foods_cannot_be_deleted(client: AsyncClient, manager: User) -> None:
    category = await create_category(client, manager)
    food = (await create_food(client, manager, categoryId=category["id"])).json()
    headers = auth_header(manager)

    blocked = await client.delete(f"/categories/{category['id']}", headers=headers)
    assert blocked.json()["code"] == "category_not_empty"

    await client.delete(f"/foods/{food['id']}", headers=headers)
    assert (
        await client.delete(f"/categories/{category['id']}", headers=headers)
    ).status_code == 204


async def test_waiters_can_read_but_not_edit_the_menu(
    client: AsyncClient, make_user: UserFactory, manager: User
) -> None:
    waiter = await make_user(UserRole.WAITER)
    await create_category(client, manager)

    assert (await client.get("/categories", headers=auth_header(waiter))).status_code == 200
    denied = await client.post("/categories", headers=auth_header(waiter), json={"name": "X"})
    assert denied.status_code == 403
    assert (await create_food(client, waiter)).status_code == 403


# foods


@pytest.mark.parametrize(
    ("discount_type", "value", "final"),
    [("none", 0, 350.0), ("percentage", 15, 297.5), ("flat", 50.5, 299.5)],
)
async def test_final_price_is_calculated_by_the_server(
    client: AsyncClient, manager: User, discount_type: str, value: float, final: float
) -> None:
    response = await create_food(
        client, manager, price=350, discountType=discount_type, discountValue=value
    )

    assert response.status_code == 201
    body = response.json()
    assert body["finalPrice"] == final
    assert body["hasDiscount"] is (discount_type != "none")


@pytest.mark.parametrize(
    ("discount_type", "value"), [("percentage", 101), ("flat", 351), ("none", -1)]
)
async def test_invalid_discounts_are_rejected(
    client: AsyncClient, manager: User, discount_type: str, value: float
) -> None:
    response = await create_food(client, manager, discountType=discount_type, discountValue=value)

    assert response.status_code == 422


async def test_lowering_price_below_flat_discount_fails(client: AsyncClient, manager: User) -> None:
    food = (await create_food(client, manager, discountType="flat", discountValue=100)).json()

    response = await client.patch(
        f"/foods/{food['id']}", headers=auth_header(manager), json={"price": 80}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_discount"


async def test_food_names_are_unique_until_deleted(client: AsyncClient, manager: User) -> None:
    first = (await create_food(client, manager, name="Fries")).json()
    assert (await create_food(client, manager, name="fries")).status_code == 409

    await client.delete(f"/foods/{first['id']}", headers=auth_header(manager))

    assert (await create_food(client, manager, name="Fries")).status_code == 201


async def test_deleted_food_is_hidden(client: AsyncClient, manager: User) -> None:
    food = (await create_food(client, manager)).json()
    headers = auth_header(manager)

    assert (await client.delete(f"/foods/{food['id']}", headers=headers)).status_code == 204

    assert (await client.get(f"/foods/{food['id']}", headers=headers)).status_code == 404
    assert (await client.get("/foods", headers=headers)).json()["total"] == 0


async def test_update_changes_category(client: AsyncClient, manager: User) -> None:
    burgers = await create_category(client, manager, "Burgers")
    sides = await create_category(client, manager, "Sides")
    food = (await create_food(client, manager, categoryId=burgers["id"])).json()

    response = await client.patch(
        f"/foods/{food['id']}", headers=auth_header(manager), json={"categoryId": sides["id"]}
    )

    assert response.json()["category"] == {"id": sides["id"], "name": "Sides"}

    cleared = await client.patch(
        f"/foods/{food['id']}", headers=auth_header(manager), json={"categoryId": None}
    )
    assert cleared.json()["category"] is None


async def test_unknown_category(client: AsyncClient, manager: User) -> None:
    response = await create_food(client, manager, categoryId=999)

    assert response.json()["code"] == "invalid_category"


async def test_list_foods_filters_search_and_sort(client: AsyncClient, manager: User) -> None:
    burgers = await create_category(client, manager, "Burgers")
    await create_food(client, manager, name="Beef Burger", price=350, categoryId=burgers["id"])
    await create_food(
        client,
        manager,
        name="Chicken Burger",
        price=300,
        discountType="percentage",
        discountValue=50,
        categoryId=burgers["id"],
    )
    await create_food(client, manager, name="Fries", price=120, isAvailable=False)
    headers = auth_header(manager)

    by_category = (await client.get(f"/foods?categoryId={burgers['id']}", headers=headers)).json()
    assert by_category["total"] == 2

    search = (await client.get("/foods?search=burger&sort=finalPrice", headers=headers)).json()
    assert [f["name"] for f in search["items"]] == ["Chicken Burger", "Beef Burger"]

    available = (await client.get("/foods?isAvailable=false", headers=headers)).json()
    assert [f["name"] for f in available["items"]] == ["Fries"]


async def test_chef_can_mark_food_sold_out(
    client: AsyncClient, make_user: UserFactory, manager: User
) -> None:
    chef = await make_user(UserRole.CHEF)
    waiter = await make_user(UserRole.WAITER)
    food = (await create_food(client, manager)).json()
    url = f"/foods/{food['id']}/availability"

    response = await client.put(url, headers=auth_header(chef), json={"isAvailable": False})
    assert response.status_code == 200
    assert response.json()["isAvailable"] is False

    denied = await client.put(url, headers=auth_header(waiter), json={"isAvailable": True})
    assert denied.status_code == 403


async def test_food_image(client: AsyncClient, manager: User) -> None:
    headers = auth_header(manager)
    upload = await client.post(
        "/uploads/images",
        headers=headers,
        data={"folder": "foods"},
        files={"file": ("a.png", make_image(), "image/png")},
    )
    key = upload.json()["key"]

    food = (await create_food(client, manager, imageKey=key)).json()
    assert food["imageUrl"] == f"/media/{key}"
    assert "imageKey" not in food

    wrong_folder = key.replace("foods/", "tables/")
    bad = await client.patch(
        f"/foods/{food['id']}", headers=headers, json={"imageKey": wrong_folder}
    )
    assert bad.json()["code"] == "invalid_image_key"

    removed = await client.patch(f"/foods/{food['id']}", headers=headers, json={"imageKey": None})
    assert removed.json()["imageUrl"] is None
