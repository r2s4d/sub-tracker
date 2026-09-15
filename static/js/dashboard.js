/*
 * Дашборд: кольцевая диаграмма по категориям и график расходов по месяцам.
 *
 * Подсказки - свои HTML-карточки (external tooltip Chart.js), оформленные как
 * строка выписки из остального интерфейса. Данные вставляются через textContent,
 * а не innerHTML: названия подписок вводит пользователь, HTML из них не выполнится.
 */
(function () {
  'use strict';

  const source = document.getElementById('dashboard-data');
  if (!source || !window.Chart) return;

  const data = JSON.parse(source.textContent);
  const css = getComputedStyle(document.documentElement);
  const token = (name) => css.getPropertyValue(name).trim();
  const colors = {
    ink: token('--st-ink'), muted: token('--st-muted'), line: token('--st-line'),
    accent: token('--st-accent'), surface: token('--st-surface'),
  };
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const rubShort = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB', maximumFractionDigits: 0 });
  const percent = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
  const plural = (n, one, few, many) => {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  };

  // Меняем только отдельные поля настроек. Замена целого объекта
  // Chart.defaults.animation ломала анимацию: сектора оставались «нулевой» длины
  // для проверки попадания курсора, и подсказки не появлялись.
  Chart.defaults.font.family = token('--st-font');
  Chart.defaults.font.size = 13;
  Chart.defaults.color = colors.muted;
  if (reduceMotion) Chart.defaults.animation.duration = 0;

  /* ---------- Построение DOM без innerHTML ---------- */

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Та же типографика сумм, что и в шаблонах (фильтр rub_html): рубли крупно, копейки мельче
  function money(value, className) {
    const [rubles, kopecks] = Number(value).toFixed(2).split('.');
    const wrap = el('span', `money ${className || ''}`.trim());
    wrap.append(
      document.createTextNode(Number(rubles).toLocaleString('ru-RU')),
      el('span', 'money-kop', `,${kopecks}`),
      el('span', 'money-cur', ' ₽'),
    );
    return wrap;
  }

  function row(label, value, className) {
    const line = el('div', `tip-row ${className || ''}`.trim());
    line.append(el('span', 'tip-row-label', label), value);
    return line;
  }

  /* ---------- Позиционирование подсказки ---------- */

  const EDGE = 8;

  /*
   * outside = true - карточка ставится снаружи графика (для кольца): с той стороны,
   * где курсор, а если там нет места - с противоположной, в крайнем случае под кольцом.
   * Иначе при наведении на левую половину карточка ложилась на кольцо и закрывала проценты.
   * outside = false - рядом с курсором (для линейного графика).
   */
  function placeTip(tip, chart, model, { outside = false } = {}) {
    if (model.opacity === 0) {
      tip.hidden = true;
      return;
    }
    tip.hidden = false;
    const rect = chart.canvas.getBoundingClientRect();
    const gap = 14;
    const width = tip.offsetWidth;
    const height = tip.offsetHeight;
    const fitsLeft = (x) => x >= EDGE;
    const fitsRight = (x) => x + width <= window.innerWidth - EDGE;
    let left;
    let top = rect.top + model.caretY - height / 2;

    if (outside) {
      const leftSide = rect.left - width - gap;
      const rightSide = rect.right + gap;
      const preferLeft = model.caretX < chart.width / 2;
      if (preferLeft && fitsLeft(leftSide)) left = leftSide;
      else if (fitsRight(rightSide)) left = rightSide;
      else if (fitsLeft(leftSide)) left = leftSide;
      else {
        // Узкий экран: ни слева, ни справа не помещается - под кольцом
        left = rect.left + rect.width / 2 - width / 2;
        top = rect.bottom + gap;
      }
    } else {
      left = rect.left + model.caretX + gap;
      if (!fitsRight(left)) left = rect.left + model.caretX - width - gap;
    }

    left = Math.min(Math.max(EDGE, left), window.innerWidth - width - EDGE);
    top = Math.min(Math.max(EDGE, top), window.innerHeight - height - EDGE);
    tip.style.left = `${left}px`;
    tip.style.top = `${top}px`;
  }

  function hideTipsOnScroll(...tips) {
    window.addEventListener('scroll', () => tips.forEach((tip) => { tip.hidden = true; }), { passive: true });
  }

  /* ---------- Кольцевая диаграмма по категориям ---------- */

  const categories = data.categories;
  const doughnutCanvas = document.getElementById('chart-categories');
  const categoryTip = document.querySelector('[data-tip="categories"]');
  const legend = document.querySelector('[data-legend]');
  const centerValue = document.querySelector('[data-center-value]');
  const centerLabel = document.querySelector('[data-center-label]');
  const defaultCenter = { value: centerValue.textContent, label: centerLabel.textContent };
  let selected = null;

  function fade(hex, alpha) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }

  function renderCategoryTip(index) {
    categoryTip.replaceChildren();
    categoryTip.style.setProperty('--cat-color', categories.colors[index]);
    const items = categories.items[index];
    const count = categories.counts[index];

    categoryTip.append(
      el('div', 'tip-title', categories.labels[index]),
      money(categories.values[index], 'tip-amount'),
      el('div', 'tip-sub', `в месяц, ${percent.format(categories.shares[index])}% всех расходов`),
    );
    const list = el('div', 'tip-list');
    items.slice(0, 3).forEach((item) => list.append(row(item.name, money(item.monthly))));
    if (items.length > 3) {
      const rest = items.length - 3;
      list.append(el('div', 'tip-more', `и ещё ${rest} ${plural(rest, 'подписка', 'подписки', 'подписок')}`));
    }
    categoryTip.append(list);
    const hint = selected === index ? 'Нажмите, чтобы свернуть' : `Нажмите, чтобы раскрыть ${count} ${plural(count, 'подписку', 'подписки', 'подписок')}`;
    categoryTip.append(el('div', 'tip-hint', hint));
  }

  function setCenter(index) {
    if (index === null) {
      centerValue.textContent = defaultCenter.value;
      centerLabel.textContent = defaultCenter.label;
      return;
    }
    centerValue.textContent = `${percent.format(categories.shares[index])}%`;
    centerLabel.textContent = categories.labels[index];
  }

  const doughnut = new Chart(doughnutCanvas, {
    type: 'doughnut',
    data: {
      labels: categories.labels,
      datasets: [{
        data: categories.values,
        backgroundColor: [...categories.colors],
        hoverBackgroundColor: [...categories.colors],
        borderColor: colors.surface,
        borderWidth: 2,
        hoverOffset: 8,
      }],
    },
    options: {
      cutout: '66%',
      maintainAspectRatio: false,
      layout: { padding: 8 },
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: false,
          external: ({ chart, tooltip }) => {
            if (tooltip.opacity !== 0 && tooltip.dataPoints?.length) {
              const index = tooltip.dataPoints[0].dataIndex;
              renderCategoryTip(index);
              setCenter(index);
            } else {
              setCenter(selected);
            }
            placeTip(categoryTip, chart, tooltip, { outside: true });
          },
        },
      },
    },
  });

  // Выбор категории: сектор выделяется, остальные приглушаются, строка легенды раскрывается
  function select(index) {
    selected = selected === index ? null : index;
    const dataset = doughnut.data.datasets[0];
    dataset.backgroundColor = categories.colors.map((color, i) => (
      selected === null || i === selected ? color : fade(color, 0.22)
    ));
    doughnut.update();

    legend.querySelectorAll('.legend-item').forEach((item) => {
      const isOpen = Number(item.dataset.index) === selected;
      item.classList.toggle('is-open', isOpen);
      item.querySelector('.legend-toggle').setAttribute('aria-expanded', String(isOpen));
      item.querySelector('.legend-items').hidden = !isOpen;
    });
    setCenter(selected);
    if (selected !== null) renderCategoryTip(selected);
  }

  doughnutCanvas.addEventListener('click', (event) => {
    const [hit] = doughnut.getElementsAtEventForMode(event, 'nearest', { intersect: true }, true);
    if (hit) select(hit.index);
  });
  doughnutCanvas.style.cursor = 'pointer';

  legend.addEventListener('click', (event) => {
    const toggle = event.target.closest('.legend-toggle');
    if (toggle) select(Number(toggle.closest('.legend-item').dataset.index));
  });

  // Связанная подсветка: наведение на строку легенды подсвечивает сектор
  legend.addEventListener('mouseover', (event) => {
    const item = event.target.closest('.legend-item');
    if (!item) return;
    const index = Number(item.dataset.index);
    doughnut.setActiveElements([{ datasetIndex: 0, index }]);
    doughnut.update('none');
    setCenter(index);
  });
  legend.addEventListener('mouseleave', () => {
    doughnut.setActiveElements([]);
    doughnut.update('none');
    setCenter(selected);
  });

  /* ---------- График расходов по месяцам ---------- */

  const months = data.months;
  const monthsTip = document.querySelector('[data-tip="months"]');
  let selectedMonth = null;

  function renderMonthTip(index) {
    monthsTip.replaceChildren();
    const actual = months.actual[index];
    const planned = months.planned[index];
    const breakdown = months.breakdown[index] || [];

    monthsTip.append(el('div', 'tip-title', months.titles[index]));
    if (actual !== null) {
      monthsTip.append(money(actual, 'tip-amount'), el('div', 'tip-sub', 'оплачено'));
    } else {
      monthsTip.append(money(planned, 'tip-amount'), el('div', 'tip-sub', 'спишется по плану'));
    }
    if (actual !== null && planned !== null) {
      monthsTip.append(row('По плану за месяц', money(planned), 'tip-row-plan'));
    }
    if (breakdown.length) {
      const list = el('div', 'tip-list');
      breakdown.slice(0, 4).forEach(([name, amount]) => list.append(row(name, money(amount))));
      if (breakdown.length > 4) {
        const restSum = breakdown.slice(4).reduce((sum, [, amount]) => sum + amount, 0);
        const rest = breakdown.length - 4;
        list.append(el('div', 'tip-more', `и ещё ${rest} ${plural(rest, 'платёж', 'платежа', 'платежей')} на ${rubShort.format(restSum)}`));
      }
      monthsTip.append(list);
    } else if (actual === 0) {
      monthsTip.append(el('div', 'tip-hint', 'Платежей в этом месяце не отмечено'));
    }
    if (actual !== null) {
      const hint = selectedMonth === index ? 'Нажмите, чтобы свернуть список' : 'Нажмите, чтобы увидеть все платежи';
      monthsTip.append(el('div', 'tip-hint', hint));
    }
  }

  // Вертикальная линия под курсором: видно, к какому месяцу относится подсказка
  const crosshair = {
    id: 'crosshair',
    afterDatasetsDraw(chart) {
      const active = chart.tooltip?.getActiveElements();
      if (!active?.length) return;
      const { ctx, chartArea } = chart;
      const x = active[0].element.x;
      ctx.save();
      ctx.strokeStyle = colors.line;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, chartArea.top);
      ctx.lineTo(x, chartArea.bottom);
      ctx.stroke();
      ctx.restore();
    },
  };

  const monthsCanvas = document.getElementById('chart-months');
  const monthsChart = new Chart(monthsCanvas, {
    type: 'line',
    data: {
      labels: months.labels,
      datasets: [
        {
          label: 'Оплачено',
          data: months.actual,
          borderColor: colors.accent,
          backgroundColor: colors.accent,
          borderWidth: 2,
          tension: 0, // без сглаживания: кривая «выдумывала» бы значения между месяцами
          pointRadius: 3,
          pointHoverRadius: 6,
          pointHitRadius: 12,
          pointBackgroundColor: colors.accent,
          pointBorderColor: colors.surface,
          pointBorderWidth: 2,
        },
        {
          label: 'По плану',
          data: months.planned,
          borderColor: colors.muted,
          backgroundColor: colors.muted,
          borderWidth: 2,
          borderDash: [6, 5],
          tension: 0,
          pointRadius: 3,
          pointHoverRadius: 6,
          pointHitRadius: 12,
          pointBackgroundColor: colors.surface,
          pointBorderColor: colors.muted,
          pointBorderWidth: 2,
        },
      ],
    },
    plugins: [crosshair],
    options: {
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false, axis: 'x' },
      scales: {
        // Подписи месяцев без наклона: в узкой колонке лишние пропускаются, а не поворачиваются
        x: { grid: { display: false }, border: { color: colors.line }, ticks: { maxRotation: 0, autoSkip: true, autoSkipPadding: 10 } },
        y: {
          beginAtZero: true,
          border: { display: false },
          grid: { color: colors.line, drawTicks: false },
          ticks: { padding: 8, maxTicksLimit: 5, callback: (value) => rubShort.format(value) },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: false,
          external: ({ chart, tooltip }) => {
            if (tooltip.opacity !== 0 && tooltip.dataPoints?.length) {
              renderMonthTip(tooltip.dataPoints[0].dataIndex);
            }
            placeTip(monthsTip, chart, tooltip);
          },
        },
      },
    },
  });

  /* ---------- Раскрытие месяца: все платежи под графиком ---------- */

  const monthDetail = document.querySelector('[data-month-detail]');
  const detailUrl = (pk) => monthDetail.dataset.detailUrl.replace('/0/', `/${pk}/`);

  function highlightMonth(index) {
    // Выбранная точка крупнее - видно, чей список открыт
    const radius = months.actual.map((_, i) => (i === index ? 7 : 3));
    monthsChart.data.datasets[0].pointRadius = radius;
    monthsChart.update('none');
  }

  function renderMonthDetail(index) {
    const payments = months.payments[index] || [];
    const total = payments.reduce((sum, p) => sum + p.amount, 0);
    const head = el('div', 'month-detail-head');
    const title = el('div');
    title.append(
      el('h3', 'month-detail-title', `Платежи за ${months.titles[index].toLowerCase()}`),
      el('p', 'month-detail-sub', payments.length
        ? `${payments.length} ${plural(payments.length, 'платёж', 'платежа', 'платежей')} на ${rubShort.format(total)}`
        : 'В этом месяце платежей не отмечено'),
    );
    const close = el('button', 'btn btn-outline-secondary btn-sm', 'Свернуть');
    close.type = 'button';
    close.addEventListener('click', () => toggleMonth(index));
    head.append(title, close);

    const list = el('ul', 'ledger month-detail-list');
    payments.forEach((payment) => {
      const item = el('li', 'ledger-row month-detail-row');
      item.style.setProperty('--cat-color', payment.color);
      const main = el('div');
      const link = el('a', 'ledger-title', payment.name);
      link.href = detailUrl(payment.pk);
      main.append(link, el('div', 'ledger-meta', payment.method || 'способ оплаты не указан'));
      item.append(main, el('div', 'month-detail-date', payment.date), el('div', 'ledger-amount'));
      item.lastChild.append(money(payment.amount));
      list.append(item);
    });
    monthDetail.replaceChildren(head, list);
  }

  function toggleMonth(index) {
    if (months.actual[index] === null) return;  // будущий месяц: платежей ещё нет
    selectedMonth = selectedMonth === index ? null : index;
    highlightMonth(selectedMonth);
    if (selectedMonth === null) {
      monthDetail.hidden = true;
      monthsChart.resize();
      return;
    }
    renderMonthDetail(selectedMonth);
    monthDetail.hidden = false;
    monthsChart.resize();  // на обзоре «в один экран» график делит высоту колонки со списком
    monthDetail.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'nearest' });
  }

  monthsCanvas.addEventListener('click', (event) => {
    const [hit] = monthsChart.getElementsAtEventForMode(event, 'index', { intersect: false, axis: 'x' }, true);
    if (hit) toggleMonth(hit.index);
  });
  monthsCanvas.style.cursor = 'pointer';
  document.querySelector('.dash-table')?.addEventListener('toggle', () => monthsChart.resize());

  /* ---------- Календарь списаний ---------- */

  const calendar = document.querySelector('[data-calendar]');
  if (calendar) {
    const monthsInCalendar = [...calendar.querySelectorAll('[data-cal-month]')];
    const title = calendar.querySelector('[data-cal-title]');
    const summary = calendar.querySelector('[data-cal-summary]');
    const prev = calendar.querySelector('[data-cal-prev]');
    const next = calendar.querySelector('[data-cal-next]');
    const upcoming = document.querySelector('[data-upcoming]');
    const dayDetails = [...document.querySelectorAll('[data-day-detail]')];
    let current = 0;

    function showDay(day) {
      calendar.querySelectorAll('.cal-day[aria-pressed]').forEach((cell) => {
        cell.setAttribute('aria-pressed', String(cell.dataset.day === day));
      });
      dayDetails.forEach((detail) => { detail.hidden = detail.dataset.dayDetail !== day; });
      upcoming.hidden = Boolean(day);
    }

    function showMonth(index) {
      current = index;
      monthsInCalendar.forEach((month, i) => { month.hidden = i !== index; });
      title.textContent = monthsInCalendar[index].dataset.title;
      summary.textContent = monthsInCalendar[index].dataset.summary;
      prev.disabled = index === 0;
      next.disabled = index === monthsInCalendar.length - 1;
      showDay(null);
    }

    prev.addEventListener('click', () => showMonth(current - 1));
    next.addEventListener('click', () => showMonth(current + 1));
    calendar.addEventListener('click', (event) => {
      const cell = event.target.closest('.cal-day[aria-pressed]');
      if (!cell) return;
      showDay(cell.getAttribute('aria-pressed') === 'true' ? null : cell.dataset.day);
    });
    document.addEventListener('click', (event) => {
      if (event.target.closest('[data-show-upcoming]')) showDay(null);
    });
    showMonth(0);
  }

  hideTipsOnScroll(categoryTip, monthsTip);
})();
