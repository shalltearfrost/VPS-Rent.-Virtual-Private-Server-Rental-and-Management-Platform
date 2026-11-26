import secrets
from datetime import timedelta
from ipaddress import ip_address
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, func, select, text, true, tuple_
from sqlalchemy.orm import aliased

from app.config import get_settings
from app.models import (
    Activity,
    LoginSession,
    OperationRequest,
    Order,
    Plan,
    Rental,
    Server,
    Ticket,
    TicketMessage,
    User,
)
from app.pagination import PageParams, paginate
from app.presenters import (
    operation_view,
    order_view,
    order_views,
    plan_view,
    rental_view,
)
from app.schemas import (
    AllocationInput,
    Credentials,
    MessageInput,
    OperationInput,
    OrderInput,
    PlanInput,
    PreparationInput,
    ResolutionInput,
    ServerInput,
    TicketInput,
    TicketStatusInput,
)
from app.security import (
    CurrentUser,
    Customer,
    Db,
    Manager,
    Operator,
    Support,
    decrypt_password,
    dummy_hash,
    encrypt_password,
    now,
    password_hasher,
    require_role,
    token_hash,
)
from app.services import (
    allocate,
    create_order,
    flag_expired,
    owned_order,
    owned_rental,
    record,
    request_operation,
    require_active,
    resolve_operation,
)

router = APIRouter(prefix="/api")
TicketUser = Annotated[User, Depends(require_role("customer", "support"))]
StaffHistory = Annotated[
    User, Depends(require_role("operator", "support", "manager"))
]
# Activity entity types each staff role may read in its history.
ACTIVITY_SCOPES = {
    "support": ("ticket",),
    "operator": ("order", "invoice", "rental", "server", "operation"),
    "manager": ("plan",),
}


def user_view(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "google_linked": user.google_sub is not None,
    }


def begin_session(
    db: Db, user: User, response: Response, request: Request
) -> dict:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    old_token = request.cookies.get("vps_session")
    if old_token:
        db.execute(
            delete(LoginSession).where(
                LoginSession.token_hash == token_hash(old_token)
            )
        )
    db.add(
        LoginSession(
            authenticated_at=now(),
            user_id=user.id,
            token_hash=token_hash(token),
            csrf_token=csrf,
            expires_at=now() + timedelta(hours=settings.session_hours),
        )
    )
    db.flush()
    response.set_cookie(
        "vps_session",
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_hours * 3600,
    )
    return {"user": user_view(user), "csrf_token": csrf}


@router.get("/health")
def health(db: Db):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "postgresql"}


