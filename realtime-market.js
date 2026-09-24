(() => {
  const chartElement = document.getElementById('chart');
  if (!chartElement || !window.LightweightCharts) return;

  const symbol = (window.MDR_CHART_SYMBOL || 'BTCUSDT').toUpperCase();
  const interval = window.MDR_CHART_INTERVAL || '1m';
  let chart;
  let series;
  let socket;
  let reconnectTimer;

  const setStatus = (text, good = true) => {
    const node = document.getElementById('marketStatus');
    if (node) {
      node.textContent = text;
      node.className = good ? 'text-[#00d084] text-xs' : 'text-yellow-400 text-xs';
    }
  };

  function createChart() {
    chart = LightweightCharts.createChart(chartElement, {
      layout: { background: { color: '#090d12' }, textColor: '#8a9bb0' },
      grid: { vertLines: { color: '#17202b' }, horzLines: { color: '#17202b' } },
      rightPriceScale: { borderColor: '#263241' },
      timeScale: { borderColor: '#263241', timeVisible: true, secondsVisible: false },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      width: chartElement.clientWidth,
      height: Math.max(280, chartElement.clientHeight || 420)
    });
    series = chart.addCandlestickSeries({
      upColor: '#00d084', downColor: '#ff5572', borderUpColor: '#00d084',
      borderDownColor: '#ff5572', wickUpColor: '#00d084', wickDownColor: '#ff5572'
    });
  }

  async function loadHistory() {
    const url = `https://api.binance.com/api/v3/klines?symbol=${encodeURIComponent(symbol)}&interval=${encodeURIComponent(interval)}&limit=500`;
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error(`market history ${response.status}`);
    const rows = await response.json();
    series.setData(rows.map(row => ({ time: Math.floor(row[0] / 1000), open: +row[1], high: +row[2], low: +row[3], close: +row[4] })));
    chart.timeScale().fitContent();
  }

  function connect() {
    clearTimeout(reconnectTimer);
    if (socket) socket.close();
    socket = new WebSocket(`wss://stream.binance.com:9443/ws/${symbol.toLowerCase()}@kline_${interval}`);
    socket.onopen = () => setStatus(`Live ${symbol} · ${interval}`);
    socket.onmessage = event => {
      const candle = JSON.parse(event.data).k;
      series.update({ time: Math.floor(candle.t / 1000), open: +candle.o, high: +candle.h, low: +candle.l, close: +candle.c });
      const price = document.getElementById('priceInput');
      if (price && document.activeElement !== price) price.value = (+candle.c).toFixed(2);
      const ticker = document.getElementById('tickerPrice');
      if (ticker) ticker.textContent = (+candle.c).toLocaleString(undefined, { maximumFractionDigits: 2 });
    };
    socket.onerror = () => setStatus('Live feed reconnecting…', false);
    socket.onclose = () => { setStatus('Live feed reconnecting…', false); reconnectTimer = setTimeout(connect, 3000); };
  }

  createChart();
  loadHistory().then(connect).catch(error => { console.warn(error); setStatus('Live history unavailable; retrying…', false); connect(); });
  window.addEventListener('resize', () => chart.applyOptions({ width: chartElement.clientWidth, height: Math.max(280, chartElement.clientHeight || 420) }));
  window.addEventListener('beforeunload', () => socket && socket.close());
})();
