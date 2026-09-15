/*
 * Дашборд: кольцевая диаграмма по категориям и график расходов по месяцам.
 *
 * Подсказки — свои HTML-карточки (external tooltip Chart.js), оформленные как
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

  function placeTip(tip, chart, model) {
    if (model.opacity === 0) {
      tip.hidden = true;
      return;
    }
    tip.hidden = false;
    const rect = chart.canvas.getBoundingClientRect();
    const gap = 14;
    const width = tip.offsetWidth;
    const height = tip.offsetHeight;
    let left = rect.left + model.caretX + gap;
    let top = rect.top + model.caretY - height / 2;
    // Не даём карточке уйти за край окна: справа места нет — показываем слева от курсора
    if (left + width > window.innerWidth - 8) left = rect.left + model.caretX - width - gap;
    left = Math.max(8, left);
    top = Math.min(Math.max(8, top), window.innerHeight - height - 8);
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
            placeTip(categoryTip, chart, tooltip);
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

  new Chart(document.getElementById('chart-months'), {
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
        x: { grid: { display: false }, border: { color: colors.line } },
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

  hideTipsOnScroll(categoryTip, monthsTip);
})();
