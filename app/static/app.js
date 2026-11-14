(() => {
  'use strict';

  const root = document.getElementById('vps-rent-app');
  const main = root.querySelector('.vr-main');
  const nav = root.querySelector('.vr-nav');
  const feedback = root.querySelector('.vr-feedback');
  const state = {
    user: null, csrf: '', plans: [], orders: [], rentals: [], tickets: [],
    queue: [], pool: [], operations: [], activity: [], managedPlans: [],
    cards: [], invoice: null, saveCard: false,
    selectedPlan: null, term: 'monthly', openOrders: new Set(), loading: false,
  };
  let invoiceTimer = null;
  const menus = {
    visitor: [['plans', 'Plans'], ['login', 'Sign in']],
    customer: [['plans', 'Plans'], ['orders', 'Orders'],
      ['servers', 'My servers'], ['tickets', 'Support']],
    operator: [['queue', 'Allocation'], ['pool', 'Server pool'],
      ['operations', 'Operations'], ['history', 'History']],
    support: [['tickets', 'Tickets'], ['history', 'History']],
    manager: [['manage', 'Rental plans']],
  };
  const labels = {
    awaiting_payment: 'Awaiting Payment',
    awaiting_allocation: 'Waiting for allocation',
    suspension_pending: 'Awaiting suspension', in_progress: 'In Progress',
    active: 'Active', available: 'Available', assigned: 'Assigned',
    expired: 'Expired', suspended: 'Suspended', ended: 'Ended',
    running: 'Running', stopped: 'Stopped', pending: 'Pending',
    completed: 'Completed', rejected: 'Rejected', paid: 'Paid', unpaid: 'Unpaid',
    open: 'Open', closed: 'Closed', failed: 'Failed', preparing: 'Preparing',
    succeeded: 'Succeeded', refunded: 'Refunded',
  };
  const tones = {
    paid: 'good', active: 'good', running: 'good', completed: 'good',
    available: 'good', succeeded: 'good', refunded: 'bad',
    failed: 'bad', expired: 'bad', stopped: 'bad',
    rejected: 'bad', awaiting_payment: 'warn', awaiting_allocation: 'warn',
    pending: 'warn', suspension_pending: 'warn', suspended: 'warn',
  };
  const safe = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  const money = cents => new Intl.NumberFormat('en-IE', {
    style: 'currency', currency: 'EUR',
  }).format(cents / 100);
  const date = value => new Intl.DateTimeFormat('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
  }).format(new Date(value));
  const duration = term => term === 'annual' ? '12 months' : '30 days';
  const badge = status => `<span class="vr-badge vr-${tones[status] || 'neutral'}">${safe(labels[status] || status)}</span>`;
  const button = (label, attrs = '', primary = false) =>
    `<button type="button" class="vr-button${primary ? ' vr-primary' : ''}" ${attrs}>${safe(label)}</button>`;
  const panel = content => `<section class="vr-panel">${content}</section>`;
  const heading = (title, subtitle = '') => `<header class="vr-heading"><h1>${safe(title)}</h1>${subtitle ? `<p>${safe(subtitle)}</p>` : ''}</header>`;
  const empty = (text, page = '', label = '') => panel(`<h2>${safe(text)}</h2>${page ? button(label, `data-page="${page}"`, true) : ''}`);
  const resources = plan => `${plan.cpu} vCPU · ${plan.ram_gb} GB RAM · ${plan.disk_gb} GB SSD`;
  const invoiceFor = order => order.invoices.find(item => item.kind === 'initial');
  const activeRental = rental => rental.status === 'active'
    && new Date(rental.expires_at) > new Date();

  function route() {
    const [page, id = ''] = location.hash.slice(1).split('/');
    return { page: page || 'home', id: Number(id) };
  }

  function go(page, id = '') {
    const hash = `${page}${id ? `/${id}` : ''}`;
    if (location.hash === `#${hash}`) render();
    else location.hash = hash;
  }

  function notice(message, error = false) {
    feedback.textContent = message;
    feedback.hidden = !message;
    feedback.classList.toggle('vr-feedback-error', error);
    feedback.setAttribute('role', error ? 'alert' : 'status');
  }

  async function api(path, method = 'GET', data) {
    const headers = { 'X-CSRF-Token': state.csrf };
    if (data !== undefined) headers['Content-Type'] = 'application/json';
    const response = await fetch(`/api${path}`, {
      method, credentials: 'same-origin', headers,
      body: data === undefined ? undefined : JSON.stringify(data),
    });
    if (response.status === 204) return null;
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(Array.isArray(result.detail)
        ? result.detail.map(item => `${item.loc.at(-1)}: ${item.msg}`).join('; ')
        : result.detail || 'The request could not be completed');
      error.status = response.status;
      throw error;
    }
    return result;
  }

  async function refresh() {
    const paths = { plans: '/plans' };
    const role = state.user?.role;
    if (role === 'customer') Object.assign(paths, {
      orders: '/orders', rentals: '/rentals', tickets: '/tickets',
      cards: '/cards',
    });
    const { page, id } = route();
    if (role === 'customer' && page === 'invoice' && id) {
      paths.invoice = `/invoices/${id}`;
    }
    if (role === 'operator') Object.assign(paths, {
      queue: '/operator/queue', pool: '/operator/servers',
      operations: '/operator/operations', activity: '/activity',
    });
    if (role === 'support') Object.assign(paths, {
      tickets: '/tickets', activity: '/activity',
    });
    if (role === 'manager') paths.managedPlans = '/management/plans';
    const entries = await Promise.all(Object.entries(paths).map(
      async ([key, path]) => [key, await api(path)]
    ));
    Object.assign(state, Object.fromEntries(entries));
    render();
  }

  function catalogue() {
    const columns = state.plans.map(plan => {
      const monthly = Math.min(plan.monthly_cents, plan.annual_cents / 12);
      return `<th scope="col" class="vr-plan-offer">
        <h2>${safe(plan.name)}</h2><p class="vr-plan-description">${safe(plan.description)}</p>
        <p class="vr-plan-regular">${monthly < plan.monthly_cents ? `<del>${money(plan.monthly_cents)}</del>` : '&nbsp;'}</p>
        <p class="vr-plan-price"><span class="vr-plan-from">From</span>${money(monthly)}</p>
        <p class="vr-plan-period">per month</p>
        ${button('Choose', `data-action="choose" data-id="${plan.id}"`, true)}
      </th>`;
    });
    const specs = [['CPU', 'cpu', 'vCPU'], ['RAM', 'ram_gb', 'GB'], ['SSD', 'disk_gb', 'GB']];
    return `<header class="vr-heading vr-catalogue-title"><h1>Linux VPS plans</h1><p>For your websites, APIs and bots.</p></header>`
      + (columns.length ? `<div class="vr-table-scroll"><table class="vr-plan-table" aria-label="Compare rental plans">
        <colgroup><col>${columns.map(() => '<col>').join('')}</colgroup>
        <thead><tr><th scope="col">Specs</th>${columns.join('')}</tr></thead>
        <tbody>${specs.map(([label, field, unit]) => `<tr><th scope="row">${label}</th>${state.plans.map(plan => `<td>${plan[field]} ${unit}</td>`).join('')}</tr>`).join('')}</tbody>
      </table></div>` : empty('No plans available'));
  }

  function checkout() {
    const plan = state.plans.find(item => item.id === state.selectedPlan);
    if (!plan) return heading('Choose a plan') + empty('Select an available plan', 'plans', 'View plans');
    const total = state.term === 'annual' ? plan.annual_cents : plan.monthly_cents;
    return heading('Review your order') + `<div class="vr-checkout">${panel(`<h2>${safe(plan.name)}</h2><p>${safe(plan.description)}</p><p class="vr-small">${resources(plan)}</p>`)}
      ${panel(`<form class="vr-form" data-form="order">
        <fieldset class="vr-terms"><legend>Rental term</legend>
          ${['monthly', 'annual'].map(term => `<label class="vr-term">
            <input type="radio" name="term" value="${term}" ${state.term === term ? 'checked' : ''}>
            <strong>${term === 'annual' ? 'Annual' : 'Monthly'} · ${duration(term)}</strong>
            <span class="vr-term-price"><strong>${money(term === 'annual' ? plan.annual_cents : plan.monthly_cents)}</strong>${term === 'annual' && plan.monthly_cents * 12 > plan.annual_cents ? `<del>${money(plan.monthly_cents * 12)}</del>` : ''}</span>
          </label>`).join('')}
        </fieldset>
        <div class="vr-row"><strong>Total due</strong><output class="vr-total-amount">${money(total)}</output></div>
        <div class="vr-actions"><button class="vr-button vr-primary">${state.user ? 'Place order' : 'Sign in to order'}</button>${button('Back', 'data-page="plans"')}</div>
      </form>`)}</div>`;
  }

  function paymentNote(payment) {
    if (!payment) return '';
    if (payment.status === 'failed') return `<p class="vr-small vr-payment-error">Last payment attempt failed: ${safe(payment.failure_reason || 'declined')}</p>`;
    if (payment.status === 'refunded') return `<p class="vr-small vr-payment-error">Payment refunded: ${safe(payment.failure_reason || '')}</p>`;
    if (payment.status === 'pending') return '<p class="vr-small">A monobank payment page is open. Finish it or check its status.</p>';
    return '';
  }

  function payBlock(invoice, label = 'Pay with monobank') {
    const pending = invoice.payment?.status === 'pending';
    return `<div class="vr-pay">
      ${paymentNote(invoice.payment)}
      ${pending ? '' : `<label class="vr-check"><input type="checkbox" data-save-card${state.saveCard ? ' checked' : ''}> Save card for automatic renewal</label>`}
      <div class="vr-actions">
        ${button(pending ? 'Continue payment' : label, `data-action="pay" data-id="${invoice.id}"`, true)}
        ${pending ? button('Check status', `data-page="invoice" data-id="${invoice.id}"`) : ''}
      </div>
      <p class="vr-small">${money(invoice.amount_cents)} is charged in euro through monobank.</p>
    </div>`;
  }

  function paidWith(payment) {
    return payment?.status === 'succeeded' ? 'Paid via monobank' : 'monobank';
  }

  function orderCard(order) {
    const invoice = invoiceFor(order);
    const paid = invoice.status === 'paid';
    const current = order.rental_id ? 3 : paid ? 2 : 1;
    const progress = ['Order placed', 'Payment', 'Allocation', 'Ready'];
    return `<details class="vr-order-entry" data-order="${order.id}" ${state.openOrders.has(order.id) ? 'open' : ''}>
      <summary class="vr-order-summary">
        <span class="vr-summary-id">#${order.id}</span><span>${safe(order.plan_name)}</span>
        <span class="vr-summary-term">${duration(order.term)}</span><span class="vr-summary-total">${money(order.price_cents)}</span>
        <span class="vr-summary-status"><span class="vr-payment-pill${paid ? '' : ' vr-unpaid'}">${paid ? 'Paid' : 'Unpaid'}</span>${badge(order.status)}</span>
        <span class="vr-order-chevron" aria-hidden="true">⌄</span>
      </summary>
      <div class="vr-order-expanded"><div class="vr-order-body">
        <section class="vr-order-card"><h2>${order.rental_id ? 'Your server is ready.' : paid ? 'Waiting for server allocation.' : 'Complete your payment.'}</h2>
          <ol class="vr-order-progress">${progress.map((label, index) => `<li${index < current ? ' class="vr-step-complete"' : ''}${index === current ? ' aria-current="step"' : ''}><span class="vr-step-marker">${index < current ? '✓' : index + 1}</span><span>${label}</span></li>`).join('')}</ol>
          <dl class="vr-order-specs"><div><dt>Processor</dt><dd>${order.cpu} vCPU</dd></div><div><dt>Memory</dt><dd>${order.ram_gb} GB RAM</dd></div><div><dt>Storage</dt><dd>${order.disk_gb} GB SSD</dd></div></dl>
          ${paid ? '' : payBlock(invoice)}
          ${order.rental_id ? button('Manage server', `data-page="server" data-id="${order.rental_id}"`, true) : ''}
        </section>
        <aside class="vr-invoice-card"><div class="vr-row"><h2>Invoice</h2>${badge(invoice.status)}</div>
          <span class="vr-small">${safe(invoice.number)}</span><div class="vr-invoice-amount"><strong>${money(invoice.amount_cents)}</strong></div>
          <dl class="vr-invoice-details"><div><dt>Plan</dt><dd>${safe(order.plan_name)}</dd></div><div><dt>Rental term</dt><dd>${duration(order.term)}</dd></div><div><dt>Payment</dt><dd>${paidWith(invoice.payment)}</dd></div></dl>
          ${order.invoices.filter(item => item.kind === 'renewal').map(item => `<div class="vr-row vr-small"><span>${safe(item.number)} · Renewal${item.payment?.initiated_by === 'auto' ? ' (auto)' : ''} · ${money(item.amount_cents)}</span>${badge(item.status)}</div>`).join('')}
        </aside>
      </div></div>
    </details>`;
  }

  function orders() {
    return heading('Orders & invoices') + (state.orders.length
      ? `<div class="vr-orders-list"><div class="vr-order-table-head" aria-hidden="true"><span>Order</span><span>Plan</span><span>Term</span><span>Total</span><span>Status</span><span></span></div>${state.orders.map(orderCard).join('')}</div>`
      : empty('No orders yet', 'plans', 'View plans'));
  }

  function servers() {
    const waiting = state.orders.filter(order => !order.rental_id);
    const rows = state.rentals.map(rental => `<button type="button" class="vr-server-row" data-page="server" data-id="${rental.id}">
      <span class="vr-server-name"><strong>${safe(rental.name)}</strong><small>${safe(rental.plan_name)} · ${resources(rental)}</small></span>
      <span class="vr-server-row-status"><span class="vr-small">Until ${date(rental.expires_at)}${rental.auto_renew_card_id && activeRental(rental) ? ' · Auto-renew on' : ''}</span>${badge(activeRental(rental) ? rental.power : rental.status)}<span class="vr-server-manage">Manage →</span></span>
    </button>`).concat(waiting.map(order => `<div class="vr-server-row"><span class="vr-server-name"><strong>${safe(order.plan_name)}</strong><small>${resources(order)}</small></span><span class="vr-server-row-status">${badge(order.status)}</span></div>`));
    return heading('My servers') + `<div class="vr-server-list">${rows.join('') || empty('No servers yet', 'plans', 'View plans')}</div>`;
  }

  function serverDetails(id) {
    const rental = state.rentals.find(item => item.id === id);
    if (!rental) return heading('Server not found') + button('My servers', 'data-page="servers"');
    const running = rental.power === 'running';
    const pending = rental.operations.some(item => item.status === 'pending');
    const disabled = pending || !activeRental(rental);
    return `<button type="button" class="vr-server-back" data-page="servers">← My servers</button>`
      + heading(rental.name) + `<section class="vr-server-panel" aria-label="Server control panel">
        <div class="vr-server-toolbar">${badge(activeRental(rental) ? rental.power : rental.status)}
          <div class="vr-actions" role="group" aria-label="Server operations">
            ${button(running ? 'Stop' : 'Start', `data-action="operation" data-id="${id}" data-kind="${running ? 'stop' : 'start'}" ${disabled ? 'disabled' : ''}`)}
            ${button('Restart', `data-action="operation" data-id="${id}" data-kind="restart" ${disabled || !running ? 'disabled' : ''}`)}
          </div>
        </div>
        <div class="vr-server-content"><dl class="vr-server-facts">
          <div><dt>IP address</dt><dd>${safe(rental.address)}</dd><dd class="vr-server-connection"><code class="vr-command">ssh ${safe(rental.ssh_user)}@${safe(rental.address)}</code></dd></div>
          <div><dt>Default user</dt><dd>${safe(rental.ssh_user)}</dd><dd class="vr-server-password">
            <label for="vr-server-password">Password</label><input id="vr-server-password" type="text" hidden readonly autocomplete="off" spellcheck="false">
            ${button('Show', `data-action="password" data-id="${id}" aria-controls="vr-server-password" aria-pressed="false" aria-label="Show server password" ${!activeRental(rental) ? 'disabled' : ''}`)}
          </dd></div>
          <div><dt>Rental term</dt><dd>${duration(rental.term)}</dd></div><div><dt>Expires</dt><dd>${date(rental.expires_at)}</dd></div>
        </dl>
        ${rental.operations.slice(0, 3).map(operation => `<div class="vr-server-request"><span>${safe(operation.kind)}${operation.result ? ` · ${safe(operation.result)}` : ''}</span>${badge(operation.status)}</div>`).join('')}
      </div></section>` + renewalSection(rental);
  }

  function renewalSection(rental) {
    const order = state.orders.find(item => item.id === rental.order_id);
    const open = order?.invoices.find(item => item.kind === 'renewal' && item.status === 'unpaid');
    const history = (order?.invoices || []).filter(item => item.kind === 'renewal' && item.status === 'paid').reverse();
    if (!activeRental(rental)) {
      return `<section class="vr-server-panel vr-renewal" aria-label="Renewal"><div class="vr-renewal-body">
        <h2>Renewal</h2><p class="vr-small">This rental has expired and can no longer be renewed. Contact support if you need the server back.</p>
      </div></section>`;
    }
    const cardOptions = state.cards.map(card => `<option value="${card.id}" ${card.id === rental.auto_renew_card_id ? 'selected' : ''}>${safe(card.masked_pan)}</option>`).join('');
    const autoRenew = state.cards.length
      ? `<label class="vr-field">Automatic renewal<select data-auto-renew data-id="${rental.id}"><option value="">Off</option>${cardOptions}</select></label>
         <p class="vr-small">${rental.auto_renew_at ? `The card is charged ${money(rental.renewal_cents)} from ${date(rental.auto_renew_at)}, before the rental expires. Failed charges are retried.` : 'Choose a saved card to renew this server automatically before it expires.'}</p>`
      : '<p class="vr-small">To renew automatically, pay once with "Save card for automatic renewal" selected.</p>';
    const cards = state.cards.length ? `<div class="vr-cards"><h3>Saved cards</h3>${state.cards.map(card => `<div class="vr-row vr-small"><span>${safe(card.masked_pan)} · added ${date(card.created_at)}</span>${button('Remove', `data-action="remove-card" data-id="${card.id}" aria-label="Remove card ${safe(card.masked_pan)}"`)}</div>`).join('')}</div>` : '';
    return `<section class="vr-server-panel vr-renewal" aria-label="Renewal"><div class="vr-renewal-body">
      <div class="vr-row"><h2>Renewal</h2><span class="vr-small">Expires ${date(rental.expires_at)}</span></div>
      <dl class="vr-invoice-details"><div><dt>Extension</dt><dd>30 days</dd></div><div><dt>Price</dt><dd>${money(rental.renewal_cents)}</dd></div></dl>
      ${open ? payBlock(open, 'Pay renewal') : `<div class="vr-pay"><label class="vr-check"><input type="checkbox" data-save-card${state.saveCard ? ' checked' : ''}> Save card for automatic renewal</label><div class="vr-actions">${button('Renew for 30 days', `data-action="renew" data-id="${rental.id}"`, true)}</div></div>`}
      <div class="vr-auto-renew">${autoRenew}</div>
      ${cards}
      ${history.length ? `<div class="vr-cards"><h3>Paid renewals</h3>${history.slice(0, 5).map(item => `<div class="vr-row vr-small"><span>${safe(item.number)} · ${date(item.paid_at)}${item.payment?.initiated_by === 'auto' ? ' · automatic' : ''}</span><span>${paidWith(item.payment)}</span></div>`).join('')}</div>` : ''}
    </div></section>`;
  }

  function invoicePage(id) {
    const invoice = state.invoice?.id === id ? state.invoice : null;
    if (!invoice) return heading('Payment') + panel('<p>Loading payment status…</p>');
    const payment = invoice.payment;
    const rental = invoice.rental_id && state.rentals.find(item => item.id === invoice.rental_id);
    const back = rental
      ? button('Back to server', `data-page="server" data-id="${rental.id}"`, true)
      : button('Back to orders', 'data-page="orders"', true);
    let title = 'Payment not started';
    let text = '';
    if (invoice.status === 'paid') {
      title = 'Payment received';
      text = invoice.kind === 'renewal'
        ? `Your rental was extended by 30 days${rental ? `, until ${date(rental.expires_at)}` : ''}.`
        : 'Your order is now waiting for server allocation.';
    } else if (payment?.status === 'pending') {
      title = 'Waiting for monobank';
      text = 'This page updates automatically once the bank confirms the payment.';
    } else if (payment?.status === 'failed') {
      title = 'Payment failed';
      text = payment.failure_reason || 'The bank declined the payment.';
    } else if (payment?.status === 'refunded') {
      title = 'Payment refunded';
      text = payment.failure_reason || 'The payment was returned to your card.';
    }
    return heading(title, `${invoice.number} · ${invoice.plan_name}`) + panel(`
      <div class="vr-row"><strong>${money(invoice.amount_cents)}</strong>${badge(payment?.status === 'pending' ? 'pending' : invoice.status)}</div>
      ${text ? `<p>${safe(text)}</p>` : ''}
      ${invoice.status === 'paid' || payment?.status === 'pending' ? '' : payBlock(invoice, 'Try again')}
      <div class="vr-actions">${payment?.status === 'pending' ? button('Continue payment', `data-action="pay" data-id="${invoice.id}"`) : ''}${back}</div>
    `);
  }

  function scheduleInvoicePoll() {
    clearTimeout(invoiceTimer);
    const { page, id } = route();
    if (page !== 'invoice' || state.invoice?.id !== id) return;
    if (state.invoice.payment?.status !== 'pending') return;
    invoiceTimer = setTimeout(async () => {
      if (route().page !== 'invoice') return;
      try { await refresh(); } catch (error) { notice(error.message, true); }
    }, 3000);
  }

  function pool() {
    return heading('Server pool') + state.pool.map(server => panel(`
      <div class="vr-row"><div><h2>${safe(server.name)}</h2><p class="vr-small">${safe(server.address)} · ${resources(server)}</p></div>${badge(server.rental_status || server.state)}</div>
      ${server.rental_status === 'suspension_pending' ? button('Confirm suspension', `data-action="suspend" data-id="${server.rental_id}"`) : ''}
      ${server.rental_status === 'suspended' ? `<form class="vr-form" data-form="prepare" data-id="${server.rental_id}"><label class="vr-field">New server password<input name="password" type="password" minlength="12" maxlength="128" autocomplete="new-password" required></label><button class="vr-button">Confirm preparation</button></form>` : ''}
    `)).join('') + `<details class="vr-panel"><summary>Add server</summary><form class="vr-form" data-form="server">
      ${field('Name', 'name', 'text', '', 'required maxlength="40"')}
      ${field('IP address', 'address', 'text', '', 'required')}
      ${field('SSH user', 'ssh_user', 'text', 'ubuntu', 'required pattern="[a-z_][a-z0-9_-]{0,31}"')}
      ${field('Password', 'password', 'password', '', 'required minlength="12" maxlength="128" autocomplete="new-password"')}
      <div class="vr-columns">${field('CPU', 'cpu', 'number', '1', 'min="1" required')}${field('RAM, GB', 'ram_gb', 'number', '2', 'min="1" required')}${field('SSD, GB', 'disk_gb', 'number', '25', 'min="1" required')}</div><button class="vr-button vr-primary">Add server</button>
    </form></details>`;
  }

  function queue() {
    return heading('Allocation queue') + (state.queue.length ? state.queue.map(order => {
      const matching = state.pool.filter(server => server.state === 'available'
        && ['cpu', 'ram_gb', 'disk_gb'].every(key => order[key] === server[key]));
      return panel(`<div class="vr-row"><h2>Order #${order.id} · ${safe(order.plan_name)}</h2>${badge(order.status)}</div><p class="vr-small">${resources(order)}</p>
        ${matching.length ? `<form class="vr-form" data-form="allocate" data-id="${order.id}"><label class="vr-field">Available server<select name="server_id">${matching.map(server => `<option value="${server.id}">${safe(server.name)} · ${safe(server.address)}</option>`).join('')}</select></label><button class="vr-button vr-primary">Assign server</button></form>` : '<p class="vr-small">No matching server available. This order stays in the queue.</p>'}`);
    }).join('') : empty('No orders awaiting allocation'));
  }

  function operations() {
    return heading('Operation requests') + (state.operations.length ? state.operations.map(operation => panel(`
      <div class="vr-row"><h2>${safe(operation.kind)} · ${safe(operation.server_name)}</h2>${badge(operation.status)}</div>
      ${operation.status === 'pending' ? `<form class="vr-form" data-form="resolve" data-id="${operation.id}"><label class="vr-field">Result<textarea name="result" required maxlength="2000"></textarea></label><div class="vr-actions"><button class="vr-button vr-primary" name="status" value="completed">Confirm completed</button><button class="vr-button" name="status" value="rejected">Reject</button></div></form>` : `<p>${safe(operation.result)}</p>`}
    `)).join('') : empty('No operation requests'));
  }

  function field(label, name, type = 'text', value = '', extra = '') {
    return `<label class="vr-field">${safe(label)}<input name="${name}" type="${type}" value="${safe(value)}" ${extra}></label>`;
  }

  function auth(register = false) {
    return heading(register ? 'Create an account' : 'Sign in') + panel(`<form class="vr-form" data-form="${register ? 'register' : 'login'}">
      ${field('Email', 'email', 'email', '', 'required autocomplete="username"')}
      ${field('Password', 'password', 'password', '', `required minlength="12" maxlength="128" autocomplete="${register ? 'new-password' : 'current-password'}"`)}
      <div class="vr-actions"><button class="vr-button vr-primary">${register ? 'Create account' : 'Sign in'}</button>${button(register ? 'Sign in' : 'Create account', `data-page="${register ? 'login' : 'register'}"`)}</div>
    </form>`);
  }

  function tickets() {
    return heading(state.user.role === 'support' ? 'Tickets' : 'Support')
      + (state.user.role === 'customer' ? button('New ticket', 'data-page="new-ticket"', true) : '')
      + (state.tickets.map(ticket => panel(`<div class="vr-row"><h2>#${ticket.id} · ${safe(ticket.subject)}</h2>${badge(ticket.status)}</div>${button('Open ticket', `data-page="ticket" data-id="${ticket.id}"`)}`)).join('') || empty('No tickets yet'));
  }

  function newTicket() {
    return heading('New ticket') + panel(`<form class="vr-form" data-form="ticket">
      ${field('Subject', 'subject', 'text', '', 'required maxlength="160"')}
      <label class="vr-field">Server<select name="rental_id"><option value="">General question</option>${state.rentals.map(rental => `<option value="${rental.id}">${safe(rental.name)}</option>`).join('')}</select></label>
      <label class="vr-field">Message<textarea name="body" required maxlength="5000"></textarea></label><button class="vr-button vr-primary">Send ticket</button>
    </form>`);
  }

  function ticketDetails(id) {
    const ticket = state.tickets.find(item => item.id === id);
    if (!ticket) return heading('Ticket not found');
    return heading(`#${id} · ${ticket.subject}`) + panel(`<div class="vr-row">${badge(ticket.status)}${state.user.role === 'support' ? `<div class="vr-actions">${['open', 'in_progress', 'closed'].map(status => button(labels[status], `data-action="ticket-status" data-id="${id}" data-status="${status}" ${status === ticket.status ? 'disabled' : ''}`)).join('')}</div>` : ''}</div>
      ${ticket.server ? `<p class="vr-small">${safe(ticket.server.name)} · ${safe(ticket.server.address)} · ${safe(labels[ticket.server.status])}</p>` : ''}
      ${ticket.messages.map(message => `<section class="vr-message"><div class="vr-row vr-small"><strong>${safe(message.author)}</strong><span>${date(message.created_at)}</span></div><p>${safe(message.body)}</p></section>`).join('')}
      ${ticket.status === 'closed' ? '' : `<form class="vr-form" data-form="reply" data-id="${id}"><label class="vr-field">Reply<textarea name="body" required maxlength="5000"></textarea></label><button class="vr-button vr-primary">Send reply</button></form>`}
    `);
  }

  function history() {
    return heading('Activity history') + (state.activity.map(item => panel(`<div class="vr-row"><strong>${safe(item.action.replaceAll('_', ' '))}</strong><span class="vr-small">${date(item.created_at)}</span></div><p>${safe(item.result)}</p><p class="vr-small">${safe(item.actor)} · ${safe(item.entity_type)} #${item.entity_id}</p>`)).join('') || empty('No activity yet'));
  }

  function manage() {
    return heading('Rental plans') + button('Create plan', 'data-page="edit-plan"', true)
      + state.managedPlans.map(plan => panel(`<div class="vr-row"><h2>${safe(plan.name)}</h2>${badge(plan.enabled ? 'active' : 'closed')}</div><p class="vr-small">${resources(plan)} · ${money(plan.monthly_cents)} / 30 days</p><div class="vr-actions">${button('Edit', `data-page="edit-plan" data-id="${plan.id}"`)}${button(plan.enabled ? 'Disable' : 'Enable', `data-action="toggle-plan" data-id="${plan.id}"`)}</div>`)).join('');
  }

  function editPlan(id) {
    const plan = state.managedPlans.find(item => item.id === id) || {};
    return heading(id ? 'Edit plan' : 'Create plan') + panel(`<form class="vr-form" data-form="plan" data-id="${id || ''}">
      ${field('Name', 'name', 'text', plan.name, 'required maxlength="40"')}
      ${field('Description', 'description', 'text', plan.description, 'required maxlength="160"')}
      <div class="vr-columns">${[['CPU', 'cpu'], ['RAM, GB', 'ram_gb'], ['SSD, GB', 'disk_gb'], ['30-day price, euro cents', 'monthly_cents'], ['Annual price, euro cents', 'annual_cents']].map(([label, key]) => field(label, key, 'number', plan[key] || '', 'min="1" required')).join('')}</div>
      <button class="vr-button vr-primary">Save plan</button>
    </form>`);
  }

  function render() {
    const role = state.user?.role || 'visitor';
    let { page, id } = route();
    if (page === 'home') page = menus[role][0][0];
    const parent = { checkout: 'plans', register: 'login', server: 'servers',
      ticket: 'tickets', 'new-ticket': 'tickets', 'edit-plan': 'manage', renew: 'servers',
      invoice: 'orders' };
    const available = menus[role].filter(([name]) => role !== 'customer'
      || name !== 'tickets' || state.orders.some(order => invoiceFor(order).status === 'paid'));
    nav.innerHTML = available.map(([name, label]) => `<button type="button" data-page="${name}" ${name === (parent[page] || page) ? 'aria-current="page"' : ''}>${label}</button>`).join('');
    root.querySelector('.vr-account').innerHTML = state.user ? button('Sign out', 'data-action="logout"') : '';
    root.querySelector('.vr-identity').textContent = state.user ? state.user.email : '';
    const screens = {
      plans: catalogue, checkout, orders, servers, server: () => serverDetails(id),
      login: () => auth(), register: () => auth(true), queue, pool, operations,
      tickets, 'new-ticket': newTicket, ticket: () => ticketDetails(id),
      history, manage, 'edit-plan': () => editPlan(id), renew: () => serverDetails(id),
      invoice: () => invoicePage(id),
    };
    const permitted = new Set(menus[role].map(([name]) => name));
    if (!screens[page] || !permitted.has(parent[page] || page)) {
      main.innerHTML = heading('Page unavailable') + button('Go back', 'data-page="home"');
      return;
    }
    main.innerHTML = screens[page]();
    scheduleInvoicePoll();
  }

  main.addEventListener('toggle', event => {
    const order = Number(event.target.dataset.order);
    if (!order) return;
    if (event.target.open) state.openOrders.add(order);
    else state.openOrders.delete(order);
  }, true);

  function saveCardChoice(control) {
    return Boolean(control.closest('.vr-pay')?.querySelector('[data-save-card]')?.checked);
  }

  async function startPayment(invoiceId, saveCard) {
    const payment = await api(`/invoices/${invoiceId}/payments`, 'POST', {
      idempotency_key: crypto.randomUUID(), save_card: saveCard,
    });
    if (payment.status === 'pending' && payment.page_url) {
      notice('Opening the monobank payment page…');
      location.assign(payment.page_url);
      return;
    }
    go('invoice', invoiceId);
    await refresh();
  }

  main.addEventListener('change', async event => {
    const select = event.target.closest('select[data-auto-renew]');
    if (select) {
      select.disabled = true;
      try {
        await api(`/rentals/${select.dataset.id}/auto-renew`, 'PUT', {
          card_id: select.value ? Number(select.value) : null,
        });
        await refresh();
        notice(select.value ? 'Automatic renewal enabled.' : 'Automatic renewal turned off.');
      } catch (error) { notice(error.message, true); await refresh().catch(() => {}); }
      return;
    }
    if (event.target.matches('[data-save-card]')) {
      state.saveCard = event.target.checked;
      return;
    }
    if (event.target.name !== 'term') return;
    state.term = event.target.value;
    const plan = state.plans.find(item => item.id === state.selectedPlan);
    main.querySelector('.vr-total-amount').textContent = money(state.term === 'annual' ? plan.annual_cents : plan.monthly_cents);
  });

  main.addEventListener('input', event => {
    const form = event.target.closest('form');
    if (form) form.dataset.dirty = 'true';
  });

  root.addEventListener('click', async event => {
    const control = event.target.closest('button[type="button"]');
    if (!control || control.disabled) return;
    const { action, page, id: rawId, kind, status } = control.dataset;
    const id = Number(rawId);
    if (page) {
      notice(''); go(page, id);
      try { await refresh(); } catch (error) { notice(error.message, true); }
      return;
    }
    if (!action) return;
    control.disabled = true;
    try {
      if (action === 'choose') {
        state.selectedPlan = id; state.term = 'monthly'; go('checkout');
      } else if (action === 'logout') {
        await api('/auth/logout', 'POST');
        state.user = null; state.csrf = ''; state.orders = [];
        state.rentals = []; state.tickets = []; state.openOrders.clear();
        await refresh(); go('plans');
      } else if (action === 'pay') {
        await startPayment(id, saveCardChoice(control));
      } else if (action === 'remove-card') {
        if (!confirm('Remove this card? Automatic renewal that uses it will be turned off.')) return;
        await api(`/cards/${id}`, 'DELETE'); await refresh();
        notice('Card removed.');
      } else if (action === 'operation') {
        await api(`/rentals/${id}/operations`, 'POST', { kind });
        await refresh(); notice('Request sent to the operator.');
      } else if (action === 'password') {
        const input = main.querySelector('#vr-server-password');
        if (input.hidden) {
          const result = await api(`/rentals/${id}/reveal-password`, 'POST');
          input.value = result.password; input.hidden = false;
          control.textContent = 'Hide';
          control.setAttribute('aria-pressed', 'true');
          control.setAttribute('aria-label', 'Hide server password');
        } else {
          input.value = ''; input.hidden = true; control.textContent = 'Show';
          control.setAttribute('aria-pressed', 'false');
          control.setAttribute('aria-label', 'Show server password');
        }
      } else if (action === 'suspend') {
        await api(`/operator/rentals/${id}/suspend`, 'POST'); await refresh();
      } else if (action === 'renew') {
        const invoice = await api(`/rentals/${id}/renewal-invoice`, 'POST');
        await startPayment(invoice.id, saveCardChoice(control));
      } else if (action === 'ticket-status') {
        await api(`/tickets/${id}/status`, 'POST', { status }); await refresh();
      } else if (action === 'toggle-plan') {
        const plan = state.managedPlans.find(item => item.id === id);
        const { id: ignored, ...data } = plan;
        await api(`/management/plans/${id}`, 'PUT', { ...data, enabled: !plan.enabled });
        await refresh();
      }
    } catch (error) { notice(error.message, true); }
    finally { control.disabled = false; }
  });

  root.addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.target;
    const submitter = event.submitter;
    const data = Object.fromEntries(new FormData(form, submitter));
    const id = Number(form.dataset.id);
    const controls = [...form.querySelectorAll('button')];
    controls.forEach(control => { control.disabled = true; });
    try {
      const type = form.dataset.form;
      if (type === 'login' || type === 'register') {
        const session = await api(`/auth/${type}`, 'POST', data);
        state.user = session.user; state.csrf = session.csrf_token;
        await refresh();
        go(state.selectedPlan && state.user.role === 'customer' ? 'checkout' : 'home');
      } else if (type === 'order') {
        if (!state.user) { go('login'); return; }
        const order = await api('/orders', 'POST', {
          plan_id: state.selectedPlan, term: data.term,
        });
        state.openOrders.add(order.id); await refresh(); go('orders');
      } else if (type === 'allocate') {
        await api(`/operator/orders/${id}/allocate`, 'POST', { server_id: Number(data.server_id) });
        await refresh(); notice('Server assigned.');
      } else if (type === 'resolve') {
        await api(`/operator/operations/${id}/resolve`, 'POST', data); await refresh();
      } else if (type === 'ticket') {
        const ticket = await api('/tickets', 'POST', {
          ...data, rental_id: data.rental_id ? Number(data.rental_id) : null,
        });
        await refresh(); go('ticket', ticket.id);
      } else if (type === 'reply') {
        await api(`/tickets/${id}/messages`, 'POST', data); await refresh();
      } else if (type === 'prepare') {
        await api(`/operator/rentals/${id}/prepare`, 'POST', data); await refresh();
      } else if (type === 'server') {
        for (const key of ['cpu', 'ram_gb', 'disk_gb']) data[key] = Number(data[key]);
        await api('/operator/servers', 'POST', data); await refresh();
      } else if (type === 'plan') {
        for (const key of ['cpu', 'ram_gb', 'disk_gb', 'monthly_cents', 'annual_cents']) data[key] = Number(data[key]);
        data.enabled = state.managedPlans.find(plan => plan.id === id)?.enabled ?? true;
        await api(`/management/plans${id ? `/${id}` : ''}`, id ? 'PUT' : 'POST', data);
        await refresh(); go('manage');
      }
    } catch (error) { notice(error.message, true); }
    finally { controls.forEach(control => { control.disabled = false; }); }
  });

  window.addEventListener('hashchange', () => { notice(''); render(); });
  async function start() {
    try {
      try {
        const session = await api('/auth/me');
        state.user = session.user; state.csrf = session.csrf_token;
      } catch (error) { if (error.status !== 401) throw error; }
      await refresh();
    } catch (error) {
      main.innerHTML = heading('Unable to load VPS Rent');
      notice(error.message, true);
    }
  }
  setInterval(async () => {
    if (document.hidden || state.loading || !state.user) return;
    if (!['orders', 'servers', 'server', 'renew', 'queue', 'operations', 'pool'].includes(route().page)) return;
    if (main.contains(document.activeElement)) return;
    if (main.querySelector('#vr-server-password:not([hidden])')) return;
    if (main.querySelector('form[data-dirty="true"]')) return;
    state.loading = true;
    try { await refresh(); }
    catch (error) { notice(error.message, true); }
    finally { state.loading = false; }
  }, 15000);
  start();
})();
