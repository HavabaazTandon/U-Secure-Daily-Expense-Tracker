/* U - charts. Reads server-rendered JSON from #chart-data; no inline scripts, no network calls. */
(function () {
  "use strict";
  if (typeof Chart === "undefined") return;
  var dataEl = document.getElementById("chart-data");
  if (!dataEl) return;
  var data = JSON.parse(dataEl.textContent);

  var C = {
    text: "#292725", muted: "#858079", border: "#E9E5DF", accent: "#B77983",
    dark: "#94636D", taupe: "#A69B91", surface: "#FFFFFF", blushSoft: "#F3E5E7"
  };

  var rupee = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 });
  var compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });
  var money = function (v) { return rupee.format(v); };

  Chart.defaults.font.family = '"DM Sans", system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = C.muted;
  Chart.defaults.borderColor = C.border;
  Chart.defaults.animation.duration = 450;

  var tooltip = {
    backgroundColor: C.text, titleColor: "#FFFFFF", bodyColor: "#F0EDE8",
    padding: 10, cornerRadius: 8, boxPadding: 4, displayColors: true,
    titleFont: { family: '"Manrope", sans-serif', weight: "600" }
  };

  function el(id) { return document.getElementById(id); }

  function trendChart(canvas) {
    var t = data.trend;
    var peak = Math.max.apply(null, t.values);
    var colors = t.values.map(function (v, i) {
      return i === t.values.length - 1 ? C.accent : "#DDB9BF";
    });
    new Chart(canvas, {
      type: "bar",
      data: { labels: t.labels, datasets: [{ label: "Spent", data: t.values, backgroundColor: colors, hoverBackgroundColor: C.dark, borderRadius: 6, borderSkipped: false, maxBarThickness: 44 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: Object.assign({}, tooltip, { callbacks: { label: function (c) { return " " + money(c.parsed.y); } } }) },
        scales: {
          x: { grid: { display: false }, border: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
          y: { beginAtZero: true, suggestedMax: peak ? undefined : 100, border: { display: false }, ticks: { maxTicksLimit: 5, callback: function (v) { return compact.format(v); } }, grid: { color: C.border } }
        }
      }
    });
  }

  function doughnut(canvas, d) {
    new Chart(canvas, {
      type: "doughnut",
      data: { labels: d.labels, datasets: [{ data: d.values, backgroundColor: d.colors, borderColor: C.surface, borderWidth: 3, hoverOffset: 4 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "68%",
        plugins: {
          legend: { display: false },
          tooltip: Object.assign({}, tooltip, { callbacks: { label: function (c) {
            var total = c.dataset.data.reduce(function (a, b) { return a + b; }, 0);
            var share = total ? (c.parsed / total * 100).toFixed(1) : "0.0";
            return " " + money(c.parsed) + " (" + share + "%)";
          } } })
        }
      }
    });
  }

  function comparisonChart(canvas) {
    var c = data.comparison;
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: c.labels,
        datasets: [
          { label: c.previous_label, data: c.previous, backgroundColor: c.colors.previous, borderRadius: 5, borderSkipped: false },
          { label: c.current_label, data: c.current, backgroundColor: c.colors.current, borderRadius: 5, borderSkipped: false }
        ]
      },
      options: {
        responsive: true, maintainAspectRatio: false, indexAxis: "y",
        plugins: {
          legend: { position: "bottom", labels: { usePointStyle: true, pointStyle: "rectRounded", boxWidth: 10, boxHeight: 10, padding: 16, color: C.text } },
          tooltip: Object.assign({}, tooltip, { callbacks: { label: function (x) { return " " + x.dataset.label + ": " + money(x.parsed.x); } } })
        },
        scales: {
          x: { beginAtZero: true, border: { display: false }, grid: { color: C.border }, ticks: { maxTicksLimit: 5, callback: function (v) { return compact.format(v); } } },
          y: { grid: { display: false }, border: { display: false }, ticks: { color: C.text } }
        }
      }
    });
  }

  var trend = el("trendChart");
  if (trend && data.trend) trendChart(trend);
  var cat = el("categoryChart");
  if (cat && data.categories) doughnut(cat, data.categories);
  var dist = el("distributionChart");
  if (dist && data.distribution) doughnut(dist, data.distribution);
  var cmp = el("comparisonChart");
  if (cmp && data.comparison) comparisonChart(cmp);
})();
