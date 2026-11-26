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

-- Running upgrade e266e9761931 -> 7c1d2a9f4b10

CREATE TABLE payment_cards (
    customer_id BIGINT NOT NULL,
    token_ciphertext TEXT NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    masked_pan VARCHAR(32) NOT NULL,
    removed_at TIMESTAMP WITH TIME ZONE,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(customer_id) REFERENCES users (id) ON DELETE RESTRICT
);

CREATE INDEX ix_payment_cards_customer_id ON payment_cards (customer_id);

CREATE UNIQUE INDEX uq_active_card_token ON payment_cards (token_hash) WHERE removed_at IS NULL;

ALTER TABLE rentals ADD COLUMN auto_renew_card_id BIGINT;

ALTER TABLE rentals ADD CONSTRAINT rentals_auto_renew_card_id_fkey FOREIGN KEY(auto_renew_card_id) REFERENCES payment_cards (id) ON DELETE RESTRICT;

CREATE INDEX ix_rentals_auto_renew_card_id ON rentals (auto_renew_card_id);

DROP INDEX uq_successful_payment;

ALTER TABLE payments DROP CONSTRAINT payment_outcome;

ALTER TABLE payments RENAME outcome TO status;

ALTER TABLE payments ADD COLUMN provider VARCHAR(16) DEFAULT 'test' NOT NULL;

ALTER TABLE payments ADD COLUMN initiated_by VARCHAR(16) DEFAULT 'customer' NOT NULL;

ALTER TABLE payments ADD COLUMN provider_invoice_id VARCHAR(64);

ALTER TABLE payments ADD COLUMN page_url TEXT;

ALTER TABLE payments ADD COLUMN save_card BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE payments ADD COLUMN card_id BIGINT;

ALTER TABLE payments ADD COLUMN failure_reason TEXT;

ALTER TABLE payments ADD COLUMN provider_modified_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE payments ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL;

ALTER TABLE payments ALTER COLUMN provider DROP DEFAULT;

ALTER TABLE payments ALTER COLUMN initiated_by DROP DEFAULT;

ALTER TABLE payments ALTER COLUMN save_card DROP DEFAULT;

ALTER TABLE payments ADD CONSTRAINT payment_status CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded'));

ALTER TABLE payments ADD CONSTRAINT payment_provider CHECK (provider IN ('test', 'monobank'));

ALTER TABLE payments ADD CONSTRAINT payment_initiator CHECK (initiated_by IN ('customer', 'auto'));

ALTER TABLE payments ADD CONSTRAINT payment_provider_details CHECK (provider = 'test' OR provider_invoice_id IS NOT NULL OR status = 'failed');

ALTER TABLE payments ADD CONSTRAINT payments_provider_invoice_id_key UNIQUE (provider_invoice_id);

ALTER TABLE payments ADD CONSTRAINT payments_card_id_fkey FOREIGN KEY(card_id) REFERENCES payment_cards (id) ON DELETE RESTRICT;

CREATE INDEX ix_payments_card_id ON payments (card_id);

CREATE INDEX ix_payments_status ON payments (status, updated_at);

CREATE UNIQUE INDEX uq_successful_payment ON payments (invoice_id) WHERE status = 'succeeded';

CREATE UNIQUE INDEX uq_pending_payment ON payments (invoice_id) WHERE status = 'pending';

UPDATE alembic_version SET version_num='7c1d2a9f4b10' WHERE alembic_version.version_num = 'e266e9761931';

-- Running upgrade 7c1d2a9f4b10 -> 9a82d7d0d151

ALTER TABLE payments ADD COLUMN reference VARCHAR(64);

ALTER TABLE payments ADD COLUMN charge_amount BIGINT;

ALTER TABLE payments ADD COLUMN charge_currency VARCHAR(3);

ALTER TABLE payments ADD COLUMN review_required BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE payments ADD COLUMN refund_reference VARCHAR(64);

ALTER TABLE payments ADD COLUMN refund_started_at TIMESTAMP WITH TIME ZONE;

ALTER TABLE payments ALTER COLUMN review_required DROP DEFAULT;

ALTER TABLE payments ADD CONSTRAINT payments_reference_key UNIQUE (reference);

ALTER TABLE payments ADD CONSTRAINT payments_refund_reference_key UNIQUE (refund_reference);

UPDATE payments SET charge_amount = invoices.amount_cents, charge_currency = invoices.currency FROM invoices WHERE payments.invoice_id = invoices.id;

