(() => {
  'use strict';

  const root = document.getElementById('vps-rent-app');
  const main = root.querySelector('.vr-main');
  const nav = root.querySelector('.vr-nav');
  const feedback = root.querySelector('.vr-feedback');
  const state = {
    user: null, csrf: '', plans: [], orders: [], rentals: [], tickets: [],
    queue: [], pool: [], operations: [], activity: [], managedPlans: [],
    cards: [], invoice: null, saveCard: false, counts: {}, ticket: null,
    server: null, filters: {},
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
    manager: [['manage', 'Rental plans'], ['history', 'History']],
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
    succeeded: 'Succeeded', refunded: 'Refunded', disabled: 'Disabled',
    reserved: 'Queued', uncertain: 'Needs review', refund_pending: 'Refund pending',
    start: 'Start', stop: 'Stop', restart: 'Restart',
  };
  const tones = {
    paid: 'good', active: 'good', running: 'good', completed: 'good',
    available: 'good', succeeded: 'good', refunded: 'bad',
    failed: 'bad', expired: 'bad', stopped: 'bad',
    rejected: 'bad', awaiting_payment: 'warn', awaiting_allocation: 'warn',
    pending: 'warn', suspension_pending: 'warn', suspended: 'warn',
    open: 'warn', in_progress: 'info',
  };
  const ticketStatuses = ['open', 'in_progress', 'closed'];
  const activityActions = {
    ticket_created: 'Ticket opened', ticket_status: 'Status changed',
    ticket_reply: 'Reply added', order_created: 'Order placed',
    allocated: 'Server allocated', operation_requested: 'Operation requested',
    operation_resolved: 'Operation resolved', password_viewed: 'Password viewed',
    rental_expired: 'Rental expired', suspended: 'Access suspended',
    prepared: 'Server prepared', server_added: 'Server added',
    plan_created: 'Plan created', plan_updated: 'Plan updated',
    payment_started: 'Payment started', payment_succeeded: 'Payment received',
    payment_failed: 'Payment failed', payment_refunded: 'Payment refunded',
    payment_reversed: 'Payment reversed', renewal_invoice: 'Renewal invoice created',
    rental_renewed: 'Rental renewed', auto_renew: 'Automatic renewal changed',
    auto_renewal_charged: 'Automatic renewal charged',
    auto_renewal_failed: 'Automatic renewal failed',
  };
  // History filters: support filters by action, other staff by entity type.
  const activityFilters = {
    // A value matches the action/entity type, or `action:result` for one outcome.
    support: [['all', 'All'], ['ticket_created', 'Opened'], ['ticket_reply', 'Replies'],
      ['ticket_status:in_progress', 'In Progress'], ['ticket_status:closed', 'Closed'], ['ticket_status:open', 'Reopened']],
    operator: [['all', 'All'], ['order', 'Orders'], ['invoice', 'Payments'], ['rental', 'Rentals'], ['server', 'Servers'], ['operation', 'Operations']],
    manager: [['all', 'All'], ['plan', 'Plans']],
  };
  const entityPages = {
    ticket: 'ticket', order: 'queue', rental: 'pool', server: 'pool',
    operation: 'operations', plan: 'edit-plan',
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
  const time = value => new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
  }).format(new Date(value));
  const stamp = value => `${date(value)}, ${time(value)}`;
  const duration = term => term === 'annual' ? '12 months' : '30 days';
  const badge = status => `<span class="vr-badge vr-${tones[status] || 'neutral'}">${safe(labels[status] || status)}</span>`;
  const button = (label, attrs = '', primary = false) =>
    `<button type="button" class="vr-button${primary ? ' vr-primary' : ''}" ${attrs}>${safe(label)}</button>`;
  const panel = content => `<section class="vr-panel">${content}</section>`;
  const heading = (title, subtitle = '') => `<header class="vr-heading"><h1>${safe(title)}</h1>${subtitle ? `<p>${safe(subtitle)}</p>` : ''}</header>`;
  const empty = (text, page = '', label = '') => panel(`<h2>${safe(text)}</h2>${page ? button(label, `data-page="${page}"`, true) : ''}`);
  const resources = plan => `${plan.cpu} vCPU · ${plan.ram_gb} GB RAM · ${plan.disk_gb} GB SSD`;
  const invoiceFor = order => order.invoices.find(item => item.kind === 'initial');
  const back = (page, label) => `<button type="button" class="vr-server-back" data-page="${page}">← ${safe(label)}</button>`;
  const facts = items => `<dl class="vr-server-facts">${items.map(([term, value]) => `<div><dt>${safe(term)}</dt><dd>${value}</dd></div>`).join('')}</dl>`;
  // In-page filter built from the workspace menu style: [[value, label, count?]].
  const filterNav = (name, options, current) => `<nav class="vr-nav vr-filter" aria-label="${safe(name)}">${options.map(([value, label, count]) => `<button type="button" data-filter="${value}" ${value === current ? 'aria-current="true"' : ''}>${safe(label)}${count === undefined ? '' : `<span class="vr-count">${count}</span>`}</button>`).join('')}</nav>`;
  // The other side wrote last, so the ticket is waiting for the viewer.
  const awaitingViewer = ticket => ticket.status !== 'closed'
    && ticket.awaiting_support === (state.user.role === 'support');
  // Staff messages are always "Support": another agent may have written them.
  const author = name => name === 'support' ? 'Support'
    : state.user.role === 'customer' ? 'You' : 'Customer';
  const hour = 3600000;
  // "12 min", "3 h 5 min", "1 d 7 h" since a timestamp.
  const since = value => {
    const minutes = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 60000));
    const [days, hours, mins] = [Math.floor(minutes / 1440), Math.floor(minutes / 60) % 24, minutes % 60];
    return days ? `${days} d ${hours} h` : hours ? `${hours} h ${mins} min` : `${mins} min`;
  };
  const paidAt = order => invoiceFor(order).paid_at;
  // Filters are applied by the API and remembered per page.
  const defaultFilter = page => ({
    operations: 'pending', tickets: state.user?.role === 'support' ? 'awaiting' : 'all',
  })[page] || 'all';
  const filterFor = page => state.filters[page] ?? defaultFilter(page);
  // Paged lists: state[key] holds the rows shown, lists[key] where to continue.
  const pageSize = 50;
  const lists = {};
  const moreButton = key => lists[key]?.cursor
    ? `<div class="vr-actions">${button('Show more', `data-action="more" data-list="${key}"`)}</div>` : '';
  const resultHints = {
    start: 'Started at the provider.', stop: 'Stopped at the provider.',
    restart: 'Restarted at the provider.',
  };
  // Day-grouped cards of log rows, used by history and resolved operations.
  const dayGroups = (items, key, row, noun) => {
    const today = new Date().toISOString().slice(0, 10);
    const days = new Map();
    for (const item of items) {
      const day = new Date(item[key]).toISOString().slice(0, 10);
      days.set(day, [...(days.get(day) || []), item]);
    }
    return `<div class="vr-log">${[...days].map(([day, list]) => `<section class="vr-server-panel" aria-label="${date(day)}">
      <div class="vr-server-toolbar"><h2>${day === today ? `Today · ${date(day)}` : date(day)}</h2><span class="vr-small">${list.length} ${noun}${list.length === 1 ? '' : 's'}</span></div>
      ${list.map(row).join('')}
    </section>`).join('')}</div>`;
  };
  const activeRental = rental => rental.status === 'active'
    && new Date(rental.expires_at) > new Date();

  // "Home" (no hash, or #home) is the role's first menu page, so loading,
  // filters, polling and rendering all agree on which page is shown.
  function route() {
    const [hash, id = ''] = location.hash.slice(1).split('/');
    const page = hash && hash !== 'home' ? hash : menus[state.user?.role || 'visitor'][0][0];
    return { page, id: Number(id) };
  }

  // Navigate and load what the new page shows. location.hash updates at
  // once, so refresh() already sees the new route; the later hashchange event
  // for this hash is ignored (it would reload twice and clear a new notice).
  let routed = '';
  async function go(page, id = '') {
    const hash = `${page}${id ? `/${id}` : ''}`;
    notice('');
    if (location.hash !== `#${hash}`) { routed = `#${hash}`; location.hash = hash; }
    await refresh();
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

  async function loadList(key, path, more = false) {
    const known = lists[key]?.path === path;
    const target = more || !known ? pageSize : Math.max(pageSize, state[key].length);
    const items = [];
    let cursor = more && known ? lists[key].cursor : null;
    do {
      const query = new URLSearchParams({limit: Math.min(200, target - items.length)});
      if (cursor) query.set('cursor', cursor);
      const page = await api(`${path}${path.includes('?') ? '&' : '?'}${query}`);
      items.push(...page.items);
      cursor = page.next_cursor;
    } while (cursor && items.length < target);
    lists[key] = {path, cursor};
    return more ? [...state[key], ...items] : items;
  }

  async function refresh() {
    const paths = { plans: '/plans' };
    const paged = {};
    const role = state.user?.role;
    const { page, id } = route();
    const filter = encodeURIComponent(filterFor(page));
    if (role === 'customer') {
      Object.assign(paths, { orders: '/orders', rentals: '/rentals', cards: '/cards' });
      if (page === 'invoice' && id) state.invoice = await api(`/invoices/${id}`);
      if (page === 'tickets') paged.tickets = '/tickets';
    }
    if (role === 'support' && page === 'tickets') paged.tickets = `/tickets?status=${filter}`;
    if ((role === 'customer' || role === 'support') && page === 'ticket' && id) paths.ticket = `/tickets/${id}`;
    if (role === 'operator') {
      if (page === 'queue' || page === 'add-server') paged.queue = '/operator/queue';
      if (page === 'pool') paged.pool = `/operator/servers?filter=${filter}`;
      if (page === 'prepare' && id) paths.server = `/operator/servers/${id}`;
      if (page === 'operations') paged.operations = `/operator/operations?status=${filter}`;
    }
    if (role === 'support' || role === 'operator') paths.counts = '/counts';
    if (role === 'manager') paths.managedPlans = '/management/plans';
    if (['support', 'operator', 'manager'].includes(role) && page === 'history') {
      paged.activity = `/activity?filter=${filter}`;
    }
    const entries = await Promise.all([
      ...Object.entries(paths).map(async ([key, path]) => [key, await api(path)]),
      ...Object.entries(paged).map(async ([key, path]) => [key, await loadList(key, path)]),
    ]);
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
    if (payment.review_required) return '<p class="vr-small vr-payment-error">Payment needs review. No automatic retry will be made. Please contact support.</p>';
    if (payment.status === 'uncertain') return '<p class="vr-small">Bank confirmation is unknown. Another charge is blocked until this attempt is reconciled.</p>';
    if (payment.status === 'reserved') return '<p class="vr-small">Automatic renewal is queued.</p>';
    if (payment.status === 'refund_pending') return '<p class="vr-small">Refund requested. Waiting for confirmation from monobank.</p>';
    if (payment.status === 'failed') return `<p class="vr-small vr-payment-error">Last payment attempt failed: ${safe(payment.failure_reason || 'declined')}</p>`;
    if (payment.status === 'refunded') return `<p class="vr-small vr-payment-error">Payment refunded: ${safe(payment.failure_reason || '')}</p>`;
    if (payment.status === 'pending') return '<p class="vr-small">A monobank payment page is open. Finish it or check its status.</p>';
    return '';
  }

  const openPayment = payment => payment && ['reserved', 'uncertain', 'pending', 'refund_pending'].includes(payment.status);

  function payBlock(invoice, label = 'Pay with monobank · Test') {
    const pending = invoice.payment?.status === 'pending';
    const blocked = openPayment(invoice.payment) || invoice.payment?.review_required;
    const canContinue = pending && invoice.payment.page_url && invoice.payment.initiated_by !== 'auto';
    return `<div class="vr-pay">
      ${paymentNote(invoice.payment)}
      ${blocked ? '' : `<label class="vr-check"><input type="checkbox" data-save-card${state.saveCard ? ' checked' : ''}> Save card for automatic renewal</label>`}
      <div class="vr-actions">
        ${!blocked || canContinue ? button(canContinue ? 'Continue payment' : label, `data-action="pay" data-id="${invoice.id}"`, true) : ''}
        ${blocked ? button('Check status', `data-page="invoice" data-id="${invoice.id}"`) : ''}
      </div>
      <p class="vr-small">Monobank test mode · No real money is charged. EUR prices are charged in UAH at the quoted rate shown by the bank.</p>
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
    return back('servers', 'My servers') + heading(rental.name) + `<section class="vr-server-panel" aria-label="Server control panel">
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

  function savedCards() {
    return state.cards.length ? `<div class="vr-cards"><h3>Saved cards</h3>${state.cards.map(card => `<div class="vr-row vr-small"><span>${safe(card.masked_pan)} · added ${date(card.created_at)}</span>${button('Remove', `data-action="remove-card" data-id="${card.id}" aria-label="Remove card ${safe(card.masked_pan)}"`)}</div>`).join('')}</div>` : '';
  }

  function renewalSection(rental) {
    const order = state.orders.find(item => item.id === rental.order_id);
    const open = order?.invoices.find(item => item.kind === 'renewal' && item.status === 'unpaid');
    const history = (order?.invoices || []).filter(item => item.kind === 'renewal' && item.status === 'paid').reverse();
    if (!activeRental(rental)) {
      return `<section class="vr-server-panel vr-renewal" aria-label="Renewal"><div class="vr-renewal-body">
        <h2>Renewal</h2><p class="vr-small">This rental has expired and can no longer be renewed. Contact support if you need the server back.</p>${savedCards()}
        <div class="vr-actions">${button('Contact support', `data-page="new-ticket" data-id="${rental.id}"`)}</div>
      </div></section>`;
    }
    const cardOptions = state.cards.map(card => `<option value="${card.id}" ${card.id === rental.auto_renew_card_id ? 'selected' : ''}>${safe(card.masked_pan)}</option>`).join('');
    const autoRenew = state.cards.length
      ? `<label class="vr-field">Automatic renewal<select data-auto-renew data-id="${rental.id}"><option value="">Off</option>${cardOptions}</select></label>
         <p class="vr-small">${rental.auto_renew_at ? `The card is charged ${money(rental.renewal_cents)} from ${date(rental.auto_renew_at)}, before the rental expires. Failed charges are retried.` : 'Choose a saved card to renew this server automatically before it expires.'}</p>`
      : '<p class="vr-small">To renew automatically, pay once with "Save card for automatic renewal" selected.</p>';
    const cards = savedCards();
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
    const canPay = rental ? activeRental(rental)
      : state.orders.some(order => order.id === invoice.order_id && order.status === 'awaiting_payment');
    const back = rental
      ? button('Back to server', `data-page="server" data-id="${rental.id}"`, true)
      : button('Back to orders', 'data-page="orders"', true);
    let title = 'Payment not started';
    let text = '';
    if (payment?.review_required || payment?.status === 'uncertain') {
      title = 'Payment needs review';
      text = 'Bank confirmation is unknown. No new charge will be made until this attempt is reconciled. Please contact support.';
    } else if (payment?.status === 'refund_pending') {
      title = 'Refund pending';
      text = 'The refund has been requested and is awaiting confirmation from monobank.';
    } else if (payment?.status === 'reserved') {
      title = 'Automatic renewal queued';
    } else if (invoice.status === 'paid') {
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
      ${!canPay || invoice.status === 'paid' || openPayment(payment) || payment?.review_required ? '' : payBlock(invoice, 'Try again')}
      <div class="vr-actions">${payment?.status === 'pending' && payment.page_url && payment.initiated_by !== 'auto' ? button('Continue payment', `data-action="pay" data-id="${invoice.id}"`) : ''}${back}</div>
    `);
  }

  function scheduleInvoicePoll() {
    clearTimeout(invoiceTimer);
    const { page, id } = route();
    if (page !== 'invoice' || state.invoice?.id !== id) return;
    if (!openPayment(state.invoice.payment)) return;
    invoiceTimer = setTimeout(async () => {
      if (route().page !== 'invoice') return;
      try { await refresh(); } catch (error) { notice(error.message, true); }
    }, 3000);
  }

  function queue() {
    const orders = state.queue;
    return heading('Allocation queue', 'Paid orders waiting for a server, oldest first.')
      + (orders.length ? `<div class="vr-server-list">${orders.map(order => {
        const servers = order.matching_servers;
        const late = Date.now() - Date.parse(paidAt(order)) > 24 * hour;
        return `<section class="vr-server-panel" aria-label="Order #${order.id}">
          <div class="vr-server-toolbar"><h2>Order #${order.id} · ${safe(order.plan_name)}</h2><span class="vr-payment-pill ${late ? 'vr-failed' : 'vr-unpaid'}">Waiting ${since(paidAt(order))}</span></div>
          <div class="vr-server-content">${facts([
            ['Customer', safe(order.customer)], ['Term', duration(order.term)],
            ['Resources', `${order.cpu} vCPU · ${order.ram_gb} GB<br><span class="vr-small">${order.disk_gb} GB SSD</span>`],
            ['Paid', stamp(paidAt(order))],
          ])}</div>
          ${order.invoices.some(invoice => invoice.payment?.review_required) ? '<p class="vr-small vr-payment-error">Payment needs review. Allocation is blocked.</p>' : servers.length
            ? `<form class="vr-form vr-inline-form" data-form="allocate" data-id="${order.id}"><label class="vr-field">Matching server<select name="server_id">${servers.map(server => `<option value="${server.id}">${safe(server.name)} · ${safe(server.address)}</option>`).join('')}</select></label><button class="vr-button vr-primary">Assign server</button></form>`
            : `<div class="vr-row"><p class="vr-small">No available server with ${resources(order)}.</p>${button('Add matching server', `data-page="add-server" data-id="${order.id}"`)}</div>`}
        </section>`;
      }).join('')}</div>${moreButton('queue')}` : empty('No orders awaiting allocation'));
  }

  function poolRow(server) {
    const rental = server.rental_id
      ? ` · Rental #${server.rental_id} · ${safe(server.customer)} · ${server.rental_status === 'active' ? 'until' : 'expired'} ${date(server.expires_at)}` : '';
    const action = server.rental_status === 'suspension_pending'
      ? button('Suspend access', `data-action="suspend" data-id="${server.rental_id}"`)
      : server.rental_status === 'suspended'
        ? button('Prepare for reuse', `data-page="prepare" data-id="${server.id}"`, true) : '';
    return `<div class="vr-server-row">
      <span class="vr-server-name"><strong>${safe(server.name)} · ${safe(server.address)}</strong><small class="vr-excerpt">${resources(server)}${rental}</small></span>
      <span class="vr-server-row-status">${badge(server.rental_status || server.state)}${action}</span>
    </div>`;
  }

  function pool() {
    const counts = state.counts.pool || {};
    return `<div class="vr-row">${heading('Server pool', 'Suspensions and preparation wait under "Needs action".')}${button('Add server', 'data-page="add-server"', true)}</div>`
      + filterNav('Filter servers', [['all', 'All'], ['action', 'Needs action'], ['available', 'Available'], ['assigned', 'Rented']].map(([value, label]) => [value, label, counts[value]]), filterFor('pool'))
      + `<div class="vr-server-list">${state.pool.map(poolRow).join('') || empty('No servers in this group')}</div>${moreButton('pool')}`;
  }

  function addServer(orderId) {
    const order = state.queue.find(item => item.id === orderId);
    const spec = order || { cpu: 1, ram_gb: 2, disk_gb: 25 };
    const origin = order ? 'queue' : 'pool';
    return back(origin, order ? 'Allocation queue' : 'Server pool')
      + heading('Add server', order ? `Prefilled to match order #${order.id} (${resources(order)}).` : 'Register a VPS that is already provisioned at the provider.')
      + `<section class="vr-server-panel" aria-label="New server"><form class="vr-form" data-form="server" data-origin="${origin}">
        <div class="vr-columns">${field('Name', 'name', 'text', '', 'required maxlength="40"')}${field('IP address', 'address', 'text', '', 'required')}</div>
        <div class="vr-columns">${field('SSH user', 'ssh_user', 'text', 'ubuntu', 'required pattern="[a-z_][a-z0-9_-]{0,31}"')}${field('Password', 'password', 'password', '', 'required minlength="12" maxlength="128" autocomplete="new-password"')}</div>
        <div class="vr-columns">${field('CPU', 'cpu', 'number', spec.cpu, 'min="1" required')}${field('RAM, GB', 'ram_gb', 'number', spec.ram_gb, 'min="1" required')}${field('SSD, GB', 'disk_gb', 'number', spec.disk_gb, 'min="1" required')}</div>
        <div class="vr-actions"><button class="vr-button vr-primary">Add server</button>${button('Cancel', `data-page="${origin}"`)}</div>
      </form></section>`;
  }

  function prepare(id) {
    const server = state.server?.id === id ? state.server : null;
    if (!server || server.rental_status !== 'suspended') return heading('Nothing to prepare') + back('pool', 'Server pool');
    const steps = ['Stop and wipe at the provider', 'Reinstall the OS', 'Set a new password', 'Confirm here'];
    return back('pool', 'Server pool') + heading(`Prepare ${server.name}`, `${server.address} · ${resources(server)}`)
      + `<section class="vr-server-panel" aria-label="Preparation">
        <div class="vr-server-toolbar">${badge(server.rental_status)}<span class="vr-small">Rental #${server.rental_id} · ${safe(server.customer)} · expired ${date(server.expires_at)}</span></div>
        <div class="vr-server-content"><ol class="vr-order-progress">${steps.map((step, index) => `<li${index === steps.length - 1 ? ' aria-current="step"' : ''}><span class="vr-step-marker">${index + 1}</span><span>${step}</span></li>`).join('')}</ol></div>
        <form class="vr-form" data-form="prepare" data-id="${server.rental_id}">
          <p class="vr-small">The previous customer must not keep access: use a password that differs from the one they had.</p>
          <div class="vr-columns">${field('New server password', 'password', 'password', '', 'required minlength="12" maxlength="128" autocomplete="new-password"')}${field('Repeat password', 'repeat', 'password', '', 'required minlength="12" maxlength="128" autocomplete="new-password"')}</div>
          <div class="vr-actions"><button class="vr-button vr-primary">Confirm preparation</button>${button('Cancel', 'data-page="pool"')}</div>
        </form>
      </section>`;
  }

  function pendingCard(operation) {
    return `<section class="vr-server-panel" aria-label="Operation #${operation.id}">
      <div class="vr-server-toolbar"><h2>${labels[operation.kind]} · ${safe(operation.server_name)}</h2><span class="vr-small">Requested ${since(operation.created_at)} ago</span>${badge(operation.status)}</div>
      <div class="vr-server-content">${facts([
        ['Customer', safe(operation.customer)], ['IP address', safe(operation.address)],
        ['Power now', badge(operation.power)], ['Rental until', date(operation.expires_at)],
      ])}</div>
      <form class="vr-form" data-form="resolve" data-id="${operation.id}">
        <label class="vr-field">Result for the customer<textarea name="result" required maxlength="2000">${resultHints[operation.kind]}</textarea></label>
        <div class="vr-actions"><button class="vr-button vr-primary" name="status" value="completed">Confirm ${labels[operation.kind].toLowerCase()}</button><button class="vr-button" name="status" value="rejected">Reject</button><span class="vr-small">Requested ${stamp(operation.created_at)}</span></div>
      </form>
    </section>`;
  }

  function resolvedRow(operation) {
    return `<div class="vr-log-row">
      <time class="vr-small" datetime="${safe(operation.resolved_at)}">${time(operation.resolved_at)}</time>
      <span class="vr-log-what"><strong>${labels[operation.kind]} · ${safe(operation.server_name)}</strong>${badge(operation.status)}<span class="vr-small">${safe(operation.result)}</span></span>
      <span class="vr-small vr-log-actor" title="${safe(operation.customer)}">${safe(operation.customer)}</span>
      <span class="vr-small vr-log-actor" title="${safe(operation.resolved_by)}">by ${safe(operation.resolved_by)}</span>
    </div>`;
  }

  function operations() {
    const filter = filterFor('operations');
    const items = state.operations;
    return heading('Operation requests', 'Customers are waiting: confirm each action only after doing it at the provider.')
      + filterNav('Filter operations', [['pending', 'Pending', state.counts.operations?.pending], ['resolved', 'Resolved']], filter)
      + (filter === 'pending'
        ? (items.length ? `<div class="vr-server-list">${items.map(pendingCard).join('')}</div>` : empty('No pending requests'))
        : (items.length ? dayGroups(items, 'resolved_at', resolvedRow, 'request') : empty('No resolved requests')))
      + moreButton('operations');
  }

  function field(label, name, type = 'text', value = '', extra = '') {
    return `<label class="vr-field">${safe(label)}<input name="${name}" type="${type}" value="${safe(value)}" ${extra}></label>`;
  }

  function auth(register = false) {
    return heading(register ? 'Create an account' : 'Sign in') + panel(`<form class="vr-form" data-form="${register ? 'register' : 'login'}">
      ${field('Email', 'email', 'email', '', 'required autocomplete="username"')}
      ${field('Password', 'password', 'password', '', `required minlength="12" maxlength="128" autocomplete="${register ? 'new-password' : 'current-password'}"`)}
      <div class="vr-actions"><button class="vr-button vr-primary">${register ? 'Create account' : 'Sign in'}</button>${button(register ? 'Sign in' : 'Create account', `data-page="${register ? 'login' : 'register'}"`)}</div>
    </form>
    ${state.googleEnabled ? '<a class="vr-button vr-google" href="/api/auth/google/start">Continue with Google</a>' : ''}`);
  }

  function ticketRow(ticket) {
    const support = state.user.role === 'support';
    const last = ticket.last_message;
    const context = [support && ticket.customer, ticket.server_name]
      .filter(Boolean).map(safe).join(' · ');
    const pill = awaitingViewer(ticket)
      ? `<span class="vr-payment-pill${support ? ' vr-unpaid' : ''}">${support ? 'Needs reply' : 'New reply'}</span>` : '';
    return `<button type="button" class="vr-server-row" data-page="ticket" data-id="${ticket.id}">
      <span class="vr-server-name"><strong>#${ticket.id} · ${safe(ticket.subject)}</strong>
        <small class="vr-excerpt">${context ? `${context} · ` : ''}${author(last.author)}: ${safe(last.body)}</small></span>
      <span class="vr-server-row-status">${pill}<span class="vr-small">${stamp(ticket.last_message_at)}</span>${badge(ticket.status)}<span class="vr-server-manage">Open →</span></span>
    </button>`;
  }

  function tickets() {
    const support = state.user.role === 'support';
    const filter = filterFor('tickets');
    const counts = state.counts.tickets || {};
    const filters = [['awaiting', 'Needs reply'], ...ticketStatuses.map(status => [status, labels[status]]), ['all', 'All']];
    const none = filter === 'awaiting' ? 'Nobody is waiting for a reply' : 'No tickets with this status';
    return `<div class="vr-row">${heading(support ? 'Tickets' : 'Support', support ? 'Most recent conversations first.' : 'Ask about your servers, payments or account.')}${support ? '' : button('New ticket', 'data-page="new-ticket"', true)}</div>`
      + (support ? filterNav('Filter tickets', filters.map(([value, label]) => [value, label, counts[value]]), filter) : '')
      + `<div class="vr-server-list">${state.tickets.map(ticketRow).join('') || empty(support ? none : 'No tickets yet')}</div>${moreButton('tickets')}`;
  }

  function newTicket(rentalId) {
    return back('tickets', 'Support') + heading('New ticket') + panel(`<form class="vr-form" data-form="ticket">
      ${field('Subject', 'subject', 'text', '', 'required maxlength="160"')}
      <label class="vr-field">Server<select name="rental_id"><option value="">General question</option>${state.rentals.map(rental => `<option value="${rental.id}" ${rental.id === rentalId ? 'selected' : ''}>${safe(rental.name)}</option>`).join('')}</select></label>
      <label class="vr-field">Message<textarea name="body" required maxlength="5000"></textarea></label><button class="vr-button vr-primary">Send ticket</button>
    </form>`);
  }

  function ticketDetails(id) {
    const support = state.user.role === 'support';
    const ticket = state.ticket?.id === id ? state.ticket : null;
    if (!ticket) return heading('Ticket not found') + back('tickets', support ? 'Tickets' : 'Support');
    const server = ticket.server;
    const context = [
      ['Server', server ? `${safe(server.name)}<br><span class="vr-small">${safe(server.address)}</span>` : 'General question'],
      ...(server ? [['Rental', badge(server.status)], ['Expires', date(server.expires_at)]] : []),
      support ? ['Customer', safe(ticket.customer)] : ['Messages', ticket.messages.length],
    ];
    const statusControl = support
      ? `<div class="vr-actions" role="group" aria-label="Ticket status">${ticketStatuses.map(status => button(labels[status], `data-action="ticket-status" data-id="${id}" data-status="${status}" aria-pressed="${status === ticket.status}"`)).join('')}</div>`
      : `<span class="vr-small">Updated ${stamp(ticket.last_message_at)}</span>`;
    const footer = ticket.status === 'closed'
      ? `<div class="vr-row"><p class="vr-note">This ticket is closed${support ? '. Reopen it to reply.' : '. Open a new ticket if the problem returns.'}</p>${support ? '' : button('New ticket', `data-page="new-ticket" data-id="${ticket.rental_id || ''}"`)}</div>`
      : `<form class="vr-form" data-form="reply" data-id="${id}">
          <label class="vr-field">Reply<textarea name="body" required maxlength="5000" placeholder="${support ? 'Write to the customer…' : 'Add details for the support team…'}"></textarea></label>
          <div class="vr-actions"><button class="vr-button vr-primary">Send reply</button>${support && ticket.status === 'open' ? '<span class="vr-small">Replying moves the ticket to In Progress.</span>' : ''}</div>
        </form>`;
    return back('tickets', support ? 'Tickets' : 'Support')
      + heading(ticket.subject, `#${id} · Opened ${stamp(ticket.created_at)}`)
      + `<section class="vr-server-panel" aria-label="Ticket">
          <div class="vr-server-toolbar">${badge(ticket.status)}${statusControl}</div>
          <div class="vr-server-content">${facts(context)}</div>
        </section>
        <section class="vr-server-panel vr-thread" aria-label="Conversation">
          ${ticket.messages.map(message => `<article class="vr-message${message.author === 'support' ? ' vr-message-staff' : ''}">
            <div class="vr-row vr-small"><strong>${author(message.author)}</strong><time datetime="${safe(message.created_at)}">${stamp(message.created_at)}</time></div>
            <p>${safe(message.body)}</p>
          </article>`).join('')}
          ${footer}
        </section>`;
  }

  function activityRow(item) {
    const page = entityPages[item.entity_type];
    const entity = `${item.entity_type[0].toUpperCase()}${item.entity_type.slice(1)} #${item.entity_id}`;
    return `<div class="vr-log-row">
      <time class="vr-small" datetime="${safe(item.created_at)}">${time(item.created_at)}</time>
      <span class="vr-log-what"><strong>${safe(activityActions[item.action] || item.action.replaceAll('_', ' '))}</strong>${labels[item.result] ? badge(item.result) : `<span class="vr-small">${safe(item.result)}</span>`}</span>
      <span class="vr-small vr-log-actor" title="${safe(item.actor)}">${safe(item.actor)}</span>
      ${page ? `<button type="button" class="vr-link" data-page="${page}" data-id="${item.entity_id}">${entity} →</button>` : `<span class="vr-small">${entity}</span>`}
    </div>`;
  }

  function history() {
    const role = state.user.role;
    const subtitles = {
      support: 'Ticket actions by customers and the support team.',
      operator: 'Orders, payments, rentals, servers and operation requests.',
      manager: 'Changes to rental plans.',
    };
    return heading('Activity history', subtitles[role])
      + filterNav('Filter activity', activityFilters[role], filterFor('history'))
      + (state.activity.length ? dayGroups(state.activity, 'created_at', activityRow, 'event') + moreButton('activity') : empty('No activity yet'));
  }

  function manage() {
    return heading('Rental plans') + button('Create plan', 'data-page="edit-plan"', true)
      + state.managedPlans.map(plan => panel(`<div class="vr-row"><h2>${safe(plan.name)}</h2>${badge(plan.enabled ? 'active' : 'disabled')}</div><p class="vr-small">${resources(plan)} · ${money(plan.monthly_cents)} / 30 days</p><div class="vr-actions">${button('Edit', `data-page="edit-plan" data-id="${plan.id}"`)}${button(plan.enabled ? 'Disable' : 'Enable', `data-action="toggle-plan" data-id="${plan.id}"`)}</div>`)).join('');
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
    const { page, id } = route();
    const parent = { checkout: 'plans', register: 'login', server: 'servers',
      ticket: 'tickets', 'new-ticket': 'tickets', 'edit-plan': 'manage', renew: 'servers',
      invoice: 'orders', 'add-server': 'pool', prepare: 'pool' };
    // Work waiting for staff, shown next to the menu item.
    const counts = {
      support: { tickets: () => state.counts.tickets?.awaiting },
      operator: {
        queue: () => state.counts.queue,
        pool: () => state.counts.pool?.action,
        operations: () => state.counts.operations?.pending,
      },
    }[role] || {};
    nav.innerHTML = menus[role].map(([name, label]) => {
      const count = counts[name]?.() || 0;
      return `<button type="button" data-page="${name}" ${name === (parent[page] || page) ? 'aria-current="page"' : ''}>${label}${count ? `<span class="vr-count">${count}</span>` : ''}</button>`;
    }).join('');
    root.querySelector('.vr-account').innerHTML = state.user ? (state.googleEnabled && !state.user.google_linked ? '<a href="/api/auth/google/start?link=true">Link Google account</a> ' : '') + button('Sign out', 'data-action="logout"') : '';
    root.querySelector('.vr-identity').textContent = state.user ? state.user.email : '';
    const screens = {
      plans: catalogue, checkout, orders, servers, server: () => serverDetails(id),
      login: () => auth(), register: () => auth(true), queue, pool, operations,
      'add-server': () => addServer(id), prepare: () => prepare(id),
      tickets, 'new-ticket': () => newTicket(id), ticket: () => ticketDetails(id),
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
    await go('invoice', invoiceId);
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
    const { action, page, filter, id: rawId, kind, status } = control.dataset;
    const id = Number(rawId);
    if (filter) {
      state.filters[route().page] = filter;
      try { await refresh(); } catch (error) { notice(error.message, true); }
      return;
    }
    if (page) {
      try { await go(page, id); } catch (error) { notice(error.message, true); }
      return;
    }
    if (!action) return;
    control.disabled = true;
    try {
      if (action === 'choose') {
        state.selectedPlan = id; state.term = 'monthly'; await go('checkout');
      } else if (action === 'logout') {
        await api('/auth/logout', 'POST');
        state.user = null; state.csrf = ''; state.orders = [];
        state.rentals = []; state.tickets = []; state.openOrders.clear();
        Object.assign(state, { counts: {}, ticket: null, server: null, filters: {} });
        for (const key of Object.keys(lists)) delete lists[key];
        await go('plans');
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
        if (!confirm('Suspend access? Confirm only after stopping the server at the provider.')) return;
        await api(`/operator/rentals/${id}/suspend`, 'POST'); await refresh();
        notice('Access suspended. Prepare the server before reuse.');
      } else if (action === 'renew') {
        const invoice = await api(`/rentals/${id}/renewal-invoice`, 'POST');
        await startPayment(invoice.id, saveCardChoice(control));
      } else if (action === 'more') {
        const key = control.dataset.list;
        state[key] = await loadList(key, lists[key].path, true); render();
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
        await go(state.selectedPlan && state.user.role === 'customer' ? 'checkout' : 'home');
      } else if (type === 'order') {
        if (!state.user) { await go('login'); return; }
        const order = await api('/orders', 'POST', {
          plan_id: state.selectedPlan, term: data.term,
        });
        state.selectedPlan = null;
        state.openOrders.add(order.id); await go('orders');
      } else if (type === 'allocate') {
        await api(`/operator/orders/${id}/allocate`, 'POST', { server_id: Number(data.server_id) });
        await refresh(); notice('Server assigned.');
      } else if (type === 'resolve') {
        await api(`/operator/operations/${id}/resolve`, 'POST', data); await refresh();
        notice(data.status === 'completed' ? 'Request completed.' : 'Request rejected.');
      } else if (type === 'ticket') {
        const ticket = await api('/tickets', 'POST', {
          ...data, rental_id: data.rental_id ? Number(data.rental_id) : null,
        });
        state.ticket = ticket; await go('ticket', ticket.id);
      } else if (type === 'reply') {
        await api(`/tickets/${id}/messages`, 'POST', data); await refresh();
        notice('Reply sent.');
      } else if (type === 'prepare') {
        if (data.password !== data.repeat) throw new Error('The passwords do not match.');
        await api(`/operator/rentals/${id}/prepare`, 'POST', { password: data.password });
        await go('pool'); notice('Server is ready for allocation.');
      } else if (type === 'server') {
        for (const key of ['cpu', 'ram_gb', 'disk_gb']) data[key] = Number(data[key]);
        await api('/operator/servers', 'POST', data);
        await go(form.dataset.origin); notice('Server added.');
      } else if (type === 'plan') {
        for (const key of ['cpu', 'ram_gb', 'disk_gb', 'monthly_cents', 'annual_cents']) data[key] = Number(data[key]);
        data.enabled = state.managedPlans.find(plan => plan.id === id)?.enabled ?? true;
        await api(`/management/plans${id ? `/${id}` : ''}`, id ? 'PUT' : 'POST', data);
        await go('manage');
      }
    } catch (error) { notice(error.message, true); }
    finally { controls.forEach(control => { control.disabled = false; }); }
  });

  // Back/forward and typed addresses: load the page; go() already did.
  window.addEventListener('hashchange', async () => {
    const own = location.hash === routed;
    routed = '';
    if (own) return;
    notice('');
    try { await refresh(); } catch (error) { notice(error.message, true); }
  });
  async function start() {
    try {
      state.googleEnabled = (await api('/auth/google/config')).enabled;
      try {
        const session = await api('/auth/me');
        state.user = session.user; state.csrf = session.csrf_token;
      } catch (error) { if (error.status !== 401) throw error; }
      await refresh();
      // The Google callback redirects here when sign-in did not complete.
      if (location.hash === '#login/google-relogin') notice('Sign out and sign in again with your password, then choose Link Google account.', true);
      if (location.hash === '#login/google-failed') notice('Google sign-in failed. For an existing account, sign in with your password and choose Link Google account.', true);
    } catch (error) {
      main.innerHTML = heading('Unable to load VPS Rent');
      notice(error.message, true);
    }
  }
  setInterval(async () => {
    if (document.hidden || state.loading || !state.user) return;
    if (!['orders', 'servers', 'server', 'renew', 'queue', 'operations', 'pool', 'tickets', 'ticket', 'history'].includes(route().page)) return;
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
