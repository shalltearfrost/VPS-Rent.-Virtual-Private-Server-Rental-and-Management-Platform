BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> e266e9761931

CREATE TABLE plans (
    name VARCHAR(40) NOT NULL,
    description VARCHAR(160) NOT NULL,
    cpu INTEGER NOT NULL,
    ram_gb INTEGER NOT NULL,
    disk_gb INTEGER NOT NULL,
    monthly_cents INTEGER NOT NULL,
    annual_cents INTEGER NOT NULL,
    enabled BOOLEAN NOT NULL,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT plan_resources_positive CHECK (cpu > 0 AND ram_gb > 0 AND disk_gb > 0),
    CONSTRAINT plan_prices_positive CHECK (monthly_cents > 0 AND annual_cents > 0),
    UNIQUE (name)
);

CREATE TABLE servers (
    name VARCHAR(40) NOT NULL,
    address INET NOT NULL,
    cpu INTEGER NOT NULL,
    ram_gb INTEGER NOT NULL,
    disk_gb INTEGER NOT NULL,
    ssh_user VARCHAR(32) NOT NULL,
    password_ciphertext TEXT NOT NULL,
    state VARCHAR(16) NOT NULL,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT server_state CHECK (state IN ('available', 'assigned', 'suspended', 'preparing')),
    CONSTRAINT server_resources_positive CHECK (cpu > 0 AND ram_gb > 0 AND disk_gb > 0),
    UNIQUE (address),
    UNIQUE (name)
);

CREATE INDEX ix_servers_available ON servers (state, cpu, ram_gb, disk_gb);

CREATE TABLE users (
    email VARCHAR(254) NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(16) NOT NULL,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT user_role CHECK (role IN ('customer', 'operator', 'support', 'manager')),
    CONSTRAINT email_lowercase CHECK (email = lower(email)),
    UNIQUE (email)
);