ALTER TABLE payments DROP CONSTRAINT payment_status;

ALTER TABLE payments DROP CONSTRAINT payment_provider_details;

ALTER TABLE payments ADD CONSTRAINT payment_status CHECK (status IN ('reserved', 'uncertain', 'pending', 'refund_pending', 'succeeded', 'failed', 'refunded'));

ALTER TABLE payments ADD CONSTRAINT payment_provider_details CHECK (provider = 'test' OR provider_invoice_id IS NOT NULL OR status IN ('reserved', 'uncertain', 'failed'));

ALTER TABLE payments ADD CONSTRAINT payment_charge_quote CHECK ((charge_amount IS NULL AND charge_currency IS NULL) OR (charge_amount > 0 AND charge_amount IS NOT NULL AND charge_currency IN ('EUR', 'USD', 'UAH') AND charge_currency IS NOT NULL));

DROP INDEX uq_pending_payment;

CREATE UNIQUE INDEX uq_pending_payment ON payments (invoice_id) WHERE status IN ('reserved', 'uncertain', 'pending', 'refund_pending');

UPDATE alembic_version SET version_num='9a82d7d0d151' WHERE alembic_version.version_num = '7c1d2a9f4b10';

-- Running upgrade 7c1d2a9f4b10 -> b3f8e1c2d4a5

ALTER TABLE tickets ADD COLUMN last_message_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL;

ALTER TABLE tickets ADD COLUMN awaiting_support BOOLEAN DEFAULT true NOT NULL;

UPDATE tickets AS t
        SET last_message_at = last.created_at,
            awaiting_support = last.role = 'customer'
        FROM (
            SELECT DISTINCT ON (m.ticket_id)
                m.ticket_id, m.created_at, u.role
            FROM ticket_messages AS m
            JOIN users AS u ON u.id = m.author_id
            ORDER BY m.ticket_id, m.created_at DESC, m.id DESC
        ) AS last
        WHERE last.ticket_id = t.id;

DROP INDEX ix_tickets_queue;

DROP INDEX ix_tickets_customer_id;

CREATE INDEX ix_tickets_customer_recent ON tickets (customer_id, last_message_at, id);

CREATE INDEX ix_tickets_status_recent ON tickets (status, last_message_at, id);

CREATE INDEX ix_tickets_recent ON tickets (last_message_at, id);

CREATE INDEX ix_tickets_awaiting ON tickets (last_message_at, id) WHERE awaiting_support AND status <> 'closed';

DROP INDEX ix_messages_thread;

DROP INDEX ix_ticket_messages_ticket_id;

CREATE INDEX ix_messages_thread ON ticket_messages (ticket_id, created_at, id);

DROP INDEX ix_activity_time;

CREATE INDEX ix_activity_time ON activity (created_at, id);

CREATE INDEX ix_activity_scope ON activity (entity_type, created_at, id);

CREATE INDEX ix_activity_action ON activity (entity_type, action, created_at, id);

DROP INDEX ix_orders_customer_id;

CREATE INDEX ix_operations_pending ON operation_requests (created_at, id) WHERE status = 'pending';

CREATE INDEX ix_operations_resolved ON operation_requests (resolved_at, id) WHERE status <> 'pending';

INSERT INTO alembic_version (version_num) VALUES ('b3f8e1c2d4a5') RETURNING alembic_version.version_num;

-- Running upgrade b3f8e1c2d4a5 -> c4a7d2e9f1b6

ALTER TABLE users ADD COLUMN google_sub VARCHAR(255);

ALTER TABLE users ADD CONSTRAINT users_google_sub_key UNIQUE (google_sub);

ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;

ALTER TABLE users ADD CONSTRAINT user_has_credential CHECK (password_hash IS NOT NULL OR google_sub IS NOT NULL);

UPDATE alembic_version SET version_num='c4a7d2e9f1b6' WHERE alembic_version.version_num = 'b3f8e1c2d4a5';

-- Running upgrade e266e9761931 -> 770df647333b