@router.post("/auth/register", status_code=201)
def register(data: Credentials, db: Db, response: Response, request: Request):
    email = str(data.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(
        email=email,
        password_hash=password_hasher.hash(data.password),
        role="customer",
    )
    db.add(user)
    db.flush()
    return begin_session(db, user, response, request)


@router.post("/auth/login")
def login(data: Credentials, db: Db, response: Response, request: Request):
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    # Google-only accounts have no password; verify against a dummy hash
    # so the response time does not reveal that the account exists.
    stored = user.password_hash if user and user.password_hash else None
    valid = password_hasher.verify(data.password, stored or dummy_hash)
    valid = valid and stored is not None
    if not user or not valid:
        raise HTTPException(401, "Email or password is incorrect")
    return begin_session(db, user, response, request)


@router.get("/auth/me")
def me(user: CurrentUser, request: Request):
    return {
        "user": user_view(user),
        "csrf_token": request.state.login_session.csrf_token,
    }


@router.post("/auth/logout", status_code=204)
def logout(user: CurrentUser, db: Db, request: Request, response: Response):
    db.delete(request.state.login_session)
    response.delete_cookie("vps_session")


@router.get("/plans")
def plans(db: Db):
    return [
        plan_view(item)
        for item in db.scalars(
            select(Plan).where(Plan.enabled.is_(True)).order_by(Plan.id)
        )
    ]


@router.get("/management/plans")
def management_plans(user: Manager, db: Db):
    return [
        plan_view(item) for item in db.scalars(select(Plan).order_by(Plan.id))
    ]


@router.post("/management/plans", status_code=201)
def add_plan(data: PlanInput, user: Manager, db: Db):
    plan = Plan(**data.model_dump())
    db.add(plan)
    db.flush()
    record(db, user, "plan_created", "plan", plan.id, plan.name)
    return plan_view(plan)


@router.put("/management/plans/{plan_id}")
def update_plan(plan_id: int, data: PlanInput, user: Manager, db: Db):
    plan = db.scalar(select(Plan).where(Plan.id == plan_id).with_for_update())
    if not plan:
        raise HTTPException(404, "Plan not found")
    for key, value in data.model_dump().items():
        setattr(plan, key, value)
    db.flush()
    record(db, user, "plan_updated", "plan", plan.id, plan.name)
    return plan_view(plan)


@router.get("/orders")
def orders(user: Customer, db: Db):
    return order_views(
        db,
        db.scalars(
            select(Order)
            .where(Order.customer_id == user.id)
            .order_by(Order.id.desc())
        ).all(),
    )


@router.post("/orders", status_code=201)
def place_order(data: OrderInput, user: Customer, db: Db):
    return order_view(db, create_order(db, user, data.plan_id, data.term))


@router.get("/orders/{order_id}")
def order_details(order_id: int, user: Customer, db: Db):
    return order_view(db, owned_order(db, order_id, user))


@router.get("/rentals")
def rentals(user: Customer, db: Db):
    return [
        rental_view(db, item)
        for item in db.scalars(
            select(Rental)
            .join(Order)
            .where(Order.customer_id == user.id)
            .order_by(Rental.id.desc())
        )
    ]


@router.get("/rentals/{rental_id}")
def rental_details(rental_id: int, user: Customer, db: Db):
    rental, _ = owned_rental(db, rental_id, user)
    return rental_view(db, rental)


@router.post("/rentals/{rental_id}/reveal-password")
def reveal_password(rental_id: int, user: Customer, db: Db):
    rental, _ = owned_rental(db, rental_id, user, lock=True)
    require_active(rental)
    server = db.get(Server, rental.server_id)
    record(db, user, "password_viewed", "rental", rental.id, "Viewed by owner")
    return {"password": decrypt_password(server.password_ciphertext)}


@router.post("/rentals/{rental_id}/operations", status_code=201)
def request_action(
    rental_id: int, data: OperationInput, user: Customer, db: Db
):
    return operation_view(request_operation(db, user, rental_id, data.kind))


@router.get("/operator/queue")
def queue(user: Operator, db: Db, page: PageParams):
    result = paginate(
        db,
        select(Order, User.email)
        .join(User, User.id == Order.customer_id)
        .where(Order.status == "awaiting_allocation"),
        [Order.created_at, Order.id],
        page,
        descending=False,
        key=lambda row: (row[0].created_at, row[0].id),
    )
    orders = [order for order, _ in result["rows"]]
    matches = matching_servers(db, orders)
    items = [
        {
            **view,
            "customer": email,
            "matching_servers": matches[
                (order.cpu, order.ram_gb, order.disk_gb)
            ],
        }
        for view, (order, email) in zip(
            order_views(db, orders), result["rows"], strict=True
        )
    ]
    return {"items": items, "next_cursor": result["next_cursor"]}


# Enough choices for one select; more servers stay in the pool.
MATCHES_PER_ORDER = 20


def matching_servers(db: Db, orders: list[Order]) -> dict:
    """Available servers per resource spec, with one query for a page."""
    specs = {(order.cpu, order.ram_gb, order.disk_gb) for order in orders}
    matches = {spec: [] for spec in specs}
    if not specs:
        return matches
    ranked = (
        select(
            Server,
            func.row_number()
            .over(
                partition_by=(Server.cpu, Server.ram_gb, Server.disk_gb),
                order_by=(Server.name, Server.id),
            )
            .label("position"),
        )
        .where(
            Server.state == "available",
            tuple_(Server.cpu, Server.ram_gb, Server.disk_gb).in_(specs),
        )
        .subquery()
    )
    candidate = aliased(Server, ranked)
    for server in db.scalars(
        select(candidate)
        .where(ranked.c.position <= MATCHES_PER_ORDER)
        .order_by(candidate.name, candidate.id)
    ):
        matches[(server.cpu, server.ram_gb, server.disk_gb)].append(
            {
                "id": server.id,
                "name": server.name,
                "address": str(server.address),
            }
        )
    return matches


@router.post("/operator/orders/{order_id}/allocate", status_code=201)
def assign(order_id: int, data: AllocationInput, user: Operator, db: Db):
    return rental_view(db, allocate(db, user, order_id, data.server_id))


def server_view(server: Server) -> dict:
    return {
        "id": server.id,
        "name": server.name,
        "address": str(server.address),
        "cpu": server.cpu,
        "ram_gb": server.ram_gb,
        "disk_gb": server.disk_gb,
        "state": server.state,
    }


# Pool rows: each server with its held rental (at most one, enforced by
# uq_rental_held_server) and that rental's customer, in one query.
POOL_ROWS = (
    select(Server, Rental.id, Rental.status, Rental.expires_at, User.email)
    .outerjoin(
        Rental, (Rental.server_id == Server.id) & (Rental.status != "ended")
    )
    .outerjoin(Order, Order.id == Rental.order_id)
    .outerjoin(User, User.id == Order.customer_id)
)
NEEDS_ACTION = ("suspension_pending", "suspended")
POOL_FILTERS = {
    "all": None,
    "action": Rental.status.in_(NEEDS_ACTION),
    "available": Server.state == "available",
    "assigned": Rental.status == "active",
}


def pool_item(row) -> dict:
    server, rental_id, status, expires_at, customer = row
    return {
        **server_view(server),
        "rental_id": rental_id,
        "rental_status": status,
        "expires_at": expires_at,
        "customer": customer,
    }


@router.get("/operator/servers")
def server_pool(
    user: Operator,
    db: Db,
    page: PageParams,
    filter: Literal["all", "action", "available", "assigned"] = "all",
):
    query = POOL_ROWS
    if POOL_FILTERS[filter] is not None:
        query = query.where(POOL_FILTERS[filter])
    result = paginate(
        db,
        query,
        [Server.name, Server.id],
        page,
        descending=False,
        key=lambda row: (row[0].name, row[0].id),
    )
    return {
        "items": [pool_item(row) for row in result["rows"]],
        "next_cursor": result["next_cursor"],
    }


@router.get("/operator/servers/{server_id}")
def pool_server(server_id: int, user: Operator, db: Db):
    row = db.execute(POOL_ROWS.where(Server.id == server_id)).first()
    if not row:
        raise HTTPException(404, "Server not found")
    return pool_item(row)


@router.post("/operator/servers", status_code=201)
def add_server(data: ServerInput, user: Operator, db: Db):
    try:
        address = str(ip_address(data.address))
    except ValueError as error:
        raise HTTPException(422, "Enter a valid IP address") from error
    values = data.model_dump(exclude={"password", "address"})
    server = Server(
        **values,
        address=address,
        password_ciphertext=encrypt_password(data.password),
    )
    db.add(server)
    db.flush()
    record(db, user, "server_added", "server", server.id, server.name)
    return server_view(server)


@router.get("/operator/operations")
def operations(
    user: Operator,
    db: Db,
    page: PageParams,
    status: Literal["pending", "resolved"] = "pending",
):
    customer, resolver = aliased(User), aliased(User)
    query = (
        select(
            OperationRequest, Rental, Server, customer.email, resolver.email
        )
        .join(Rental, Rental.id == OperationRequest.rental_id)
        .join(Server, Server.id == Rental.server_id)
        .join(Order, Order.id == Rental.order_id)
        .join(customer, customer.id == Order.customer_id)
        .outerjoin(resolver, resolver.id == OperationRequest.resolved_by)
    )
    if status == "pending":
        # Oldest first: the customer who waited longest is served first.
        query = query.where(OperationRequest.status == "pending")
        columns, descending = [OperationRequest.created_at], False
    else:
        query = query.where(OperationRequest.status != "pending")
        columns, descending = [OperationRequest.resolved_at], True
    columns.append(OperationRequest.id)
    result = paginate(
        db,
        query,
        columns,
        page,
        descending=descending,
        key=lambda row: [getattr(row[0], column.key) for column in columns],
    )
    items = [
        {
            **operation_view(item),
            "server_name": server.name,
            "address": str(server.address),
            "customer": email,
            "power": rental.power,
            "expires_at": rental.expires_at,
            "resolved_by": resolved_by,
        }
        for item, rental, server, email, resolved_by in result["rows"]
    ]
    return {"items": items, "next_cursor": result["next_cursor"]}


@router.post("/operator/operations/{operation_id}/resolve")
def resolve(operation_id: int, data: ResolutionInput, user: Operator, db: Db):
    return operation_view(
        resolve_operation(db, user, operation_id, data.status, data.result)
    )


@router.post("/operator/expiry-scan")
def scan_expiry(user: Operator, db: Db):
    return {"flagged": flag_expired(db)}


@router.post("/operator/rentals/{rental_id}/suspend")
def suspend(rental_id: int, user: Operator, db: Db):
    rental, order = owned_rental(db, rental_id, user, lock=True)
    if rental.expires_at > now() or rental.status not in {
        "active",
        "suspension_pending",
    }:
        raise HTTPException(409, "This rental is not awaiting suspension")
    server = db.scalar(
        select(Server).where(Server.id == rental.server_id).with_for_update()
    )
    rental.status = "suspended"
    rental.power = "stopped"
    order.status = "expired"
    server.state = "suspended"
    for operation in db.scalars(
        select(OperationRequest)
        .where(
            OperationRequest.rental_id == rental.id,
            OperationRequest.status == "pending",
        )
        .with_for_update()
    ):
        operation.status = "rejected"
        operation.result = "Rental expired and was suspended"
        operation.resolved_by = user.id
        operation.resolved_at = now()
        record(
            db,
            user,
            "operation_resolved",
            "operation",
            operation.id,
            "Rejected during suspension",
        )
    record(db, user, "suspended", "rental", rental.id, "Access suspended")
    db.flush()
    return {"status": rental.status}


@router.post("/operator/rentals/{rental_id}/prepare")
def prepare(rental_id: int, data: PreparationInput, user: Operator, db: Db):
    rental, _ = owned_rental(db, rental_id, user, lock=True)
    if rental.status != "suspended":
        raise HTTPException(409, "Suspend the rental before preparation")
    server = db.scalar(
        select(Server).where(Server.id == rental.server_id).with_for_update()
    )
    if data.password == decrypt_password(server.password_ciphertext):
        raise HTTPException(
            409, "Set a new password before reusing the server"
        )
    server.password_ciphertext = encrypt_password(data.password)
    server.state = "available"
    rental.status = "ended"
    record(db, user, "prepared", "server", server.id, "Ready for allocation")
    db.flush()
    return server_view(server)


def accessible_ticket(
    db: Db, ticket_id: int, user: User, *, lock: bool = False
) -> Ticket:
    query = select(Ticket).where(Ticket.id == ticket_id)
    if user.role == "customer":
        query = query.where(Ticket.customer_id == user.id)
    if lock:
        query = query.with_for_update().execution_options(
            populate_existing=True
        )
    ticket = db.scalar(query)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


def ticket_view(db: Db, ticket: Ticket) -> dict:
    """One ticket with its whole conversation, for the ticket page."""
    messages = db.execute(
        select(TicketMessage, User)
        .join(User, User.id == TicketMessage.author_id)
        .where(TicketMessage.ticket_id == ticket.id)
        .order_by(TicketMessage.created_at, TicketMessage.id)
    )
    context = None
    if ticket.rental_id:
        rental = db.get(Rental, ticket.rental_id)
        server = db.get(Server, rental.server_id)
        context = {
            "name": server.name,
            "address": str(server.address),
            "status": rental.status,
            "expires_at": rental.expires_at,
        }
    customer = db.get(User, ticket.customer_id)
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "customer": customer.email,
        "status": ticket.status,
        "rental_id": ticket.rental_id,
        "created_at": ticket.created_at,
        "last_message_at": ticket.last_message_at,
        "awaiting_support": ticket.awaiting_support,
        "server": context,
        "messages": [
            {
                "author": author.role,
                "body": message.body,
                "created_at": message.created_at,
            }
            for message, author in messages
        ],
    }