CREATE TABLE activity (
    actor_id BIGINT,
    action VARCHAR(64) NOT NULL,
    entity_type VARCHAR(32) NOT NULL,
    entity_id BIGINT NOT NULL,
    result TEXT NOT NULL,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(actor_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE INDEX ix_activity_actor_id ON activity (actor_id);

CREATE INDEX ix_activity_time ON activity (created_at);

CREATE TABLE orders (
    customer_id BIGINT NOT NULL,
    plan_id BIGINT NOT NULL,
    plan_name VARCHAR(40) NOT NULL,
    cpu INTEGER NOT NULL,
    ram_gb INTEGER NOT NULL,
    disk_gb INTEGER NOT NULL,
    price_cents INTEGER NOT NULL,
    renewal_cents INTEGER NOT NULL,
    term VARCHAR(16) NOT NULL,
    status VARCHAR(24) NOT NULL,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT order_status CHECK (status IN ('awaiting_payment', 'awaiting_allocation', 'active', 'expired')),
    CONSTRAINT order_term CHECK (term IN ('monthly', 'annual')),
    CONSTRAINT order_snapshot_positive CHECK (cpu > 0 AND ram_gb > 0 AND disk_gb > 0 AND price_cents > 0 AND renewal_cents > 0),
    FOREIGN KEY(customer_id) REFERENCES users (id) ON DELETE RESTRICT,
    FOREIGN KEY(plan_id) REFERENCES plans (id) ON DELETE RESTRICT
);

CREATE INDEX ix_orders_customer_created ON orders (customer_id, created_at);

CREATE INDEX ix_orders_customer_id ON orders (customer_id);

CREATE INDEX ix_orders_plan_id ON orders (plan_id);

CREATE INDEX ix_orders_queue ON orders (status, created_at);

CREATE TABLE sessions (
    user_id BIGINT NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    csrf_token VARCHAR(64) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    id BIGSERIAL NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE,
    UNIQUE (token_hash)
);

CREATE INDEX ix_sessions_expires_at ON sessions (expires_at);

CREATE INDEX ix_sessions_user_id ON sessions (user_id);

CREATE TABLE rentals (
    order_id BIGINT NOT NULL,
    server_id BIGINT NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(24) NOT NULL,
    power VARCHAR(16) NOT NULL,
    id BIGSERIAL NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT rental_power CHECK (power IN ('running', 'stopped')),
    CONSTRAINT rental_status CHECK (status IN ('active', 'suspension_pending', 'suspended', 'ended')),
    CONSTRAINT rental_period CHECK (expires_at > started_at),
    FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE RESTRICT,
    FOREIGN KEY(server_id) REFERENCES servers (id) ON DELETE RESTRICT,
    UNIQUE (order_id)
);

CREATE INDEX ix_rentals_expiry ON rentals (status, expires_at);

CREATE INDEX ix_rentals_server_id ON rentals (server_id);

CREATE UNIQUE INDEX uq_rental_held_server ON rentals (server_id) WHERE status <> 'ended';

CREATE TABLE invoices (
    order_id BIGINT NOT NULL,
    rental_id BIGINT,
    kind VARCHAR(16) NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency VARCHAR(3) NOT NULL,
    status VARCHAR(16) NOT NULL,
    paid_at TIMESTAMP WITH TIME ZONE,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT invoice_kind CHECK ((kind = 'initial' AND rental_id IS NULL) OR (kind = 'renewal' AND rental_id IS NOT NULL)),
    CONSTRAINT invoice_paid_at CHECK ((status = 'paid') = (paid_at IS NOT NULL)),
    CONSTRAINT invoice_currency CHECK (currency = 'EUR'),
    CONSTRAINT invoice_status CHECK (status IN ('unpaid', 'paid')),
    CONSTRAINT invoice_amount CHECK (amount_cents > 0),
    FOREIGN KEY(order_id) REFERENCES orders (id) ON DELETE RESTRICT,
    FOREIGN KEY(rental_id) REFERENCES rentals (id) ON DELETE RESTRICT
);

CREATE INDEX ix_invoices_order_id ON invoices (order_id);

CREATE INDEX ix_invoices_rental_id ON invoices (rental_id);

CREATE UNIQUE INDEX uq_initial_invoice ON invoices (order_id) WHERE kind = 'initial';

CREATE UNIQUE INDEX uq_open_renewal ON invoices (rental_id) WHERE kind = 'renewal' AND status = 'unpaid';

CREATE TABLE operation_requests (
    rental_id BIGINT NOT NULL,
    requested_by BIGINT NOT NULL,
    kind VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    result TEXT,
    resolved_by BIGINT,
    resolved_at TIMESTAMP WITH TIME ZONE,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT operation_resolution CHECK ((status = 'pending' AND resolved_by IS NULL AND resolved_at IS NULL AND result IS NULL) OR (status <> 'pending' AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL AND length(trim(result)) > 0 AND result IS NOT NULL)),
    CONSTRAINT operation_kind CHECK (kind IN ('start', 'stop', 'restart')),
    CONSTRAINT operation_status CHECK (status IN ('pending', 'completed', 'rejected')),
    FOREIGN KEY(rental_id) REFERENCES rentals (id) ON DELETE RESTRICT,
    FOREIGN KEY(requested_by) REFERENCES users (id) ON DELETE RESTRICT,
    FOREIGN KEY(resolved_by) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE INDEX ix_operation_requests_rental_id ON operation_requests (rental_id);

CREATE INDEX ix_operation_requests_requested_by ON operation_requests (requested_by);

CREATE INDEX ix_operation_requests_resolved_by ON operation_requests (resolved_by);

CREATE UNIQUE INDEX uq_pending_operation ON operation_requests (rental_id) WHERE status = 'pending';

CREATE TABLE tickets (
    customer_id BIGINT NOT NULL,
    rental_id BIGINT,
    subject VARCHAR(160) NOT NULL,
    status VARCHAR(16) NOT NULL,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ticket_status CHECK (status IN ('open', 'in_progress', 'closed')),
    FOREIGN KEY(customer_id) REFERENCES users (id) ON DELETE RESTRICT,
    FOREIGN KEY(rental_id) REFERENCES rentals (id) ON DELETE RESTRICT
);

CREATE INDEX ix_tickets_customer_id ON tickets (customer_id);

CREATE INDEX ix_tickets_queue ON tickets (status, created_at);

CREATE INDEX ix_tickets_rental_id ON tickets (rental_id);

CREATE TABLE payments (
    invoice_id BIGINT NOT NULL,
    customer_id BIGINT NOT NULL,
    idempotency_key VARCHAR(64) NOT NULL,
    outcome VARCHAR(16) NOT NULL,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT payment_outcome CHECK (outcome IN ('succeeded', 'failed')),
    FOREIGN KEY(customer_id) REFERENCES users (id) ON DELETE RESTRICT,
    FOREIGN KEY(invoice_id) REFERENCES invoices (id) ON DELETE RESTRICT,
    UNIQUE (idempotency_key)
);

CREATE INDEX ix_payments_customer_id ON payments (customer_id);

CREATE INDEX ix_payments_invoice_id ON payments (invoice_id);

CREATE UNIQUE INDEX uq_successful_payment ON payments (invoice_id) WHERE outcome = 'succeeded';

CREATE TABLE ticket_messages (
    ticket_id BIGINT NOT NULL,
    author_id BIGINT NOT NULL,
    body TEXT NOT NULL,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT message_body CHECK (length(trim(body)) > 0),
    FOREIGN KEY(author_id) REFERENCES users (id) ON DELETE RESTRICT,
    FOREIGN KEY(ticket_id) REFERENCES tickets (id) ON DELETE RESTRICT
);

CREATE INDEX ix_messages_thread ON ticket_messages (ticket_id, created_at);

CREATE INDEX ix_ticket_messages_author_id ON ticket_messages (author_id);

CREATE INDEX ix_ticket_messages_ticket_id ON ticket_messages (ticket_id);

INSERT INTO alembic_version (version_num) VALUES ('e266e9761931') RETURNING alembic_version.version_num;

COMMIT;