CREATE TABLE monobank_checkouts (
    invoice_id BIGINT NOT NULL,
    payment_id BIGINT,
    reference VARCHAR(64) NOT NULL,
    provider_invoice_id VARCHAR(64) NOT NULL,
    payment_url TEXT NOT NULL,
    status VARCHAR(16) NOT NULL,
    modified_at TIMESTAMP WITH TIME ZONE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    review_required BOOLEAN NOT NULL,
    id BIGSERIAL NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT monobank_checkout_status CHECK (status IN ('created', 'processing', 'hold', 'success', 'failure', 'expired', 'reversed')),
    FOREIGN KEY(invoice_id) REFERENCES invoices (id) ON DELETE RESTRICT,
    FOREIGN KEY(payment_id) REFERENCES payments (id) ON DELETE RESTRICT,
    UNIQUE (payment_id),
    UNIQUE (provider_invoice_id),
    UNIQUE (reference)
);

CREATE INDEX ix_monobank_checkouts_invoice_id ON monobank_checkouts (invoice_id);

CREATE UNIQUE INDEX uq_monobank_pending_invoice ON monobank_checkouts (invoice_id) WHERE status IN ('created', 'processing', 'hold');

INSERT INTO alembic_version (version_num) VALUES ('770df647333b') RETURNING alembic_version.version_num;

-- Running upgrade 770df647333b -> 19364610a068

ALTER TABLE monobank_checkouts ADD COLUMN amount_kopecks BIGINT;

ALTER TABLE monobank_checkouts ADD COLUMN eur_uah_rate NUMERIC(12, 6);

ALTER TABLE monobank_checkouts ADD CONSTRAINT monobank_checkout_quote CHECK ((amount_kopecks IS NULL AND eur_uah_rate IS NULL) OR (amount_kopecks IS NOT NULL AND amount_kopecks > 0 AND eur_uah_rate IS NOT NULL AND eur_uah_rate > 0));

UPDATE alembic_version SET version_num='19364610a068' WHERE alembic_version.version_num = '770df647333b';

-- Running upgrade 19364610a068, 9a82d7d0d151 -> b8109fd1b2aa

UPDATE payments AS p SET provider = 'monobank', provider_invoice_id = c.provider_invoice_id, reference = c.reference, page_url = c.payment_url, charge_amount = c.amount_kopecks, charge_currency = CASE WHEN c.amount_kopecks IS NOT NULL THEN 'UAH' ELSE NULL END, review_required = c.review_required OR c.amount_kopecks IS NULL, provider_modified_at = c.modified_at FROM monobank_checkouts AS c WHERE c.payment_id = p.id;

INSERT INTO payments (invoice_id, customer_id, idempotency_key, status, provider, initiated_by, provider_invoice_id, page_url, save_card, reference, charge_amount, charge_currency, review_required, created_at, updated_at) SELECT c.invoice_id, o.customer_id, 'legacy-checkout-' || c.id, CASE WHEN c.status = 'success' OR c.amount_kopecks IS NULL THEN 'uncertain' ELSE 'pending' END, 'monobank', 'customer', c.provider_invoice_id, c.payment_url, false, c.reference, c.amount_kopecks, CASE WHEN c.amount_kopecks IS NOT NULL THEN 'UAH' ELSE NULL END, c.review_required OR c.amount_kopecks IS NULL OR c.status = 'success', c.created_at, now() FROM monobank_checkouts AS c JOIN invoices AS i ON i.id = c.invoice_id JOIN orders AS o ON o.id = i.order_id WHERE c.payment_id IS NULL AND c.status IN ('created', 'processing', 'hold', 'success') AND NOT EXISTS (SELECT 1 FROM payments AS p WHERE p.provider_invoice_id = c.provider_invoice_id);

UPDATE monobank_checkouts AS c SET payment_id = p.id FROM payments AS p WHERE c.payment_id IS NULL AND p.provider_invoice_id = c.provider_invoice_id;

DELETE FROM alembic_version WHERE alembic_version.version_num = '19364610a068';

UPDATE alembic_version SET version_num='b8109fd1b2aa' WHERE alembic_version.version_num = '9a82d7d0d151';

-- Running upgrade b8109fd1b2aa, c4a7d2e9f1b6 -> da8f0c21e37b

DELETE FROM alembic_version WHERE alembic_version.version_num = 'b8109fd1b2aa';

UPDATE alembic_version SET version_num='da8f0c21e37b' WHERE alembic_version.version_num = 'c4a7d2e9f1b6';

-- Running upgrade da8f0c21e37b -> ebc4d38098b1

ALTER TABLE sessions ADD COLUMN authenticated_at TIMESTAMP WITH TIME ZONE;

UPDATE alembic_version SET version_num='ebc4d38098b1' WHERE alembic_version.version_num = 'da8f0c21e37b';

COMMIT;
