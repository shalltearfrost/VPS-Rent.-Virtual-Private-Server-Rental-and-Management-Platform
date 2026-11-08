import secrets
from datetime import timedelta
from ipaddress import ip_address
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select, text

from app.config import get_settings
from app.models import (
    Activity,
    Invoice,
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
from app.presenters import (
    invoice_view,
    operation_view,
    order_view,
    plan_view,
    rental_view,
)
from app.schemas import (
    AllocationInput,
    Credentials,
    MessageInput,
    OperationInput,
    OrderInput,
    PaymentInput,
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
    pay_invoice,
    record,
    renewal_invoice,
    request_operation,
    require_active,
    resolve_operation,
)

router = APIRouter(prefix="/api")
TicketUser = Annotated[User, Depends(require_role("customer", "support"))]
StaffHistory = Annotated[User, Depends(require_role("operator", "support"))]


def user_view(user: User) -> dict:
    return {"id": user.id, "email": user.email, "role": user.role}


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
    valid = password_hasher.verify(
        data.password, user.password_hash if user else dummy_hash
    )
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
    return [
        order_view(db, item)
        for item in db.scalars(
            select(Order)
            .where(Order.customer_id == user.id)
            .order_by(Order.id.desc())
        )
    ]


@router.post("/orders", status_code=201)
def place_order(data: OrderInput, user: Customer, db: Db):
    return order_view(db, create_order(db, user, data.plan_id, data.term))


@router.get("/orders/{order_id}")
def order_details(order_id: int, user: Customer, db: Db):
    return order_view(db, owned_order(db, order_id, user))


@router.get("/invoices/{invoice_id}")
def invoice_details(invoice_id: int, user: Customer, db: Db):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    owned_order(db, invoice.order_id, user)
    return invoice_view(invoice)


@router.post("/invoices/{invoice_id}/test-payment")
def payment(invoice_id: int, data: PaymentInput, user: Customer, db: Db):
    result = pay_invoice(db, user, invoice_id, data)
    return {
        "id": result.id,
        "invoice_id": result.invoice_id,
        "outcome": result.outcome,
    }


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


@router.post("/rentals/{rental_id}/renewal-invoice")
def renew(rental_id: int, user: Customer, db: Db):
    return invoice_view(renewal_invoice(db, user, rental_id))


@router.post("/rentals/{rental_id}/operations", status_code=201)
def request_action(
    rental_id: int, data: OperationInput, user: Customer, db: Db
):
    return operation_view(request_operation(db, user, rental_id, data.kind))


@router.get("/operator/queue")
def queue(user: Operator, db: Db):
    return [
        order_view(db, item)
        for item in db.scalars(
            select(Order)
            .where(Order.status == "awaiting_allocation")
            .order_by(Order.created_at)
        )
    ]


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


@router.get("/operator/servers")
def server_pool(user: Operator, db: Db):
    result = []
    for server in db.scalars(select(Server).order_by(Server.id)):
        item = server_view(server)
        rental = db.scalar(
            select(Rental).where(
                Rental.server_id == server.id, Rental.status != "ended"
            )
        )
        item["rental_id"] = rental.id if rental else None
        item["rental_status"] = rental.status if rental else None
        result.append(item)
    return result


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
def operations(user: Operator, db: Db):
    result = []
    for item in db.scalars(
        select(OperationRequest).order_by(OperationRequest.created_at.desc())
    ):
        rental = db.get(Rental, item.rental_id)
        result.append(
            {
                **operation_view(item),
                "server_name": db.get(Server, rental.server_id).name,
            }
        )
    return result


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


def accessible_ticket(db: Db, ticket_id: int, user: User) -> Ticket:
    query = select(Ticket).where(Ticket.id == ticket_id)
    if user.role == "customer":
        query = query.where(Ticket.customer_id == user.id)
    ticket = db.scalar(query)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


def ticket_view(db: Db, ticket: Ticket) -> dict:
    messages = db.execute(
        select(TicketMessage, User)
        .join(User, User.id == TicketMessage.author_id)
        .where(TicketMessage.ticket_id == ticket.id)
        .order_by(TicketMessage.id)
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
    return {
        "id": ticket.id,
        "subject": ticket.subject,
        "status": ticket.status,
        "rental_id": ticket.rental_id,
        "created_at": ticket.created_at,
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


@router.get("/tickets")
def tickets(user: TicketUser, db: Db):
    query = select(Ticket).order_by(Ticket.id.desc())
    if user.role == "customer":
        query = query.where(Ticket.customer_id == user.id)
    return [ticket_view(db, ticket) for ticket in db.scalars(query)]


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
    record(db, user, "ticket_created", "ticket", ticket.id, "Open")
    db.flush()
    return ticket_view(db, ticket)


@router.get("/tickets/{ticket_id}")
def ticket_details(ticket_id: int, user: TicketUser, db: Db):
    return ticket_view(db, accessible_ticket(db, ticket_id, user))


@router.post("/tickets/{ticket_id}/messages", status_code=201)
def reply(ticket_id: int, data: MessageInput, user: TicketUser, db: Db):
    ticket = accessible_ticket(db, ticket_id, user)
    if ticket.status == "closed":
        raise HTTPException(409, "This ticket is closed")
    db.add(
        TicketMessage(ticket_id=ticket.id, author_id=user.id, body=data.body)
    )
    db.flush()
    return ticket_view(db, ticket)


@router.post("/tickets/{ticket_id}/status")
def change_ticket_status(
    ticket_id: int, data: TicketStatusInput, user: Support, db: Db
):
    ticket = accessible_ticket(db, ticket_id, user)
    if ticket.status != data.status:
        ticket.status = data.status
        record(db, user, "ticket_status", "ticket", ticket.id, data.status)
    db.flush()
    return ticket_view(db, ticket)


@router.get("/activity")
def activity(user: StaffHistory, db: Db):
    query = (
        select(Activity, User.email)
        .outerjoin(User, User.id == Activity.actor_id)
        .order_by(Activity.created_at.desc(), Activity.id.desc())
        .limit(200)
    )
    if user.role == "support":
        query = query.where(Activity.entity_type == "ticket")
    else:
        query = query.where(
            Activity.entity_type.in_(
                ["order", "rental", "server", "operation"]
            )
        )
    return [
        {
            "id": item.id,
            "actor": email or "System",
            "action": item.action,
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "result": item.result,
            "created_at": item.created_at,
        }
        for item, email in db.execute(query)
    ]