# List rows show the start of the newest message only.
EXCERPT_LENGTH = 160
TicketFilter = Literal["all", "awaiting", "open", "in_progress", "closed"]


@router.get("/tickets")
def tickets(
    user: TicketUser, db: Db, page: PageParams, status: TicketFilter = "all"
):
    """Ticket summaries, newest conversation first, in one query per page."""
    customer, author = aliased(User), aliased(User)
    last = (
        select(
            author.role.label("author"),
            func.left(TicketMessage.body, EXCERPT_LENGTH).label("body"),
        )
        .join(author, author.id == TicketMessage.author_id)
        .where(TicketMessage.ticket_id == Ticket.id)
        .order_by(TicketMessage.created_at.desc(), TicketMessage.id.desc())
        .limit(1)
        .lateral("last_message")
    )
    query = (
        select(Ticket, customer.email, Server.name, last.c.author, last.c.body)
        .join(customer, customer.id == Ticket.customer_id)
        .outerjoin(Rental, Rental.id == Ticket.rental_id)
        .outerjoin(Server, Server.id == Rental.server_id)
        .outerjoin(last, true())
    )
    if user.role == "customer":
        query = query.where(Ticket.customer_id == user.id)
    if status == "awaiting":
        query = query.where(Ticket.awaiting_support, Ticket.status != "closed")
    elif status != "all":
        query = query.where(Ticket.status == status)
    result = paginate(
        db,
        query,
        [Ticket.last_message_at, Ticket.id],
        page,
        descending=True,
        key=lambda row: (row[0].last_message_at, row[0].id),
    )
    items = [
        {
            "id": ticket.id,
            "subject": ticket.subject,
            "status": ticket.status,
            "customer": email,
            "rental_id": ticket.rental_id,
            "server_name": server_name,
            "created_at": ticket.created_at,
            "last_message_at": ticket.last_message_at,
            "awaiting_support": ticket.awaiting_support,
            "last_message": {"author": last_author, "body": excerpt},
        }
        for ticket, email, server_name, last_author, excerpt in result["rows"]
    ]
    return {"items": items, "next_cursor": result["next_cursor"]}


@router.post("/tickets", status_code=201)
def open_ticket(data: TicketInput, user: Customer, db: Db):
    if data.rental_id:
        owned_rental(db, data.rental_id, user)
    ticket = Ticket(
        subject=data.subject, customer_id=user.id, rental_id=data.rental_id
    )
    db.add(ticket)
    db.flush()
    db.add(
        TicketMessage(ticket_id=ticket.id, author_id=user.id, body=data.body)
    )
    record(db, user, "ticket_created", "ticket", ticket.id, ticket.status)
    db.flush()
    return ticket_view(db, ticket)


@router.get("/tickets/{ticket_id}")
def ticket_details(ticket_id: int, user: TicketUser, db: Db):
    return ticket_view(db, accessible_ticket(db, ticket_id, user))


@router.post("/tickets/{ticket_id}/messages", status_code=201)
def reply(ticket_id: int, data: MessageInput, user: TicketUser, db: Db):
    ticket = accessible_ticket(db, ticket_id, user, lock=True)
    if ticket.status == "closed":
        raise HTTPException(409, "This ticket is closed")
    db.add(
        TicketMessage(ticket_id=ticket.id, author_id=user.id, body=data.body)
    )
    # Same transaction time as the message's created_at.
    ticket.last_message_at = func.now()
    ticket.awaiting_support = user.role == "customer"
    record(
        db,
        user,
        "ticket_reply",
        "ticket",
        ticket.id,
        f"{user.role.capitalize()} replied",
    )
    if user.role == "support" and ticket.status == "open":
        ticket.status = "in_progress"
        record(db, user, "ticket_status", "ticket", ticket.id, ticket.status)
    db.flush()
    return ticket_view(db, ticket)


@router.post("/tickets/{ticket_id}/status")
def change_ticket_status(
    ticket_id: int, data: TicketStatusInput, user: Support, db: Db
):
    ticket = accessible_ticket(db, ticket_id, user, lock=True)
    if ticket.status != data.status:
        ticket.status = data.status
        record(db, user, "ticket_status", "ticket", ticket.id, data.status)
    db.flush()
    return ticket_view(db, ticket)


# History filters: support narrows by action (optionally `action:result`),
# other staff by entity type; values outside the role's scope are rejected.
SUPPORT_ACTIONS = ("ticket_created", "ticket_reply", "ticket_status")


@router.get("/activity")
def activity(
    user: StaffHistory,
    db: Db,
    page: PageParams,
    filter: str = Query("all", max_length=64),
):
    query = (
        select(Activity, User.email)
        .outerjoin(User, User.id == Activity.actor_id)
        .where(Activity.entity_type.in_(ACTIVITY_SCOPES[user.role]))
    )
    if filter != "all":
        value, _, result = filter.partition(":")
        if user.role == "support":
            column, allowed = Activity.action, SUPPORT_ACTIONS
        else:
            column, allowed = Activity.entity_type, ACTIVITY_SCOPES[user.role]
        if value not in allowed:
            raise HTTPException(422, "Unknown history filter")
        query = query.where(column == value)
        if result:
            query = query.where(Activity.result == result)
    page_rows = paginate(
        db,
        query,
        [Activity.created_at, Activity.id],
        page,
        descending=True,
        key=lambda row: (row[0].created_at, row[0].id),
    )
    items = [
        {
            "id": item.id,
            "actor": email or "System",
            "action": item.action,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "result": item.result,
            "created_at": item.created_at,
        }
        for item, email in page_rows["rows"]
    ]
    return {"items": items, "next_cursor": page_rows["next_cursor"]}


@router.get("/counts")
def counts(user: CurrentUser, db: Db):
    """Work waiting for staff, for menu and filter badges."""
    if user.role == "support":
        by_status = dict(
            db.execute(
                select(Ticket.status, func.count()).group_by(Ticket.status)
            ).all()
        )
        awaiting = db.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.awaiting_support, Ticket.status != "closed")
        )
        statuses = ("open", "in_progress", "closed")
        return {
            "tickets": {
                "all": sum(by_status.values()),
                "awaiting": awaiting,
                **{status: by_status.get(status, 0) for status in statuses},
            }
        }
    if user.role == "operator":
        held = dict(
            db.execute(
                select(Rental.status, func.count())
                .where(Rental.status != "ended")
                .group_by(Rental.status)
            ).all()
        )
        servers = dict(
            db.execute(
                select(Server.state, func.count()).group_by(Server.state)
            ).all()
        )
        return {
            "queue": db.scalar(
                select(func.count())
                .select_from(Order)
                .where(Order.status == "awaiting_allocation")
            ),
            "pool": {
                "all": sum(servers.values()),
                "action": sum(held.get(status, 0) for status in NEEDS_ACTION),
                "available": servers.get("available", 0),
                "assigned": held.get("active", 0),
            },
            "operations": {
                "pending": db.scalar(
                    select(func.count())
                    .select_from(OperationRequest)
                    .where(OperationRequest.status == "pending")
                )
            },
        }
    return {}
